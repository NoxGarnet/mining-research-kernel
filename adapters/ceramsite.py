from pathlib import Path
import csv
from mining_research_kernel import asset, safe_path, sha256

def discover(workspace: Path):
    files=[("projects/master_thesis_ceramsite_concrete/START.md","entry"),("projects/master_thesis_ceramsite_concrete/Tracks/research_track.yaml","track"),("projects/master_thesis_ceramsite_concrete/wenxian/source_manifest.csv","source"),("projects/master_thesis_ceramsite_concrete/wenxian/zotero_import/metadata.ris","source"),("projects/master_thesis_ceramsite_concrete/wenxian/md/references/","note")]
    assets=[]; diagnostics=[]
    for path,typ in files:
        try:p=safe_path(workspace,path)
        except ValueError as e: diagnostics.append(str(e)); continue
        a=asset("ceramsite_research",path.replace("/","_"),path,typ,"authoritative" if typ in {"entry","track","source"} else "derived","CANNOT_VERIFY")
        if p.is_file(): a["sha256"]=sha256(p)
        elif p.is_dir(): a["item_count"]=sum(1 for x in p.iterdir() if x.is_file())
        else: diagnostics.append(f"missing: {path}")
        assets.append(a)
    return {"schema_version":1,"type":"Project","project_id":"ceramsite_research","domain":"ceramsite porous cementitious materials","project_type":"literature_experiment","authority_root":"projects/master_thesis_ceramsite_concrete","entry":"projects/master_thesis_ceramsite_concrete/Tracks/research_track.yaml","status":"direction_scoping_unvalidated","status_scope":"research direction and literature metadata only; no external peer review, advisor confirmation, or experiment validation","objectives":["discover research track and source mappings"],"constraints":["read-only; do not access Zotero or infer validated material conclusions"],"known_limits":["metadata pending verification","historical Accepted/Ultimate filenames do not mean approval","candidate directions require advisor and experimental validation"],"current_baseline":None,"assets":assets,"tools":[],"verification_gates":[{"schema_version":1,"type":"Verification","gate_id":"source_mapping","status":"PASS_WITH_NOTES" if not diagnostics else "CANNOT_VERIFY","scope":"research track, source manifest, RIS and markdown references presence"},{"schema_version":1,"type":"Verification","gate_id":"experimental_validation","status":"CANNOT_VERIFY","scope":"material performance and thesis direction"}],"last_verified":None,"diagnostics":diagnostics}
