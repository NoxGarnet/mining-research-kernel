"""Read-only mining research kernel CLI (standard library only).

This module is a compatibility CLI shim.  Generic services are implemented in
``mining_research_kernel``; concrete adapter choice is made by the composition
root.
"""
from __future__ import annotations
import argparse, json, re, sys
from pathlib import Path

from default_extensions import registry_for_workspace
from mining_research_kernel.core import (
    asset, discover_all as _discover_all, discover_sources as _discover_sources,
    inspect_source as _inspect_source, safe_path, sha256, validate_record,
)
from mining_research_kernel.registry import ExtensionRegistry

SCHEMA_VERSION = 1
ALLOWED_TYPES = {"Project", "Asset", "Tool", "Run", "Verification"}

def flac3d(workspace: Path):
    from adapters.flac3d import discover
    return discover(workspace)

def ceramsite(workspace: Path):
    from adapters.ceramsite import discover
    return discover(workspace)

def project_index_diagnostics(workspace: Path):
    # A portable FLAC3D project is self-describing and does not need the
    # private-workspace navigation index used by the legacy fixtures.
    if (workspace / "flac3d_project.yaml").is_file():
        return []
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
    active_registry = registry or registry_for_workspace(workspace)
    projects = _discover_all(workspace, active_registry)
    for project in projects:
        project["diagnostics"] = index_diags + project.get("diagnostics", [])
    return projects

def discover_sources(workspace, registry: ExtensionRegistry | None = None):
    return _discover_sources(workspace, registry or registry_for_workspace(workspace))

def inspect_source(workspace, source_id, *, registry: ExtensionRegistry | None = None,
                   reader=None, operation=None, params=None):
    return _inspect_source(workspace, source_id, registry or registry_for_workspace(workspace),
                           reader=reader, operation=operation, params=params)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Filesystem-native mining research kernel")
    ap.add_argument("--workspace", default=".")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    i = sub.add_parser("inspect"); i.add_argument("project_id")
    sub.add_parser("discover-sources")
    s = sub.add_parser("inspect-source"); s.add_argument("source_id"); s.add_argument("--operation"); s.add_argument("--params-json", default="{}")
    sub.add_parser("validate")
    dc = sub.add_parser("documentation-check")
    dc.add_argument("--registration", required=True)
    dc.add_argument("--page", required=True)
    dc.add_argument("--command", dest="syntax_command")
    dc.add_argument("--product", required=True)
    dc.add_argument("--product-version", required=True)
    dc.add_argument("--anchor")
    dc.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    init = sub.add_parser("init-flac3d-project")
    init.add_argument("path")
    init.add_argument("--project-id", required=True)
    init.add_argument("--template", choices=("blank", "synthetic"), default="blank")
    si = sub.add_parser("init-synthetic-project")
    si.add_argument("path")
    si.add_argument("--project-id", required=True)
    z = sub.add_parser("validate-zotero-snapshot"); z.add_argument("path")
    z = sub.add_parser("inspect-zotero-snapshot"); z.add_argument("path"); z.add_argument("--project-id", default="zotero_snapshot")
    rc = sub.add_parser("run-create"); rc.add_argument("--runs-root", required=True); rc.add_argument("run_id"); rc.add_argument("--request-json", default="null"); rc.add_argument("--inputs-json", default='{"input_hashes":[]}')
    rr = sub.add_parser("run-record"); rr.add_argument("--runs-root", required=True); rr.add_argument("run_id"); rr.add_argument("stage"); rr.add_argument("--role", required=True); rr.add_argument("--model", required=True); rr.add_argument("--status", required=True); rr.add_argument("--inputs-json", default="null"); rr.add_argument("--outputs-json", default="null"); rr.add_argument("--data-json", default="{}")
    ri = sub.add_parser("run-inspect"); ri.add_argument("--runs-root", required=True); ri.add_argument("run_id")
    rv = sub.add_parser("run-validate"); rv.add_argument("--runs-root", required=True); rv.add_argument("run_id")
    ts = sub.add_parser("task-start"); ts.add_argument("--project-root", required=True); ts.add_argument("--request-json", required=True); ts.add_argument("--documentation-result")
    ti = sub.add_parser("task-inspect"); ti.add_argument("--project-root", required=True); ti.add_argument("task_id")
    tc = sub.add_parser("task-complete"); tc.add_argument("--project-root", required=True); tc.add_argument("task_id"); tc.add_argument("--operation-id", required=True); tc.add_argument("--completion-json", required=True)
    tf = sub.add_parser("task-run-fake"); tf.add_argument("--project-root", required=True); tf.add_argument("task_id"); tf.add_argument("--operation-id", required=True); tf.add_argument("--fixture-id", required=True)
    rm = sub.add_parser("research-map-rebuild"); rm.add_argument("--project-root", required=True); rm.add_argument("--output")
    am = sub.add_parser("register-local-material"); am.add_argument("--project-root", required=True); am.add_argument("path"); am.add_argument("--material-kind", required=True, choices=("primary/original", "project_record", "derived_reading_note")); am.add_argument("--citation-locator"); am.add_argument("--source-ref", action="append", default=[]); am.add_argument("--source-documents-claim")
    rp = sub.add_parser("route-propose"); rp.add_argument("--project-root", required=True); rp.add_argument("--route-json", required=True); rp.add_argument("--operation-id", required=True)
    ri3 = sub.add_parser("route-inspect"); ri3.add_argument("--project-root", required=True); ri3.add_argument("route_id")
    rr3 = sub.add_parser("route-reserve"); rr3.add_argument("--project-root", required=True); rr3.add_argument("route_id"); rr3.add_argument("--operation-id", required=True)
    rf3 = sub.add_parser("route-finish"); rf3.add_argument("--project-root", required=True); rf3.add_argument("route_id"); rf3.add_argument("--reservation-id", required=True); rf3.add_argument("--outcome", required=True, choices=("completed", "failed", "cannot_verify")); rf3.add_argument("--operation-id", required=True); rf3.add_argument("--outputs-json", default="[]"); rf3.add_argument("--stop-reason")
    ro3 = sub.add_parser("route-reopen"); ro3.add_argument("--project-root", required=True); ro3.add_argument("route_id"); ro3.add_argument("--operation-id", required=True)
    rj3 = sub.add_parser("route-reject"); rj3.add_argument("--project-root", required=True); rj3.add_argument("route_id"); rj3.add_argument("--operation-id", required=True); rj3.add_argument("--reason", required=True)
    rs3 = sub.add_parser("route-supersede"); rs3.add_argument("--project-root", required=True); rs3.add_argument("route_id"); rs3.add_argument("--superseded-route-id", required=True); rs3.add_argument("--operation-id", required=True)
    rc3 = sub.add_parser("route-compare"); rc3.add_argument("--project-root", required=True); rc3.add_argument("--question-id", required=True); rc3.add_argument("--comparison-id", required=True); rc3.add_argument("--operation-id", required=True); rc3.add_argument("--route-ids-json", default="[]"); rc3.add_argument("--stop-reason")
    co4 = sub.add_parser("cognition-observe"); co4.add_argument("--project-root", required=True); co4.add_argument("--operation-id", required=True); co4.add_argument("--observation-kind", required=True); co4.add_argument("--observation-json", required=True); co4.add_argument("--locator-json", default="null"); co4.add_argument("--scope-json", default="null"); co4.add_argument("--task-id"); co4.add_argument("--route-id"); co4.add_argument("--run-id"); co4.add_argument("--content-sha256")
    cp4 = sub.add_parser("cognition-propose"); cp4.add_argument("--project-root", required=True); cp4.add_argument("--proposal-json", required=True); cp4.add_argument("--operation-id", required=True)
    cb4 = sub.add_parser("cognition-rebuild"); cb4.add_argument("--project-root", required=True); cb4.add_argument("--output", default="research/core_cognition.json"); cb4.add_argument("--object-ref"); cb4.add_argument("--task-id"); cb4.add_argument("--route-id"); cb4.add_argument("--version")
    cf4 = sub.add_parser("failure-record"); cf4.add_argument("--project-root", required=True); cf4.add_argument("--failure-json", required=True); cf4.add_argument("--operation-id", required=True)
    cg4 = sub.add_parser("cognition-failure-gate"); cg4.add_argument("--project-root", required=True); cg4.add_argument("--object-ref"); cg4.add_argument("--task-id"); cg4.add_argument("--route-id"); cg4.add_argument("--version")
    cr4 = sub.add_parser("cognition-review"); cr4.add_argument("--project-root", required=True); cr4.add_argument("proposal_id"); cr4.add_argument("--operation-id", required=True); cr4.add_argument("--review-ref", required=True); cr4.add_argument("--evidence-json", default="null"); cr4.add_argument("--scope-json", default="null"); cr4.add_argument("--impact"); cr4.add_argument("--decision", choices=("accept", "reject", "contested"), default="accept")
    args = ap.parse_args(argv); workspace = Path(args.workspace).resolve()
    if args.command == "task-start":
        from mining_research_kernel.r2_workflow import task_start
        out = task_start(args.project_root, args.request_json, args.documentation_result)
    elif args.command == "task-inspect":
        from mining_research_kernel.r2_workflow import task_inspect
        out = task_inspect(args.project_root, args.task_id)
    elif args.command == "task-complete":
        from mining_research_kernel.r2_workflow import load_json_value, task_complete
        out = task_complete(args.project_root, args.task_id, args.operation_id,
                            load_json_value(args.completion_json, "completion-json"))
    elif args.command == "task-run-fake":
        from mining_research_kernel.r2_workflow import task_run_fake
        out = task_run_fake(args.project_root, args.task_id, args.operation_id, args.fixture_id)
    elif args.command == "research-map-rebuild":
        from mining_research_kernel.r2_workflow import research_map_rebuild
        out = research_map_rebuild(args.project_root, args.output)
    elif args.command == "register-local-material":
        from mining_research_kernel.r2_workflow import load_json_value
        from mining_research_kernel.records import ResearchStore
        locator = None if args.citation_locator is None else load_json_value(args.citation_locator, "citation-locator")
        out = ResearchStore(args.project_root).register_local_material(
            args.path, args.material_kind, citation_locator=locator,
            source_refs=args.source_ref, source_documents_claim=args.source_documents_claim)
    elif args.command in {"route-propose", "route-inspect", "route-reserve", "route-finish", "route-reopen", "route-reject", "route-supersede", "route-compare"}:
        from mining_research_kernel.routes import RouteLifecycle
        from mining_research_kernel.r2_workflow import load_json_value
        lifecycle = RouteLifecycle(args.project_root)
        if args.command == "route-propose":
            request = load_json_value(args.route_json, "route-json")
            if not isinstance(request, dict):
                raise ValueError("route-json must contain an object")
            out = lifecycle.propose(request, args.operation_id)
        elif args.command == "route-inspect":
            out = lifecycle.inspect(args.route_id)
        elif args.command == "route-reserve":
            out = lifecycle.reserve(args.route_id, args.operation_id)
        elif args.command == "route-finish":
            outputs = load_json_value(args.outputs_json, "outputs-json")
            out = lifecycle.finish(args.route_id, args.reservation_id, args.outcome, args.operation_id,
                                   outputs=outputs, stop_reason=args.stop_reason)
        elif args.command == "route-reopen":
            out = lifecycle.reopen(args.route_id, args.operation_id)
        elif args.command == "route-reject":
            out = lifecycle.reject(args.route_id, args.operation_id, args.reason)
        elif args.command == "route-supersede":
            out = lifecycle.supersede(args.route_id, args.superseded_route_id, args.operation_id)
        else:
            route_ids = load_json_value(args.route_ids_json, "route-ids-json")
            out = lifecycle.compare(args.question_id, args.comparison_id, args.operation_id,
                                    route_ids=route_ids, stop_reason=args.stop_reason)
    elif args.command in {"cognition-observe", "cognition-propose", "cognition-rebuild", "failure-record", "cognition-failure-gate", "cognition-review"}:
        from mining_research_kernel.cognition import CoreCognition
        from mining_research_kernel.r2_workflow import load_json_value
        cognition = CoreCognition(args.project_root)
        if args.command == "cognition-observe":
            out = cognition.record_mechanical_evidence(
                args.observation_kind, load_json_value(args.observation_json, "observation-json"),
                operation_id=args.operation_id, locator=load_json_value(args.locator_json, "locator-json"),
                scope=load_json_value(args.scope_json, "scope-json"), task_id=args.task_id,
                route_id=args.route_id, run_id=args.run_id, content_sha256=args.content_sha256)
        elif args.command == "cognition-propose":
            out = cognition.propose(load_json_value(args.proposal_json, "proposal-json"), args.operation_id)
        elif args.command == "cognition-rebuild":
            out = cognition.rebuild(args.output, object_ref=args.object_ref, task_id=args.task_id, route_id=args.route_id, version=args.version)
        elif args.command == "failure-record":
            out = cognition.record_failure(load_json_value(args.failure_json, "failure-json"), args.operation_id)
        elif args.command == "cognition-failure-gate":
            out = cognition.failure_gate(object_ref=args.object_ref, task_id=args.task_id,
                                         route_id=args.route_id, version=args.version)
        else:
            out = cognition.review(args.proposal_id, args.operation_id, review_ref=args.review_ref,
                                   evidence_refs=load_json_value(args.evidence_json, "evidence-json"),
                                   scope=load_json_value(args.scope_json, "scope-json"), impact=args.impact, decision=args.decision)
    elif args.command == "documentation-check":
        from providers.documentation import load_registration, resolve_documentation
        source = load_registration(args.registration)
        provider = resolve_documentation({"provider": "local"}, registration=source)
        out = provider.verify_syntax(
            args.page,
            args.syntax_command,
            product=args.product,
            product_version=args.product_version,
            anchor=args.anchor,
            task_context=args.task_context,
        )
        if out.get("status") not in {"VERIFIED", "SYNTHETIC_VERIFIED"}:
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    elif args.command == "init-flac3d-project":
        from flac3d_project import init_project
        target = Path(args.path).expanduser()
        out = {"initialized": str(init_project(target, args.project_id, args.template)),
               "project_id": args.project_id, "template": args.template}
    elif args.command == "init-synthetic-project":
        from flac3d_project import init_synthetic_project
        target = Path(args.path).expanduser()
        out = {"initialized": str(init_synthetic_project(target, args.project_id)),
               "project_id": args.project_id, "template": "synthetic", "product": "synthetic"}
    elif args.command == "discover": out = discover_all(workspace)
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
        fixture_root = Path(__file__).resolve().parent.joinpath("fixtures")
        for p in fixture_root.glob("*.json"):
            data = json.loads(p.read_text(encoding="utf-8"))
            if data.get("snapshot_type") == "zotero_filtered_metadata":
                from zotero_snapshot import validate_snapshot
                try: validate_snapshot(data); errors=[]
                except Exception as exc: errors=[str(exc)]
            else: errors=validate_record(data, "Project", workspace)
            out.append({"file": p.relative_to(fixture_root).as_posix(), "errors": errors})
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
