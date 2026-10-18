"""Durable, bounded review of selected FLAC3D script lines."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import _id, task_record_evidence_review, task_start
from mining_research_kernel.on_demand import _decision_bound_to_task_state
from mining_research_kernel.source_review import _evidence_for_asset, _payload_record

_MAX_FILE = 2 * 1024 * 1024
_MAX_LINES = 200
_MAX_CHARS = 32000
_MAX_FINDINGS = 100
_MAX_REVIEW_TEXT = 4000
_MAX_REVIEW_GAPS = 100
_MAX_GAP_TEXT = 1000
_MAX_EVIDENCE_REFS = 100
_MAX_DOCS = 20
_FAMILY = "literal_single_line_zone_cmodel_assign"
_ASSIGN = re.compile(r"^\s*zone\s+cmodel\s+assign\s+[A-Za-z][\w.-]*(?:\s+range\s+.+)?\s*$", re.I)
_CANDIDATE = re.compile(r"\bzone\s+cmodel\s+assign\b", re.I)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _safe_source_path(root: Path, script: str) -> tuple[Path, str]:
    p = Path(script).expanduser()
    explicit = p.is_absolute()
    if not explicit and (".." in p.parts or str(p).startswith(("/", "\\"))):
        raise ValueError("relative script path escapes project root")
    resolved = p.resolve() if explicit else (root / p).resolve()
    if not explicit:
        try: label = resolved.relative_to(root).as_posix()
        except ValueError as exc: raise ValueError("relative script path resolves outside project root") from exc
    else:
        try: label = resolved.relative_to(root).as_posix()
        except ValueError: label = f"caller:{resolved.name}"
    return resolved, label


def _read_script(path: Path, encoding: str) -> tuple[bytes, str]:
    try:
        if not path.is_file(): raise ValueError("script path must be an existing file")
        with path.open("rb") as stream:
            raw = stream.read(_MAX_FILE + 1)
    except (OSError, IsADirectoryError) as exc:
        raise ValueError("script path cannot be read as a regular file") from exc
    if len(raw) > _MAX_FILE: raise ValueError("script exceeds 2 MiB")
    try: text = raw.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError, TypeError) as exc: raise ValueError("script cannot be decoded with the requested encoding") from exc
    return raw, text


def _classify_script(text: str, start_line: int, end_line: int) -> list[str]:
    """Classify all lines so selected slices inherit block/continuation context."""
    classes: list[str] = []
    block: str | None = None
    continued = False
    for line_number,line in enumerate(io.StringIO(text),1):
        line=line.rstrip("\r\n")
        stripped = line.strip()
        comment_only = not stripped or stripped.startswith((";", "#"))
        if block:
            if start_line<=line_number<=end_line: classes.append("uncertain" if stripped else "none")
            if (block == "fish" and re.fullmatch(r"end", stripped, re.I)) or (
                    block == "python" and re.fullmatch(r"end_python", stripped, re.I)):
                block = None
            if line_number>=end_line: break
            continue
        if comment_only:
            if start_line<=line_number<=end_line: classes.append("none")
            continued = False
            if line_number>=end_line: break
            continue
        starts_block = bool(re.match(r"\s*fish\s+define\b", line, re.I))
        starts_python = bool(re.match(r"\s*python(?:\s|$)", line, re.I))
        if starts_block or starts_python:
            if start_line<=line_number<=end_line: classes.append("uncertain")
            block = "fish" if starts_block else "python"
            continued = False
            if line_number>=end_line: break
            continue
        if continued:
            classification="uncertain"
        elif _CANDIDATE.search(line):
            if any(token in line for token in ('"', "'", ";", "#")) or not _ASSIGN.fullmatch(line):
                classification="uncertain"
            else:
                classification="candidate"
        else:
            classification="uncertain" if stripped.endswith("...") else "none"
        # FLAC3D continuation is indicated by trailing ellipsis. A prior
        # candidate ending in it is uncertain, and subsequent command-like
        # lines remain uncertain until a noncontinued line ends the chain.
        this_continues = _has_trailing_continuation(line)
        if this_continues and classification == "candidate": classification="uncertain"
        continued = this_continues or (continued and this_continues)
        if start_line<=line_number<=end_line: classes.append(classification)
        if line_number>=end_line: break
    return classes


def _has_trailing_continuation(line: str) -> bool:
    """Recognize trailing ... outside simple quoted strings and comments."""
    quote: str | None = None
    escaped = False
    for index, char in enumerate(line):
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif quote and char == quote:
            quote = None
        elif not quote and char in ("'", '"'):
            quote = char
        elif not quote and char in (";", "#"):
            line = line[:index]
            break
    return line.rstrip().endswith("...")


def _documentation_binding(store: ResearchStore, task_context: str, version: str, refs: list[str]) -> list[dict[str, Any]]:
    if (not isinstance(refs, list) or not refs or len(refs) > _MAX_DOCS
            or not all(isinstance(x, str) and x.strip() and len(x) <= 200 for x in refs)
            or len(set(refs)) != len(refs)):
        raise ValueError(f"documentation_asset_refs must be a non-empty unique list of at most {_MAX_DOCS} IDs")
    bindings = []
    for aid in refs:
        asset, evidence, payload = _payload_record(store, _id(aid, "documentation_asset_ref"),
                                                   _evidence_for_asset(store, aid, "documentation_query_observation"))
        result = payload["documentation_result"]
        citation = result.get("citation", {})
        request = payload.get("request", {})
        if (request.get("operation") == "command-name-only" or result.get("coverage_scope") in {"command_name_only","discovery_only"}
                or result.get("status") == "DISCOVERY_ONLY"):
            raise ValueError("discovery and command-name-only observations are not actual passage readings")
        if not result.get("passages"):
            raise ValueError("script review requires an actual documentation passage reading")
        cited_product=citation.get("product"); requested_product=request.get("product")
        if (not isinstance(cited_product,str) or not isinstance(requested_product,str)
                or cited_product.casefold() != "flac3d" or requested_product.casefold() != "flac3d"):
            raise ValueError("documentation product must be FLAC3D")
        if request.get("product_version") != version:
            raise ValueError("documentation product version does not match script review")
        trust = citation.get("trust_class")
        if trust == "synthetic":
            if task_context != "synthetic": raise ValueError("synthetic documentation requires synthetic task_context")
            if result.get("status") not in {"SYNTHETIC_VERIFIED", "READ_WITH_LIMITS"}: raise ValueError("synthetic source must contain an actual synthetic passage reading")
        elif trust != "official_local":
            raise ValueError("script review requires official_local documentation")
        elif result.get("status") != "READ_WITH_LIMITS":
            raise ValueError("official source must contain an actual READ_WITH_LIMITS passage reading")
        bindings.append({"asset_ref": asset["id"], "asset_revision": asset["revision"], "asset_sha256": asset["content_sha256"],
                         "evidence": [{"id": e["id"], "revision": e["revision"], "asset_ref": e["asset_ref"]} for e in evidence],
                         "citation": {k: copy.deepcopy(citation.get(k)) for k in ("source_id", "product", "document_family", "document_build", "page", "anchor", "trust_class", "sha256_body")},
                         "status": result.get("status"), "coverage_scope": result.get("coverage_scope"),
                         "uncovered": copy.deepcopy(result.get("uncovered", [])),
                         "passages": copy.deepcopy(result["passages"])})
    return bindings


def start_script_review(project_root, *, task_id: str, question: str, script: str, start_line: int, end_line: int,
                        product_version: str, documentation_asset_refs: list[str], encoding: str = "utf-8-sig",
                        task_context: str = "production") -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    task_id = _id(task_id, "task_id")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000: raise ValueError("question must be non-empty and bounded")
    if not isinstance(script, str) or not script.strip() or len(script) > 4096: raise ValueError("script path must be non-empty and bounded")
    if any(isinstance(n, bool) or not isinstance(n, int) for n in (start_line, end_line)) or start_line < 1 or end_line < start_line or end_line-start_line+1 > _MAX_LINES:
        raise ValueError("line range must be positive, ordered, and at most 200 lines")
    if not isinstance(product_version, str) or not product_version.strip() or len(product_version) > 100: raise ValueError("product_version must be non-empty and bounded")
    if not isinstance(encoding, str) or not encoding.strip() or len(encoding) > 100: raise ValueError("encoding must be a non-empty encoding name")
    if task_context not in {"production", "synthetic"}: raise ValueError("task_context must be production or synthetic")
    path, label = _safe_source_path(root, script)
    store = ResearchStore(root)
    # Relative material identities move with the project. Only external caller
    # labels need a host-path digest to distinguish different same-name files.
    source_identity = str(path) if label.startswith("caller:") else label
    spec={"question":question.strip(),"script":label,
          "script_identity_sha256":hashlib.sha256(source_identity.encode("utf-8")).hexdigest(),
          "start_line":start_line,"end_line":end_line,
          "product_version":product_version.strip(),"documentation_asset_refs":list(documentation_asset_refs) if isinstance(documentation_asset_refs,list) else documentation_asset_refs,
          "encoding":encoding,"task_context":task_context}
    prior=store.latest_record(task_id,"TaskState")
    if prior:
        saved=prior.get("packet",{}).get("input",{}).get("script_review",{})
        if saved.get("request_spec") != spec: raise ValueError(f"task_id already records a different script review: {task_id}")
        return {"task_packet":prior["packet"],"script_snapshot":copy.deepcopy(saved["script_snapshot"]),"documentation_sources":copy.deepcopy(saved["documentation_sources"]),"review_template":saved["review_template"],"replayed":True}
    doc_bindings = _documentation_binding(store, task_context, product_version.strip(), documentation_asset_refs)
    raw, text = _read_script(path, encoding)
    lines = text.splitlines()
    if end_line > len(lines): raise ValueError("selected line range exceeds script length")
    selected = lines[start_line-1:end_line]
    if sum(len(x) for x in selected) > _MAX_CHARS: raise ValueError("selected script text exceeds 32000 characters")
    classifications = _classify_script(text,start_line,end_line)
    snap = {"source": label, "start_line": start_line, "end_line": end_line,
            "lines": [{"line": start_line+i, "text": line, "classification": classifications[i]} for i,line in enumerate(selected)],
            "script_sha256": hashlib.sha256(raw).hexdigest(), "encoding": encoding}
    request_hash = hashlib.sha256(_canonical({"question":question.strip(),"script":label,"start_line":start_line,"end_line":end_line,
                                              "product_version":product_version.strip(),"docs":doc_bindings,"snapshot":snap,"task_context":task_context})).hexdigest()
    material = store.register_local_material(path, "primary/original", citation_locator={"caller_label":label,"script_sha256":snap["script_sha256"]})
    if material["asset"]["content_sha256"] != snap["script_sha256"]:
        raise ValueError("script changed while the bounded snapshot was being registered; start a new task")
    doc_assets = [binding["asset_ref"] for binding in doc_bindings]
    doc_evidence = [e for binding in doc_bindings for e in binding["evidence"]]
    asset_refs = [material["asset"]["id"], *doc_assets]
    evidence_refs = [material["evidence"]["id"], *[e["id"] for e in doc_evidence]]
    revision_pins = {material["asset"]["id"]: material["asset"]["revision"],
                     material["evidence"]["id"]: material["evidence"]["revision"]}
    for binding in doc_bindings:
        revision_pins[binding["asset_ref"]] = binding["asset_revision"]
        revision_pins.update({e["id"]: e["revision"] for e in binding["evidence"]})
    if len(set(asset_refs)) != len(asset_refs) or len(set(evidence_refs)) != len(evidence_refs):
        raise ValueError("script and documentation material references must be unique")
    inp={"review_mode":"flac3d_script_review",
         "script_review":{"request_sha256":request_hash,"request_spec":spec,"script_snapshot":snap,"documentation_sources":doc_bindings,
                           "script_material":{"asset_ref":material["asset"]["id"],"asset_revision":material["asset"]["revision"],
                                              "asset_sha256":material["asset"]["content_sha256"],"evidence_ref":material["evidence"]["id"],
                                              "evidence_revision":material["evidence"]["revision"]},
                           "product_version":product_version.strip(),"command_family":_FAMILY,
                           "review_template":{"summary":"","findings":[],"gaps":["Manual authored review with bounded source citation; semantic correctness is not proven."],"next_action":""}}}
    packet=task_start(root,{"task_id":task_id,"workflow_id":"research","task_type":"mining_research_kernel.task.evidence_review",
        "question_statement":question.strip(),"claim_statement":f"Manual bounded review of FLAC3D script lines {start_line}-{end_line} for {product_version.strip()}.",
        "maturity":"known_workflow","max_runs":1,"task_context":task_context,"verification_gates":[],
        "asset_refs":asset_refs,"evidence_refs":evidence_refs,"input":inp,
        },_expected_material_revisions=revision_pins)
    return {"task_packet":packet,"script_snapshot":snap,"documentation_sources":doc_bindings,"review_template":inp["script_review"]["review_template"],"replayed":False}


def _task(store: ResearchStore, task_id: str):
    state=store.latest_record(_id(task_id,"task_id"),"TaskState")
    if not state: raise ValueError(f"unknown task: {task_id}")
    data=state.get("packet",{}).get("input",{}).get("script_review")
    if not isinstance(data,Mapping): raise ValueError("task is not a script review")
    return state,data


def record_script_review(project_root, *, task_id: str, operation_id: str, review: dict) -> dict[str, Any]:
    store=ResearchStore(Path(project_root).expanduser().resolve()); state,saved=_task(store,task_id)
    operation_id=_id(operation_id,"operation_id")
    prior_op=state.get("operation_results",{}).get(operation_id)
    if isinstance(prior_op,Mapping) and prior_op.get("status")=="recorded":
        prior_decision=_decision_bound_to_task_state(store,state)
        prior_review=(prior_decision or {}).get("assessment",{}).get("manual_authored_review",{}).get("review")
        if prior_review != review: raise ValueError("operation_id was already used with a different review")
        return {"task_packet":state["packet"],"operation_id":operation_id,"review_record_ref":prior_op.get("decision_id"),"requires_user_choice":True}
    if not isinstance(review,dict):
        raise ValueError("review requires summary, findings, non-empty gaps, and next_action")
    try: _canonical(review)
    except (TypeError,ValueError) as exc: raise ValueError("review must contain JSON-compatible values") from exc
    review_summary=review.get("summary"); findings=review.get("findings"); gaps=review.get("gaps"); next_action=review.get("next_action")
    if not isinstance(review_summary,str) or not review_summary.strip() or len(review_summary)>_MAX_REVIEW_TEXT:
        raise ValueError("review.summary must be non-empty and bounded")
    if not isinstance(findings,list) or len(findings)>_MAX_FINDINGS:
        raise ValueError(f"review.findings must be a list of at most {_MAX_FINDINGS} entries")
    if (not isinstance(gaps,list) or not gaps or len(gaps)>_MAX_REVIEW_GAPS
            or not all(isinstance(x,str) and x.strip() and len(x)<=_MAX_GAP_TEXT for x in gaps)):
        raise ValueError("review.gaps must contain bounded non-empty strings")
    if not isinstance(next_action,str) or not next_action.strip() or len(next_action)>2000:
        raise ValueError("review.next_action must be non-empty and bounded")
    snap=saved["script_snapshot"]; low,high=snap["start_line"],snap["end_line"]
    docs={e["id"]:(d,e) for d in saved["documentation_sources"] for e in d["evidence"]}
    evidence=set(docs)
    for finding in review["findings"]:
        if not isinstance(finding,Mapping): raise ValueError("each finding must be an object")
        if (any(isinstance(finding.get(k),bool) or not isinstance(finding.get(k),int) for k in ("start_line","end_line"))
                or not low<=finding["start_line"]<=finding["end_line"]<=high):
            raise ValueError("finding line range must be within captured lines")
        statement=finding.get("statement")
        if not isinstance(statement,str) or not statement.strip() or len(statement)>_MAX_REVIEW_TEXT:
            raise ValueError("finding.statement must be non-empty and bounded")
        refs=finding.get("documentation_evidence_refs")
        if (not isinstance(refs,list) or not refs or len(refs)>_MAX_EVIDENCE_REFS
                or not all(isinstance(ref,str) and ref.strip() and len(ref)<=200 for ref in refs)
                or len(set(refs))!=len(refs) or not set(refs).issubset(evidence)):
            raise ValueError("finding documentation_evidence_refs must be bounded selected Evidence IDs")
        rows=[r for r in snap["lines"] if finding["start_line"]<=r["line"]<=finding["end_line"]]
        if not any(r["classification"]=="candidate" for r in rows): raise ValueError("finding range must include a complete literal candidate command")
    revision_pins=_validate_bound_materials(store,state,saved)
    packet=state["packet"]
    packet_materials={item["asset_id"]:item for item in packet.get("material_reads",[]) if isinstance(item,Mapping)}
    script_material=saved["script_material"]
    assessment_reads=[]; material_gaps=[]; mandatory_gaps=[]
    for asset_id in packet.get("asset_refs",[]):
        material=packet_materials.get(asset_id)
        asset=store.latest_record(asset_id,"Asset")
        if material is None or asset is None: raise ValueError(f"task material binding is missing: {asset_id}")
        evrefs=list(material.get("evidence_refs",[]))
        if asset_id==script_material["asset_ref"]:
            if asset["content_sha256"]!=snap["script_sha256"]: raise ValueError("script Asset hash no longer matches the captured original")
            locator={"script_snapshot_sha256":snap["script_sha256"],"line_start":low,"line_end":high}
            reading_gaps=["selected lines are a historical snapshot; original source was not reread during review"]
            summary="Reviewed persisted selected-line snapshot only."
        else:
            doc=next(d for d in saved["documentation_sources"] if d["asset_ref"]==asset_id)
            citation=doc["citation"]
            locator={"asset_revision":doc["asset_revision"],"page":citation.get("page"),"anchor":citation.get("anchor"),
                     "document_build":citation.get("document_build"),"trust_class":citation.get("trust_class"),
                     "coverage_scope":doc["coverage_scope"]}
            reading_gaps=list(doc["uncovered"])
            reading_gaps.append("bounded saved passage citation; semantic correctness and engineering applicability are not established")
            mandatory_gaps.extend(doc["uncovered"])
            summary=f"Used saved passage from {citation.get('source_id')} page {citation.get('page')} anchor {citation.get('anchor')} (build {citation.get('document_build')})."
            material_gaps.append({"asset_id":asset_id,"reason":"; ".join(reading_gaps[:10]),"next_action":"preserve source coverage limits; user selects any further validation"})
        assessment_reads.append({"asset_id":asset_id,"evidence_refs":evrefs,"observed_sha256":asset["content_sha256"],
          "reading_status":"READ_WITH_LIMITS","verification_status":"NOT_VERIFIED","locator":locator,"summary":summary,
          "numeric_check_status":"NOT_APPLICABLE","scientific_validation_status":"NOT_VERIFIED","gaps":reading_gaps})
    mandatory_gaps.extend(["manual authored review with bounded citations does not prove command semantics",
                           "no FLAC3D solver or model execution was performed"])
    judgment_gaps=list(dict.fromkeys([*gaps,*mandatory_gaps]))
    if not material_gaps:
        material_gaps=[{"asset_id":script_material["asset_ref"],"reason":"bounded script snapshot review","next_action":"user chooses whether to inspect another range or validate independently"}]
    assessment={"scope":"material_reading_and_evidence_synthesis_only",
      "judgment":{"status":"PROVISIONAL_WITH_GAPS" if findings else "INSUFFICIENT","summary":review_summary,
                  "gaps":judgment_gaps,"next_action":{"action":next_action,"executable":False,"requires_user_choice":True}},
      "manual_authored_review":{"review":copy.deepcopy(review),"basis":"manual authored review with bounded source citation",
        "semantic_correctness":"NOT_PROVEN","bound_script_sha256":snap["script_sha256"],
        "source_freshness":"historical captured snapshot; no fresh source read during recording",
        "documentation_bindings":copy.deepcopy(saved["documentation_sources"])},
      "material_reads":assessment_reads,"material_gaps":material_gaps}
    result=task_record_evidence_review(project_root,task_id,operation_id,assessment,
                                       _expected_material_revisions=revision_pins)
    return {"task_packet":result,"operation_id":operation_id,"review_record_ref":result.get("review_record_ref"),"requires_user_choice":True}


def _validate_bound_materials(store: ResearchStore,state: Mapping[str,Any],saved: Mapping[str,Any]) -> dict[str,int]:
    script=saved["script_material"]
    pins={script["asset_ref"]:script["asset_revision"],script["evidence_ref"]:script["evidence_revision"]}
    asset=store.latest_record(script["asset_ref"],"Asset")
    evidence=store.latest_record(script["evidence_ref"],"Evidence")
    if (asset is None or asset.get("revision")!=script["asset_revision"] or asset.get("content_sha256")!=script["asset_sha256"]
            or script["asset_sha256"]!=saved["script_snapshot"]["script_sha256"]):
        raise ValueError("registered script Asset changed since review start")
    if evidence is None or evidence.get("revision")!=script["evidence_revision"] or evidence.get("asset_ref")!=script["asset_ref"]:
        raise ValueError("registered script Evidence changed since review start")
    refs=saved["request_spec"]["documentation_asset_refs"]
    current=_documentation_binding(store,state["packet"].get("task_context","production"),saved["product_version"],refs)
    if current!=saved["documentation_sources"]:
        raise ValueError("documentation Asset/Evidence revision, hash, or saved passage changed since review start")
    for doc in saved["documentation_sources"]:
        pins[doc["asset_ref"]]=doc["asset_revision"]
        current_asset=store.latest_record(doc["asset_ref"],"Asset")
        if current_asset is None or current_asset.get("revision")!=doc["asset_revision"] or current_asset.get("content_sha256")!=doc["asset_sha256"]:
            raise ValueError("documentation Asset changed since review start")
        for item in doc["evidence"]:
            current_ev=store.latest_record(item["id"],"Evidence")
            if current_ev is None or current_ev.get("revision")!=item["revision"] or current_ev.get("asset_ref")!=doc["asset_ref"]:
                raise ValueError("documentation Evidence changed since review start")
            pins[item["id"]]=item["revision"]
    return pins


def script_review_progress(project_root, *, task_id: str, script: str | None = None) -> dict[str, Any]:
    root=Path(project_root).expanduser().resolve(); store=ResearchStore(root); state,data=_task(store,task_id); snap=copy.deepcopy(data["script_snapshot"])
    decision=_decision_bound_to_task_state(store,state)
    review=copy.deepcopy((decision or {}).get("assessment",{}).get("manual_authored_review",{}).get("review"))
    drift="not_checked"
    if script is not None:
        path,_=_safe_source_path(root,script)
        if not path.is_file(): drift="missing"
        else:
            try: raw,_=_read_script(path,snap["encoding"]); drift="unchanged" if hashlib.sha256(raw).hexdigest()==snap["script_sha256"] else "changed"
            except (OSError,ValueError): drift="changed"
    return {"task_packet":copy.deepcopy(state["packet"]),"script_snapshot":snap,
            "documentation_sources":copy.deepcopy(data["documentation_sources"]),"review":review,
            "decision":copy.deepcopy(decision),"source_status":drift,"replayed_from_persisted_snapshot":True}


def render_script_review_report(project_root, *, task_id: str) -> str:
    store=ResearchStore(Path(project_root).expanduser().resolve()); state,data=_task(store,task_id); snap=data["script_snapshot"]
    decision=_decision_bound_to_task_state(store,state)
    review=(decision or {}).get("assessment",{}).get("manual_authored_review",{}).get("review",{})
    lines=["# FLAC3D script review", "",f"Task: `{task_id}`",f"Version: `{data['product_version']}`",f"Source label: `{snap['source']}` (SHA-256 `{snap['script_sha256']}`)",f"Selected lines: {snap['start_line']}-{snap['end_line']}","",
      "This is a manual authored review with bounded source citations. Citations do not prove semantic correctness. No fresh source query, original-script reread, solver check, or model execution is represented. The user retains the next-step choice.","",
      "## Captured script lines",""]
    longest=max((len(run) for row in snap["lines"] for run in re.findall(r"`+",row["text"])),default=2)
    fence="`"*max(3,longest+1)
    lines.extend([fence+"text",*[f"{row['line']:>5}: {row['text']}  [{row['classification']}]" for row in snap["lines"]],fence,""])
    lines.extend(["## Documentation sources","","Only the saved passage snapshots below were used; these entries are not fresh queries.",""])
    for index,doc in enumerate(data["documentation_sources"],1):
        citation=doc["citation"]
        evrefs=", ".join(f"{item['id']}@r{item['revision']}" for item in doc["evidence"])
        lines.extend([f"### Source {index}: {citation.get('source_id')}",
          f"- Asset: `{doc['asset_ref']}` r{doc['asset_revision']}, SHA-256 `{doc['asset_sha256']}`",
          f"- Product/build: {citation.get('product')} / {citation.get('document_build')} (family {citation.get('document_family')})",
          f"- Trust: {citation.get('trust_class')}; page: {citation.get('page')}; anchor: {citation.get('anchor')}",
          f"- Evidence: {evrefs}",f"- Reading status/scope: {doc['status']} / {doc['coverage_scope']}"])
        if doc["uncovered"]: lines.extend(["- Uncovered scope:",*[f"  - {item}" for item in doc["uncovered"]]])
        for passage in doc["passages"]:
            lines.extend([f"- Saved passage locator: {passage.get('locator')}","",passage.get("text", ""),""])
    if decision:
        lines.extend([f"## Recorded review (Decision `{decision['id']}` revision {decision['revision']})", "",
                      "### Summary",review.get("summary", ""),"","### Findings"])
        for f in review.get("findings",[]): lines.append(f"- Lines {f['start_line']}-{f['end_line']}: {f['statement']} (Evidence: {', '.join(f['documentation_evidence_refs'])})")
        judgment_gaps=decision.get("judgment",{}).get("gaps",review.get("gaps",[]))
        lines.extend(["","### Gaps",*[f"- {g}" for g in judgment_gaps],"","### Next action",review.get("next_action", ""),""])
        judgment=decision.get("judgment",{})
        lines.extend([f"Judgment status: {judgment.get('status', 'UNKNOWN')}.",""])
    else: lines.extend(["## Status","No review has been recorded.",""])
    lines.extend(["## Limits","- Manual authored review with bounded source citation; semantics and engineering applicability remain unverified.",
                  "- The source passages and selected script lines are persisted historical snapshots; this report performed no fresh reads.",
                  "- No FLAC3D solver check, Run, or Verification was created.","- The user chooses whether to inspect more lines or pursue independent validation.",""])
    return "\n".join(lines)


__all__=["start_script_review","record_script_review","script_review_progress","render_script_review_report"]
