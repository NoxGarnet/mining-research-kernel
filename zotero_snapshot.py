"""Strict offline validation and deterministic consumption of Zotero snapshots."""
from __future__ import annotations
import json, re
from pathlib import Path

class SnapshotError(ValueError): pass
ROOT_KEYS={"schema_version","snapshot_type","instance_id","exported_at","library","items"}
LIBRARY_KEYS={"version","collection_key"}; ITEM_KEYS={"item_key","version","item_type","title","doi","collections","tags","attachments"}; ATTACHMENT_KEYS={"filename","content_type","item_key","version"}
FORBIDDEN={"clientsecret","accesstoken","apikey","token","password","credential","database","sqlite","localpath","absolutepath","filepath","dbpath"}
FILE_URI=re.compile(r"^file:",re.I); DRIVE_ABS=re.compile(r"^[A-Za-z]:[\\/]"); DRIVE_PATH=re.compile(r"^[A-Za-z]:(?=\S)(?=.*[\\/])")
DOI_RE=re.compile(r"^10\.\d{4,9}/\S+$",re.I)
def _norm(name): return re.sub(r"[^a-z0-9]","",str(name).lower())
def normalize_doi(value):
    if value is None: return None
    if not isinstance(value,str): raise ValueError("doi must be a string")
    text=value.strip()
    if not text: return None
    text=re.sub(r"^(?:https?://)?(?:dx\.)?doi\.org/", "", text, flags=re.I)
    text=re.sub(r"^doi:\s*", "", text, flags=re.I).strip().lower()
    if not DOI_RE.fullmatch(text): raise ValueError("doi must use a DOI form like 10.1234/example")
    return text
def _safe_string(value,where):
    if not isinstance(value,str): raise SnapshotError(f"{where} must be a string")
    text=value.strip()
    if FILE_URI.match(text) or text.startswith(("/","\\")) or DRIVE_ABS.match(text) or DRIVE_PATH.match(text): raise SnapshotError(f"absolute/local path forbidden at {where}")
def _required_string(value,where):
    _safe_string(value,where)
    if not value.strip(): raise SnapshotError(f"{where} must be non-empty")
def _collection_key(value,where):
    _required_string(value,where)
    if not re.fullmatch(r"[A-Za-z0-9]+",value.strip()): raise SnapshotError(f"{where} must use letters/digits only")
def _keys(obj,allowed,where):
    extra=set(obj)-allowed
    if extra: raise SnapshotError(f"unknown fields at {where}: {sorted(extra)}")
    for key in obj:
        if _norm(key) in FORBIDDEN: raise SnapshotError(f"forbidden field at {where}.{key}")
def _string_array(value,where):
    if not isinstance(value,list) or any(not isinstance(x,str) for x in value): raise SnapshotError(f"{where} must be a string array")
    for i,x in enumerate(value): _required_string(x,f"{where}[{i}]")
def validate_snapshot(snapshot):
    if not isinstance(snapshot,dict): raise SnapshotError("snapshot must be an object")
    _keys(snapshot,ROOT_KEYS,"root")
    if snapshot.get("schema_version")!=1: raise SnapshotError(f"unsupported schema_version: {snapshot.get('schema_version')!r}")
    if snapshot.get("snapshot_type")!="zotero_filtered_metadata": raise SnapshotError("unsupported snapshot_type")
    for key in ("instance_id","exported_at"): _required_string(snapshot.get(key),f"root.{key}")
    if not re.fullmatch(r"[a-f0-9]{16,64}",snapshot["instance_id"]): raise SnapshotError("instance_id must be lowercase hex")
    lib=snapshot.get("library")
    if not isinstance(lib,dict): raise SnapshotError("library must be an object")
    _keys(lib,LIBRARY_KEYS,"library")
    if "version" not in lib or not isinstance(lib["version"],(str,int)) or isinstance(lib["version"],bool): raise SnapshotError("library.version must be string or integer")
    if isinstance(lib["version"],str): _required_string(lib["version"],"library.version")
    if "collection_key" in lib: _collection_key(lib["collection_key"],"library.collection_key")
    items=snapshot.get("items")
    if not isinstance(items,list): raise SnapshotError("items must be an array")
    seen=set()
    for i,item in enumerate(items):
        where=f"items[{i}]"
        if not isinstance(item,dict): raise SnapshotError(f"{where} must be an object")
        _keys(item,ITEM_KEYS,where)
        for key in ("item_key","item_type","title"):
            if key not in item: raise SnapshotError(f"{where} missing {key}")
            _required_string(item[key],f"{where}.{key}")
        if not item["item_key"].strip(): raise SnapshotError(f"{where}.item_key must be non-empty")
        if not isinstance(item.get("version"),int) or isinstance(item["version"],bool): raise SnapshotError(f"{where}.version must be integer")
        if "doi" in item:
            try: normalize_doi(item["doi"])
            except ValueError as exc: raise SnapshotError(f"{where}.doi: {exc}")
        normalized_item_key=item["item_key"].strip()
        if normalized_item_key in seen: raise SnapshotError(f"duplicate item key: {item['item_key']}")
        seen.add(normalized_item_key); _string_array(item.get("collections"),f"{where}.collections"); _string_array(item.get("tags"),f"{where}.tags")
        attachments=item.get("attachments")
        if not isinstance(attachments,list): raise SnapshotError(f"{where}.attachments must be an array")
        for j,a in enumerate(attachments):
            aw=f"{where}.attachments[{j}]"
            if not isinstance(a,dict): raise SnapshotError(f"{aw} must be an object")
            _keys(a,ATTACHMENT_KEYS,aw)
            for key in ("filename","content_type","item_key"):
                if key not in a: raise SnapshotError(f"{aw} missing {key}")
                _required_string(a[key],f"{aw}.{key}")
            if not a["item_key"].strip() or not a["filename"].strip(): raise SnapshotError(f"{aw} key and filename must be non-empty")
            if a["filename"] in {".",".."} or "/" in a["filename"] or "\\" in a["filename"]: raise SnapshotError(f"attachment filename must be basename at {aw}")
            if not isinstance(a.get("version"),int) or isinstance(a["version"],bool): raise SnapshotError(f"{aw}.version must be integer")
        keys=[a["item_key"].strip() for a in attachments]
        if len(keys)!=len(set(keys)): raise SnapshotError(f"duplicate attachment key under {item['item_key']}")
    return snapshot
def load_snapshot(path): return validate_snapshot(json.loads(Path(path).read_text(encoding="utf-8")))
def snapshot_to_assets(snapshot,project_id="zotero_snapshot"):
    validate_snapshot(snapshot); result=[]
    for item in sorted(snapshot["items"],key=lambda x:x["item_key"]):
        result.append({"schema_version":1,"type":"Asset","asset_id":f"zotero:{snapshot['instance_id']}:{item['item_key']}","project_id":project_id,"path":f"zotero:item:{item['item_key']}","asset_type":"source","authority":"derived","verification_status":"CANNOT_VERIFY","source":"filtered Zotero metadata snapshot","object_version":item["version"],"title":item["title"],"doi":normalize_doi(item.get("doi")),"item_type":item["item_type"],"collections":sorted(item["collections"]),"tags":sorted(item["tags"]),"attachments":sorted(item["attachments"],key=lambda x:(x["filename"],x["item_key"])),"known_limits":["metadata snapshot; full text and experimental validation not implied"]})
    return result
