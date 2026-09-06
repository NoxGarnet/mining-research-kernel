from pathlib import Path
import json
from mining_research_kernel import asset, safe_path, sha256
from flac3d_project import load_config


def _configured_discover(workspace: Path):
    config = load_config(workspace)
    project_id = config["project_id"]
    path_fields = [("entry", "entry", "authoritative"), ("baseline", "baseline", "authoritative"),
                   ("errors", "error", "authoritative"), ("decisions", "decision", "authoritative"),
                   ("research_map", "research_map", "derived")]
    assets = []; diagnostics = []
    for field, typ, authority in path_fields:
        relative = config.get(field)
        if relative is None: continue
        p = safe_path(workspace, relative)
        row = asset(project_id, f"{project_id}:{field}", relative, typ, authority, "CANNOT_VERIFY")
        row["sha256"] = sha256(p)
        if not p.exists(): diagnostics.append(f"missing: {field}: {relative}")
        assets.append(row)
    checks = config["verification"]["project_checks"]
    check_results = [{"check": check, "status": "CANNOT_VERIFY", "scope": "declared check; not executed"} for check in checks]
    return {"schema_version": 1, "type": "Project", "project_id": project_id,
            "domain": config["domain"], "project_type": "computation",
            "authority_root": ".", "entry": config["entry"], "status": "source_presence_only",
            "status_scope": "portable contract and file presence only; no provider execution or verification",
            "known_limits": ["execution provider is not run by Phase 1", "documentation provider is not run by Phase 1"],
            "verification_gates": [{"schema_version": 1, "type": "Verification", "gate_id": "project_checks",
                                    "status": "CANNOT_VERIFY", "scope": "declared checks; not executed", "checks": check_results}],
            "objectives": [f"discover portable {config['product']} project {project_id}"],
            "constraints": [f"execution provider: {config['execution']['provider']}",
                            f"documentation provider: {config['documentation']['provider']}"],
            "current_baseline": config["baseline"], "assets": assets, "tools": [],
            "last_verified": None, "diagnostics": diagnostics,
            "product": config["product"], "product_version": config["product_version"],
            "providers": {"documentation": config["documentation"], "execution": config["execution"]}}

def discover(workspace: Path):
    if (workspace / "flac3d_project.yaml").is_file():
        return _configured_discover(workspace)
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
