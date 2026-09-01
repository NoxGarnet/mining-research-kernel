"""Read-only mining research kernel CLI (standard library only)."""
from __future__ import annotations
import argparse, csv, hashlib, json, re, sys
from pathlib import Path
from extension_registry import DEFAULT_REGISTRY, ExtensionRegistry

SCHEMA_VERSION = 1
ALLOWED_TYPES = {"Project", "Asset", "Tool", "Run", "Verification"}

def safe_path(workspace: Path, relative: str) -> Path:
    p = Path(relative.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"unsafe workspace-relative path: {relative}")
    resolved = (workspace / p).resolve()
    if resolved != workspace.resolve() and workspace.resolve() not in resolved.parents:
        raise ValueError(f"path escapes workspace: {relative}")
    return resolved

def sha256(path: Path) -> str | None:
    if not path.is_file(): return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()

def validate_record(record: dict, kind: str | None = None, workspace: Path | None = None) -> list[str]:
    errors = []
    if not isinstance(record, dict): return ["record must be an object"]
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {record.get('schema_version')!r}")
    if kind and record.get("type") not in (None, kind): errors.append(f"expected type {kind}")
    required = {
        "Project": ("project_id", "domain", "project_type", "authority_root", "entry", "status", "status_scope", "known_limits", "verification_gates"),
        "Asset": ("asset_id", "project_id", "path", "asset_type", "authority", "verification_status"),
        "Tool": ("tool_id", "name", "read_only"),
        "Run": ("run_id", "status", "current_stage", "stages", "history"),
        "Verification": ("gate_id", "status", "scope"),
    }
    target = kind or record.get("type")
    if target in required:
        for key in required[target]:
            if key not in record: errors.append(f"missing {key}")
    if target == "Project":
        for key in ("assets", "tools", "verification_gates"):
            if key in record and not isinstance(record[key], list): errors.append(f"{key} must be a list")
        if "source_paths" in record:
            if not isinstance(record["source_paths"], list): errors.append("source_paths must be a list")
            elif workspace is not None:
                for rel in record["source_paths"]:
                    if not isinstance(rel, str): errors.append("source_paths entries must be strings"); continue
                    try:
                        if not safe_path(workspace, rel).exists(): errors.append(f"missing source_path: {rel}")
                    except ValueError as e: errors.append(str(e))
        if isinstance(record.get("verification_gates"), list):
            for i, gate in enumerate(record["verification_gates"]):
                if not isinstance(gate, dict): errors.append(f"verification_gates[{i}] must be an object"); continue
                for key in ("gate_id", "status"):
                    if key not in gate: errors.append(f"verification_gates[{i}] missing {key}")
    return errors

def asset(project_id, asset_id, path, asset_type, authority="authoritative", verification_status="CANNOT_VERIFY", source=None):
    return {"schema_version": 1, "type": "Asset", "asset_id": asset_id, "project_id": project_id,
            "path": path, "asset_type": asset_type, "authority": authority,
            "verification_status": verification_status, "source": source or "read-only discovery",
            "sha256": None, "known_limits": []}

def flac3d(workspace: Path):
    from adapters.flac3d import discover
    return discover(workspace)

def ceramsite(workspace: Path):
    from adapters.ceramsite import discover
    return discover(workspace)

def project_index_diagnostics(workspace: Path):
    index = workspace / "Workspace_Index" / "project_index.yaml"
    if not index.is_file(): return ["missing project index: Workspace_Index/project_index.yaml"]
    text = index.read_text(encoding="utf-8")
    diagnostics = []
    entries = re.findall(r"(?m)^\s*- project:\s*([^\s#]+)\s*\n\s*(?:module:\s*[^\n]+\n\s*)?path:\s*([^\s#]+)\s*\n\s*entry:\s*([^\s#]+)", text)
    if not entries: diagnostics.append("project index has no parseable project_entries")
    for required_path in ("projects/flac3D/", "projects/acoustic_emission/", "projects/master_thesis_ceramsite_concrete/"):
        if required_path not in text.replace("\\", "/"):
            diagnostics.append(f"project index does not register supported path: {required_path}")
    for project, path, entry in entries:
        for label, rel in (("path", path), ("entry", entry)):
            try:
                if not safe_path(workspace, rel).exists(): diagnostics.append(f"index {project} {label} missing: {rel}")
            except ValueError as e: diagnostics.append(f"index {project} {label}: {e}")
    return diagnostics

def discover_all(workspace, registry: ExtensionRegistry | None = None):
    index_diags = project_index_diagnostics(workspace)
    active_registry = registry or DEFAULT_REGISTRY
    projects = []
    for extension in active_registry.by_kind("project"):
        try:
            projects.append(active_registry.resolve(extension)(workspace))
        except Exception as exc:
            projects.append({"extension_id": extension.extension_id, "kind": extension.kind,
                             "diagnostics": [f"extension {extension.extension_id} failed: {type(exc).__name__}: {exc}"]})
    for project in projects:
        project["diagnostics"] = index_diags + project.get("diagnostics", [])
    return projects

def discover_sources(workspace, registry: ExtensionRegistry | None = None):
    active_registry = registry or DEFAULT_REGISTRY
    sources = []
    for extension in active_registry.by_kind("source"):
        try:
            sources.append(active_registry.resolve(extension)(workspace, action="discover"))
        except Exception as exc:
            sources.append({"extension_id": extension.extension_id, "kind": extension.kind,
                            "status": "CANNOT_VERIFY",
                            "diagnostics": [{"code": "source_discovery_failed",
                                             "message": f"{type(exc).__name__}: {exc}"}]})
    return sources

def inspect_source(workspace, source_id, *, registry: ExtensionRegistry | None = None,
                   reader=None, operation=None, params=None):
    active_registry = registry or DEFAULT_REGISTRY
    extension = next((row for row in active_registry.by_kind("source")
                      if row.extension_id == source_id), None)
    if extension is None:
        return {"extension_id": source_id, "kind": "source", "status": "CANNOT_VERIFY",
                "diagnostics": [{"code": "unknown_source", "message": f"unknown source: {source_id}"}]}
    try:
        return active_registry.resolve(extension)(workspace, action="inspect", reader=reader,
                                                  operation=operation, params=params)
    except Exception as exc:
        return {"extension_id": source_id, "kind": "source", "status": "CANNOT_VERIFY",
                "diagnostics": [{"code": "source_inspection_failed",
                                 "message": f"{type(exc).__name__}: {exc}"}]}

def main(argv=None):
    ap = argparse.ArgumentParser(description="Read-only mining research kernel")
    ap.add_argument("--workspace", default=".")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    i = sub.add_parser("inspect"); i.add_argument("project_id")
    sub.add_parser("discover-sources")
    s = sub.add_parser("inspect-source"); s.add_argument("source_id"); s.add_argument("--operation"); s.add_argument("--params-json", default="{}")
    sub.add_parser("validate")
    z = sub.add_parser("validate-zotero-snapshot"); z.add_argument("path")
    z = sub.add_parser("inspect-zotero-snapshot"); z.add_argument("path"); z.add_argument("--project-id", default="zotero_snapshot")
    rc = sub.add_parser("run-create"); rc.add_argument("--runs-root", required=True); rc.add_argument("run_id"); rc.add_argument("--request-json", default="null"); rc.add_argument("--inputs-json", default='{"input_hashes":[]}')
    rr = sub.add_parser("run-record"); rr.add_argument("--runs-root", required=True); rr.add_argument("run_id"); rr.add_argument("stage"); rr.add_argument("--role", required=True); rr.add_argument("--model", required=True); rr.add_argument("--status", required=True); rr.add_argument("--inputs-json", default="null"); rr.add_argument("--outputs-json", default="null"); rr.add_argument("--data-json", default="{}")
    ri = sub.add_parser("run-inspect"); ri.add_argument("--runs-root", required=True); ri.add_argument("run_id")
    rv = sub.add_parser("run-validate"); rv.add_argument("--runs-root", required=True); rv.add_argument("run_id")
    args = ap.parse_args(argv); workspace = Path(args.workspace).resolve()
    if args.command == "discover": out = discover_all(workspace)
    elif args.command == "inspect":
        out = next((x for x in discover_all(workspace) if x["project_id"] == args.project_id), {"diagnostics": ["unknown project_id"]})
    elif args.command == "discover-sources": out = discover_sources(workspace)
    elif args.command == "inspect-source":
        out = inspect_source(workspace, args.source_id, operation=args.operation,
                             params=json.loads(args.params_json))
    elif args.command == "validate-zotero-snapshot":
        from zotero_snapshot import load_snapshot
        data=load_snapshot(args.path); out={"valid":True,"instance_id":data["instance_id"],"item_count":len(data["items"])}
    elif args.command == "inspect-zotero-snapshot":
        from zotero_snapshot import load_snapshot, snapshot_to_assets
        data=load_snapshot(args.path); out={"valid":True,"instance_id":data["instance_id"],"item_count":len(data["items"]),"assets":snapshot_to_assets(data,args.project_id)}
    elif args.command == "run-create":
        from run_ledger import create_run
        out=create_run(args.runs_root,args.run_id,json.loads(args.request_json),json.loads(args.inputs_json))
    elif args.command == "run-record":
        from run_ledger import record_stage
        out=record_stage(args.runs_root,args.run_id,args.stage,args.role,args.status,json.loads(args.data_json),model=args.model,inputs=json.loads(args.inputs_json),outputs=json.loads(args.outputs_json))
    elif args.command == "run-inspect":
        from run_ledger import inspect_run
        out=inspect_run(args.runs_root,args.run_id)
    elif args.command == "run-validate":
        from run_ledger import validate_bundle
        errors=validate_bundle(args.runs_root,args.run_id); out={"valid":not errors,"errors":errors}
        if errors:
            print(json.dumps(out,ensure_ascii=False,indent=2))
            return 2
    else:
        out = []
        for p in Path(__file__).parent.joinpath("fixtures").glob("*.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("snapshot_type") == "zotero_filtered_metadata":
                from zotero_snapshot import validate_snapshot
                try: validate_snapshot(data); errors=[]
                except Exception as exc: errors=[str(exc)]
            else: errors=validate_record(data, "Project", workspace)
            out.append({"file": str(p), "errors": errors})
        if any(row["errors"] for row in out):
            print(json.dumps(out,ensure_ascii=False,indent=2))
            return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0

def cli(argv=None):
    try:
        return main(argv)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 2

if __name__ == "__main__": sys.exit(cli())
