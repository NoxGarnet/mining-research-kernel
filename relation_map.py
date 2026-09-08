"""Deterministic, read-only relation mapping for the ceramsite literature.

The mapper consumes an already sanitized Zotero snapshot plus the authoritative
source manifest and relative derivative names.  It never opens attachments or
Markdown contents and never auto-binds fuzzy title matches.
"""
from __future__ import annotations
import argparse, csv, hashlib, json, re
from pathlib import Path
from typing import Any

from mining_research_kernel.artifacts import atomic_write_json, ensure_output_directory
from zotero_snapshot import load_snapshot, normalize_doi

ABS_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|/|\\\\|file:)", re.I)
SENSITIVE = re.compile(r"(?:api[_-]?key|token|password|secret|cookie|sqlite|database|annotation.?body)", re.I)

def norm_title(value: str) -> str:
    value = str(value or "").replace("_", " ").replace("—", "-")
    value = re.sub(r"\.[A-Za-z0-9]+$", "", value)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value, flags=re.UNICODE).casefold()

def _maybe_doi(value: Any) -> str | None:
    try:
        return normalize_doi(value)
    except (TypeError, ValueError):
        return None

def safe_relative(value: str) -> str:
    value = str(value or "").replace("\\", "/")
    if ABS_RE.search(value) or any(part == ".." for part in value.split("/")):
        raise ValueError("absolute or traversal path rejected")
    if SENSITIVE.search(value):
        raise ValueError("sensitive field/path rejected")
    return value

def parse_ris(path: str | Path) -> list[dict[str, Any]]:
    records=[]; current={}; authors=[]
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        if not raw.strip(): continue
        match=re.match(r"^([A-Z0-9]{2})  - ?(.*)$",raw)
        if not match: continue
        tag, value = match.group(1), match.group(2).strip()
        if tag == "TY": current={"type": value, "authors": []}; authors=[]
        elif tag == "ER":
            current["authors"]=authors; records.append(current); current={}; authors=[]
        elif tag == "TI" and current: current["title"]=value
        elif tag == "DO" and current: current["doi"]=_maybe_doi(value)
        elif tag == "AU" and current: authors.append(value)
        elif tag == "PY" and current: current["year"]=value
    return records

def _title_candidates(title: str, pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
    key=norm_title(title)
    return [x for x in pool if norm_title(x.get("title")) == key]

def combine_snapshots(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if not snapshots:
        raise ValueError("at least one sanitized snapshot is required")
    instance_ids={snapshot["instance_id"] for snapshot in snapshots}
    if len(instance_ids) != 1:
        raise ValueError("snapshot instance_id mismatch")
    items={}
    for snapshot in snapshots:
        for item in snapshot["items"]:
            previous=items.get(item["item_key"])
            if previous is not None and previous != item:
                raise ValueError(f"conflicting duplicate Zotero item: {item['item_key']}")
            items[item["item_key"]]=item
    return {
        "schema_version":1,
        "snapshot_type":"zotero_filtered_metadata",
        "instance_id":next(iter(instance_ids)),
        "exported_at":max(str(snapshot["exported_at"]) for snapshot in snapshots),
        "library":{"version":str(max(int(snapshot["library"]["version"]) for snapshot in snapshots))},
        "items":sorted(items.values(),key=lambda item:item["item_key"]),
    }

def build_mapping(snapshot: dict[str, Any], manifest_path: str | Path, ris_path: str | Path,
                  markdown_root: str | Path) -> dict[str, Any]:
    items=snapshot["items"]
    by_title={}
    for item in items: by_title.setdefault(norm_title(item["title"]), []).append(item)
    by_doi={}
    for item in items:
        doi=_maybe_doi(item.get("doi"))
        if doi: by_doi.setdefault(doi, []).append(item)
    with Path(manifest_path).open(encoding="utf-8-sig", newline="") as stream:
        rows=list(csv.DictReader(stream))
    ris=parse_ris(ris_path)
    md_names=sorted(p.name for p in Path(markdown_root).glob("*.md"))
    md_by_title={}
    for name in md_names: md_by_title.setdefault(norm_title(Path(name).stem), []).append(name)
    expected_md=[]
    for row in rows:
        if str(row.get("md_exists", "True")).strip().casefold() == "true":
            expected_md.append(Path(safe_relative(row.get("md_relative_path", ""))).name)
    expected_set=set(expected_md); actual_set=set(md_names)
    md_collision=[{"normalized_title":k,"filenames":v} for k,v in sorted(md_by_title.items()) if len(v)>1]
    md_shared=[{"filename":n,"manifest_rows":expected_md.count(n)} for n in sorted(expected_set) if expected_md.count(n)>1]
    md_missing=[n for n in sorted(expected_set) if n not in actual_set]
    md_orphan=[n for n in md_names if n not in expected_set]
    relations=[]; ambiguities=[]; duplicates=[]; orphans=[]; used=set()
    for row in rows:
        title=row.get("title_key", ""); key=norm_title(title)
        attachment_matches=[item for item in by_title.get(key, []) if item["item_type"]=="attachment"]
        manifest_doi=_maybe_doi(row.get("doi"))
        if manifest_doi:
            ris_matches=[record for record in ris if _maybe_doi(record.get("doi"))==manifest_doi]
            manifest_ris_evidence="exact_doi"
        else:
            ris_matches=[record for record in ris if record.get("authors") and norm_title(f"{record.get('title','')}_{record['authors'][0]}")==key]
            manifest_ris_evidence="exact_title_plus_first_author"
        bibliographic_matches=[]
        parent_match_evidence=None
        ris_doi=_maybe_doi(ris_matches[0].get("doi")) if len(ris_matches)==1 else None
        if len(ris_matches)==1:
            if ris_doi:
                bibliographic_matches=[item for item in by_doi.get(ris_doi, []) if item["item_type"] not in {"attachment","note"}]
                if bibliographic_matches: parent_match_evidence="exact_doi"
            if not bibliographic_matches:
                bibliographic_matches=[item for item in by_title.get(norm_title(ris_matches[0].get("title")), []) if item["item_type"] not in {"attachment","note"}]
                if bibliographic_matches: parent_match_evidence="exact_title"
        if len(attachment_matches)>1 or len(ris_matches)>1 or len(bibliographic_matches)>1:
            ambiguities.append({"source_title":title,
                "attachment_item_keys":sorted(x["item_key"] for x in attachment_matches),
                "bibliographic_item_keys":sorted(x["item_key"] for x in bibliographic_matches),
                "ris_match_count":len(ris_matches)})
        zotero_parent_doi=_maybe_doi(bibliographic_matches[0].get("doi")) if len(bibliographic_matches)==1 else None
        doi_compared=bool(ris_doi and zotero_parent_doi)
        doi_match=(ris_doi==zotero_parent_doi) if doi_compared else None
        complete=len(attachment_matches)==len(ris_matches)==len(bibliographic_matches)==1 and doi_match is not False
        partial=not complete and any((attachment_matches,ris_matches,bibliographic_matches))
        status="exact_complete" if complete else ("partial" if partial else "missing_from_zotero")
        if len(attachment_matches)==1: used.add(attachment_matches[0]["item_key"])
        if len(bibliographic_matches)==1: used.add(bibliographic_matches[0]["item_key"])
        md_expected=Path(safe_relative(row.get("md_relative_path", ""))).name if str(row.get("md_exists", "True")).strip().casefold()=="true" else None
        md_candidates=md_by_title.get(key, [])
        md_status=("missing" if md_expected and md_expected not in actual_set else
                   "collision" if len(md_candidates)>1 else
                   "matched" if md_expected and md_expected in actual_set else "not_expected")
        rel={"source_relative_path":safe_relative(row.get("source_relative_path","")),"title_key":title,
             "source_sha256":row.get("source_sha256",""),"markdown_relative_path":safe_relative(row.get("md_relative_path","")),
             "markdown_filename":md_expected if md_status=="matched" else None,"markdown_candidates":md_candidates,
             "markdown_status":md_status,
             "zotero_bibliographic_item_key":bibliographic_matches[0]["item_key"] if len(bibliographic_matches)==1 else None,
             "zotero_attachment_item_key":attachment_matches[0]["item_key"] if len(attachment_matches)==1 else None,
             "ris_doi":ris_doi,"zotero_bibliographic_doi":zotero_parent_doi,
             "match_status":status,
             "match_evidence":{"manifest_to_ris":manifest_ris_evidence if len(ris_matches)==1 else None,
                               "ris_to_zotero_parent":parent_match_evidence if len(bibliographic_matches)==1 else None,
                               "manifest_to_zotero_attachment":"exact_normalized_title" if len(attachment_matches)==1 else None,
                               "doi_compared":doi_compared,"doi_match":doi_match},
             "ris_records":ris_matches}
        relations.append(rel)
    title_counts={norm_title(r.get("title_key")):0 for r in rows}
    for r in rows: title_counts[norm_title(r.get("title_key"))]+=1
    duplicates=[]
    for k,v in sorted(title_counts.items()):
        group=[r for r in rows if norm_title(r.get("title_key"))==k]
        if v>1:
            hashes={r.get("source_sha256","") for r in group}; targets={safe_relative(r.get("md_relative_path","")) for r in group}
            kind="same_hash_shared_target" if len(hashes)==1 and len(targets)==1 else "conflicting_duplicate"
            duplicates.append({"title_key":k,"manifest_rows":v,"kind":kind,"source_sha256_values":sorted(hashes),"markdown_targets":sorted(targets)})
    for item in items:
        if item["item_key"] not in used: orphans.append({"zotero_item_key":item["item_key"],"title":item["title"]})
    exact=sum(r["match_status"]=="exact_complete" for r in relations)
    missing_titles=sorted({r["title_key"] for r in relations if r["match_status"]=="missing_from_zotero"})
    return {"schema_version":1,"type":"relation_map","matching_policy":"If a manifest DOI exists it exactly selects the RIS record; otherwise manifest title plus first RIS author selects RIS. A RIS DOI exactly selects the Zotero bibliographic parent when available, with exact RIS title as the conservative fallback. Exact normalized manifest title links the standalone attachment. DOI conflicts prevent an exact-complete match; fuzzy candidates never bind.",
            "relations":sorted(relations,key=lambda x:x["source_relative_path"]),
            "summary":{"manifest_rows":len(rows),"unique_title_keys":len(title_counts),"markdown_files":len(md_names),"ris_records":len(ris),"zotero_items":len(items),"exact_complete_matches":exact,"missing_from_zotero_unique_titles":len(missing_titles)},
            "ambiguities":ambiguities,"duplicates":duplicates,"orphans":orphans,"missing_from_zotero":missing_titles,
            "markdown_reconciliation":{"expected_count":len(expected_md),"missing":md_missing,"shared":md_shared,"orphan":md_orphan,"collision":md_collision}}

def write_artifacts(result: dict[str, Any], output: str | Path) -> None:
    out=ensure_output_directory(output)
    payloads={"relation_map.json":result,"ambiguities.json":{"schema_version":1,"ambiguities":result["ambiguities"]},
      "duplicates.json":{"schema_version":1,"duplicates":result["duplicates"]},"orphans.json":{"schema_version":1,"orphans":result["orphans"]},
      "coverage_report.json":{"schema_version":1,"summary":result["summary"],"missing_from_zotero":result["missing_from_zotero"],"markdown_reconciliation":result["markdown_reconciliation"],"reconciliation":"Counts and missing titles are deterministically source-derived."},
      "rebuild_report.json":{"schema_version":1,"rebuildable":True,"inputs":["sanitized Zotero snapshot","source_manifest.csv","RIS","relative Markdown filenames"]}}
    for name,obj in payloads.items(): atomic_write_json(out / name, obj)

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--snapshot",required=True,action="append"); p.add_argument("--manifest",required=True); p.add_argument("--ris",required=True); p.add_argument("--markdown-root",required=True); p.add_argument("--output",required=True); a=p.parse_args(argv)
    result=build_mapping(combine_snapshots([load_snapshot(path) for path in a.snapshot]),a.manifest,a.ris,a.markdown_root); write_artifacts(result,a.output); print(json.dumps(result["summary"],ensure_ascii=False,sort_keys=True))
if __name__=="__main__": main()
