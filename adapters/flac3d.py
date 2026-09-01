from pathlib import Path
import json
from mining_kernel import safe_path, sha256, asset

def discover(workspace: Path):
    root = "projects/flac3D"
    ae = "projects/acoustic_emission"
    files = [
        ("projects/flac3D/START.md", "entry", "authoritative"),
        ("projects/flac3D/studies/coal_roadway/cases/liner_v16/main.dat", "model", "authoritative"),
        ("projects/flac3D/scripts/check.ps1", "script", "authoritative"),
        ("projects/flac3D/docs/error-journal.md", "error", "authoritative"),
        ("projects/flac3D/docs/decisions.md", "decision", "authoritative"),
        ("projects/acoustic_emission/results/flac3d_proxy/liner_v16_scan_interval_test20_v1/manifest.json", "result", "authoritative"),
    ]
    assets=[]; diagnostics=[]
    for path, typ, auth in files:
        try: p=safe_path(workspace,path)
        except ValueError as e: diagnostics.append(str(e)); continue
        a=asset("flac3d_coal_roadway", path.replace("/", "_"), path, typ, auth, "CANNOT_VERIFY")
        a["sha256"] = sha256(p)
        if not p.exists(): diagnostics.append(f"missing: {path}")
        assets.append(a)
    return {"schema_version":1,"type":"Project","project_id":"flac3d_coal_roadway","domain":"mining geomechanics and AE proxy","project_type":"computation","authority_root":root,"entry":"projects/flac3D/START.md","status":"source_presence_only","status_scope":"declared baseline and file presence only; no FLAC3D execution or AE validation","objectives":["discover roadway baseline and associated AE proxy evidence"],"constraints":["read-only; do not run FLAC3D"],"known_limits":["FLAC3D plasticity indicators are not measured AE waveforms or physical AE energy","verification is limited to source declarations and file presence"],"current_baseline":"projects/flac3D/studies/coal_roadway/cases/liner_v16/main.dat","assets":assets,"tools":[{"schema_version":1,"type":"Tool","tool_id":"flac3d_check","name":"projects/flac3D/scripts/check.ps1","read_only":True}],"verification_gates":[{"schema_version":1,"type":"Verification","gate_id":"source_presence","status":"PASS_WITH_NOTES" if not diagnostics else "CANNOT_VERIFY","scope":"required entry, baseline, check script, manifest presence"},{"schema_version":1,"type":"Verification","gate_id":"physical_ae_validation","status":"CANNOT_VERIFY","scope":"experimental or field AE comparison"}],"last_verified":None,"diagnostics":diagnostics}
