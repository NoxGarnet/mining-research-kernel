"""E-side read-only Zotero Local API exporter."""
from __future__ import annotations
import argparse, hashlib, json, re, socket
from datetime import datetime, timezone
from urllib.parse import quote, urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler
from zotero_snapshot import normalize_doi, validate_snapshot

DEFAULT_BASE="http://127.0.0.1:23119/api"; LOOPBACK={"127.0.0.1","::1","localhost"}; KEY_RE=re.compile(r"^[A-Za-z0-9]+$"); MAX_PAGES=1000; MAX_ITEMS=100000
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): raise ValueError("redirects are forbidden for Zotero export")
def ensure_loopback(base_url):
    p=urlparse(base_url)
    if p.scheme!="http" or p.username is not None or p.password is not None or p.query or p.fragment or p.port != 23119: raise ValueError("base URL must be http loopback port 23119 without userinfo/query/fragment")
    if p.path.rstrip("/")!="/api": raise ValueError("base URL path must be /api")
    host=p.hostname
    if host not in LOOPBACK: raise ValueError("base URL host must be loopback")
    if host=="localhost":
        addresses={x[4][0] for x in socket.getaddrinfo(host,23119,type=socket.SOCK_STREAM)}
        if not addresses or any(not (a in LOOPBACK or a.startswith("127.")) for a in addresses): raise ValueError("localhost does not resolve exclusively to loopback")
    return "http://[::1]:23119/api" if host=="::1" else f"http://{host}:23119/api"
def validate_collection_key(key):
    key=(key or "").strip()
    if not key or not KEY_RE.fullmatch(key): raise ValueError("collection_key must be a non-empty Zotero key using letters/digits only")
    return key
def get_json(base_url,path):
    url=ensure_loopback(base_url)+"/"+path.lstrip("/")
    req=Request(url,method="GET",headers={"Accept":"application/json"})
    with build_opener(NoRedirect()).open(req,timeout=10) as response:
        return json.loads(response.read().decode("utf-8")), dict(response.headers.items())
def export_snapshot(base_url=DEFAULT_BASE,collection_key=None,all_library=False,instance_seed=None):
    if bool(collection_key) == bool(all_library): raise ValueError("collection_key and all_library are strict XOR")
    if instance_seed is None or not str(instance_seed).strip(): raise ValueError("stable instance_seed is required")
    base=ensure_loopback(base_url); key=validate_collection_key(collection_key) if collection_key else None
    prefix=f"users/0/collections/{quote(key,safe='')}/items" if key else "users/0/items"; start=0; limit=100; raw=[]
    fingerprints=set(); page_count=0; expected_total=None; library_version=None
    while True:
        page_count+=1
        if page_count>MAX_PAGES: raise ValueError("Zotero pagination exceeded MAX_PAGES")
        page,headers=get_json(base,f"{prefix}?format=json&limit={limit}&start={start}")
        if not isinstance(page,list): raise ValueError("Zotero items response must be an array")
        page_version=headers.get("Last-Modified-Version")
        if page_version is None: raise ValueError("Zotero response missing Last-Modified-Version")
        if library_version is None: library_version=page_version
        elif page_version != library_version: raise ValueError("Zotero library changed during export")
        total_header=headers.get("Total-Results")
        if total_header is not None:
            try: total=int(total_header)
            except (TypeError,ValueError): raise ValueError("invalid Zotero Total-Results header")
            if total < 0: raise ValueError("invalid Zotero Total-Results header")
            if expected_total is None: expected_total=total
            elif total != expected_total: raise ValueError("Zotero Total-Results changed during export")
        fingerprint=hashlib.sha256(json.dumps(page,sort_keys=True,separators=(",",":")).encode()).hexdigest()
        if fingerprint in fingerprints: raise ValueError("Zotero pagination repeated a page")
        fingerprints.add(fingerprint)
        keys=[(x.get("key") or x.get("data",{}).get("key")) for x in page]
        if len(keys)!=len(set(keys)): raise ValueError("Zotero page contains duplicate item keys")
        if any(k in {(x.get("key") or x.get("data",{}).get("key")) for x in raw} for k in keys): raise ValueError("Zotero pagination made no key progress")
        raw.extend(page)
        if len(raw)>MAX_ITEMS: raise ValueError("Zotero pagination exceeded MAX_ITEMS")
        if expected_total is not None:
            if len(raw)>expected_total: raise ValueError("Zotero returned more items than Total-Results")
            if len(raw)==expected_total: break
            if not page: raise ValueError("Zotero pagination ended before Total-Results")
        elif len(page)<limit: break
        start+=len(page)
    items={}; attachments=[]
    for obj in raw:
        data=obj.get("data",obj); item_key=obj.get("key",data.get("key")); version=obj.get("version",data.get("version",0)); typ=data.get("itemType","unknown")
        if typ=="attachment" and data.get("parentItem"):
            attachments.append((data["parentItem"],{"filename":data.get("filename", ""),"content_type":data.get("contentType", ""),"item_key":item_key,"version":version})); continue
        title=str(data.get("title","")).strip() or f"[untitled {typ}]"
        item={"item_key":item_key,"version":version,"item_type":typ,"title":title,"collections":sorted(data.get("collections",[])),"tags":sorted(t.get("tag","") if isinstance(t,dict) else str(t) for t in data.get("tags",[])),"attachments":[]}
        doi=normalize_doi(data.get("DOI") or data.get("doi"))
        if doi is not None: item["doi"]=doi
        items[item_key]=item
    orphans=[(attachment.get("item_key") or "") for parent,attachment in attachments if parent not in items]
    if orphans: raise ValueError(f"orphan attachment parent keys: {sorted(orphans)}")
    for parent,attachment in attachments: items[parent]["attachments"].append(attachment)
    instance_id=hashlib.sha256(str(instance_seed).strip().encode()).hexdigest()
    snapshot={"schema_version":1,"snapshot_type":"zotero_filtered_metadata","instance_id":instance_id,"exported_at":datetime.now(timezone.utc).isoformat(),"library":{"version":str(library_version),**({"collection_key":key} if key else {})},"items":list(items.values())}
    return validate_snapshot(snapshot)
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--base-url",default=DEFAULT_BASE); p.add_argument("--collection-key"); p.add_argument("--all-library",action="store_true"); p.add_argument("--instance-seed",required=True); p.add_argument("--output",required=True); a=p.parse_args(argv)
    snapshot=export_snapshot(a.base_url,a.collection_key,a.all_library,a.instance_seed)
    with open(a.output,"w",encoding="utf-8",newline="\n") as f: json.dump(snapshot,f,ensure_ascii=False,indent=2); f.write("\n")
if __name__=="__main__": main()
