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

def _write_research_report(project_root, task_id, output, markdown):
    """Replace only this task's generated view, preserving project inputs."""
    import hashlib
    import os
    from research_project import load_config
    from mining_research_kernel.artifacts import _absolute_without_follow, _reject_reparse_chain, atomic_write_text
    from mining_research_kernel.records import ID_RE, ResearchStore
    if not isinstance(task_id, str) or not ID_RE.fullmatch(task_id):
        raise ValueError("report task_id must be a valid record ID")
    root = _absolute_without_follow(project_root)
    _reject_reparse_chain(root, "project root")
    selected = Path(output).expanduser()
    target = _absolute_without_follow(selected if selected.is_absolute() else root / selected)
    _reject_reparse_chain(target, "report output")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("report output must stay inside the selected project") from exc
    entry = load_config(root).get("entry", "START.md")
    if (target.suffix.lower() != ".md" or target.name.casefold() in {"start.md", "readme.md", "agents.md", "index.md"}
            or tuple(part.casefold() for part in relative.parts[:2]) == ("research", "records")
            or relative.as_posix().casefold() == str(entry).replace("\\", "/").casefold()
            or any(part.startswith(".") for part in relative.parts)):
        raise ValueError("report output must be a separate Markdown view, outside project entries and records")
    marker = f"<!-- MRK generated research report; task={task_id}; authority=derived -->\n"
    if os.path.lexists(target):
        if not target.is_file() or target.stat().st_nlink > 1:
            raise ValueError("report output must be an ordinary file")
        with target.open("rb") as stream:
            if stream.read(len(marker.encode("utf-8"))) != marker.encode("utf-8"):
                raise ValueError("report output already exists and is not this task's generated report")
    for transaction in ResearchStore(root).list_transactions():
        for record in transaction.get("records", []):
            locator = record.get("locator", {})
            if (record.get("type") == "Asset" and isinstance(locator, dict)
                    and isinstance(locator.get("path"), str)
                    and locator.get("path", "").replace("\\", "/").casefold() == relative.as_posix().casefold()):
                raise ValueError("report output is a registered material; choose a separate derived file")
    text = marker + markdown
    atomic_write_text(target, text)
    return relative.as_posix(), hashlib.sha256(text.encode("utf-8")).hexdigest()


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
    er = sub.add_parser("enable-research", help="opt in an existing project to persistent research records")
    er.add_argument("--project-root", required=True)
    er.add_argument("--project-id", required=True)
    dr = sub.add_parser("documentation-record", help="query registered local documentation and persist its bounded observation")
    dr.add_argument("--project-root", required=True)
    dr.add_argument("--task-id", required=True)
    dr.add_argument("--question", required=True)
    dr.add_argument("--registration", required=True)
    dr.add_argument("--page", required=True)
    dr.add_argument("--command", dest="syntax_command", required=True)
    dr.add_argument("--product", required=True)
    dr.add_argument("--product-version", required=True)
    dr.add_argument("--anchor")
    dr.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    zr = sub.add_parser("zotero-record", help="persist a bounded external Zotero reading capture; does not query Zotero")
    zr.add_argument("--project-root", required=True)
    zr.add_argument("--task-id", required=True)
    zr.add_argument("--question", required=True)
    zr.add_argument("--capture", required=True, help="explicit UTF-8 JSON capture file from the external reader")
    zr.add_argument("--findings-json", default="[]", help="optional interpretations and page citations; JSON or @file")
    zr.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    zc = sub.add_parser("validate-zotero-reading", help="validate one external reading capture without writing records")
    zc.add_argument("capture")
    zs = sub.add_parser("zotero-search", help="search an explicitly configured read-only Zotero connection")
    zs.add_argument("--registration", required=True)
    zs.add_argument("--query", required=True)
    zs.add_argument("--collection-key")
    zs.add_argument("--limit", type=int, default=10)
    zd = sub.add_parser("zotero-read", help="read selected Zotero pages and save their observation without a capture file")
    zd.add_argument("--registration", required=True)
    zd.add_argument("--project-root", required=True)
    zd.add_argument("--task-id", required=True)
    zd.add_argument("--question", required=True)
    zd.add_argument("--item-key", required=True)
    zd.add_argument("--pdf-key", dest="attachment_key")
    zd.add_argument("--pages", help="one-based PDF page indices, e.g. 1,3-4; omit for metadata only")
    zd.add_argument("--collection-key")
    zd.add_argument("--max-reading-chars", type=int, default=12000)
    zd.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    sr = sub.add_parser("research-start", help="combine selected saved literature and documentation observations")
    sr.add_argument("--project-root", required=True)
    sr.add_argument("--task-id", required=True)
    sr.add_argument("--question", required=True)
    sr.add_argument("--asset-ref", action="append", required=True)
    sr.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    rv = sub.add_parser("research-review", help="record a cited Markdown review of selected saved sources")
    rv.add_argument("--project-root", required=True)
    rv.add_argument("--task-id", required=True)
    rv.add_argument("--operation-id", required=True)
    rv.add_argument("--review-file", required=True)
    rv.add_argument("--judgment", choices=("PROVISIONAL_WITH_GAPS", "INSUFFICIENT"), default="PROVISIONAL_WITH_GAPS")
    iq = sub.add_parser("itasca-query", help="query only documentation tools on an explicitly selected Itasca MCP Host")
    iq.add_argument("--registration", required=True)
    iq.add_argument("--operation", required=True, choices=("itasca_query_command", "itasca_browse_commands", "itasca_browse_reference"))
    iq.add_argument("--software", required=True, choices=("flac", "pfc", "3dec", "mpoint", "massflow"))
    iq.add_argument("--version", required=True, choices=("6.0", "7.0", "9.0"))
    iq.add_argument("--query")
    iq.add_argument("--command", dest="itasca_command")
    iq.add_argument("--topic")
    iq.add_argument("--limit", type=int, default=10)
    iq.add_argument("--max-reading-chars", type=int, default=12000)
    rd = sub.add_parser("documentation-read", help="read bounded documentation passages and save source coverage")
    rd.add_argument("--project-root", required=True)
    rd.add_argument("--task-id", required=True)
    rd.add_argument("--question", required=True)
    rd.add_argument("--registration", required=True)
    rd.add_argument("--provider", choices=("local", "itasca"), default="local")
    rd.add_argument("--page")
    rd.add_argument("--product")
    rd.add_argument("--product-version")
    rd.add_argument("--anchor")
    rd.add_argument("--operation", choices=("itasca_query_command", "itasca_browse_commands", "itasca_browse_reference"))
    rd.add_argument("--software", choices=("flac", "pfc", "3dec", "mpoint", "massflow"))
    rd.add_argument("--version", choices=("6.0", "7.0", "9.0"))
    rd.add_argument("--query")
    rd.add_argument("--command", dest="itasca_command")
    rd.add_argument("--topic")
    rd.add_argument("--limit", type=int, default=10)
    rd.add_argument("--max-reading-chars", type=int, default=12000)
    rd.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    lc = sub.add_parser("literature-start", help="prepare a question-oriented comparison of selected distinct papers")
    lc.add_argument("--project-root", required=True)
    lc.add_argument("--task-id", required=True)
    lc.add_argument("--question", required=True)
    lc.add_argument("--asset-ref", action="append", required=True)
    lc.add_argument("--dimension", action="append", help="comparison dimension; repeat to select explicit dimensions")
    lc.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    lr = sub.add_parser("literature-review", help="save a comparison with citations to captured page ranges")
    lr.add_argument("--project-root", required=True)
    lr.add_argument("--task-id", required=True)
    lr.add_argument("--operation-id", required=True)
    lr.add_argument("--comparison-file", required=True)
    lr.add_argument("--judgment", choices=("PROVISIONAL_WITH_GAPS", "INSUFFICIENT"), default="PROVISIONAL_WITH_GAPS")
    rb = sub.add_parser("research-begin", help="begin a source review or comparison under one continuing question")
    rb.add_argument("--project-root", required=True)
    rb.add_argument("--task-id", required=True)
    rb.add_argument("--question", required=True)
    rb.add_argument("--asset-ref", action="append", required=True)
    rb.add_argument("--mode", choices=("literature", "sources"), default="literature")
    rb.add_argument("--dimension", action="append")
    rb.add_argument("--task-context", choices=("production", "synthetic"), default="production")
    rc = sub.add_parser("research-continue", help="continue a recorded judgment with selected existing or newly read sources")
    rc.add_argument("--project-root", required=True)
    rc.add_argument("--task-id", required=True)
    rc.add_argument("--from-task", dest="from_task_id", required=True)
    rc.add_argument("--asset-ref", action="append")
    rc.add_argument("--reason")
    rp = sub.add_parser("research-progress", help="recover the question, judgments and source changes along a named task lineage")
    rp.add_argument("--project-root", required=True)
    rp.add_argument("--task-id", required=True)
    report = sub.add_parser("research-report", help="render a derived Markdown report from saved research records")
    report.add_argument("--project-root", required=True)
    report.add_argument("--task-id", required=True)
    report.add_argument("--output", help="optional project-relative or in-project absolute Markdown output")
    init = sub.add_parser("init-flac3d-project")
    init.add_argument("path")
    init.add_argument("--project-id", required=True)
    init.add_argument("--template", choices=("blank", "synthetic"), default="blank")
    si = sub.add_parser("init-synthetic-project")
    si.add_argument("path")
    si.add_argument("--project-id", required=True)
    iw = sub.add_parser("init-workspace", help="create a minimal three-file research workspace")
    iw.add_argument("path")
    iw.add_argument("--project-id", required=True)
    iw.add_argument("--question", required=True)
    wc = sub.add_parser("workspace-context", help="read-only navigation from an explicit INDEX.md")
    wc.add_argument("--workspace-root", required=True)
    z = sub.add_parser("validate-zotero-snapshot"); z.add_argument("path")
    z = sub.add_parser("inspect-zotero-snapshot"); z.add_argument("path"); z.add_argument("--project-id", default="zotero_snapshot")
    rc = sub.add_parser("run-create"); rc.add_argument("--runs-root", required=True); rc.add_argument("run_id"); rc.add_argument("--request-json", default="null"); rc.add_argument("--inputs-json", default='{"input_hashes":[]}')
    rr = sub.add_parser("run-record"); rr.add_argument("--runs-root", required=True); rr.add_argument("run_id"); rr.add_argument("stage"); rr.add_argument("--role", required=True); rr.add_argument("--model", required=True); rr.add_argument("--status", required=True); rr.add_argument("--inputs-json", default="null"); rr.add_argument("--outputs-json", default="null"); rr.add_argument("--data-json", default="{}")
    ri = sub.add_parser("run-inspect"); ri.add_argument("--runs-root", required=True); ri.add_argument("run_id")
    rv = sub.add_parser("run-validate"); rv.add_argument("--runs-root", required=True); rv.add_argument("run_id")
    ts = sub.add_parser("task-start"); ts.add_argument("--project-root", required=True); ts.add_argument("--request-json", required=True); ts.add_argument("--documentation-result", help="request evidence for synthetic tasks only; cannot verify production documentation")
    ti = sub.add_parser("task-inspect"); ti.add_argument("--project-root", required=True); ti.add_argument("task_id")
    context = sub.add_parser("project-context", help="read-only project navigation without a task ID")
    context.add_argument("--project-root", required=True)
    context.add_argument("--manifest", help="explicit project-relative JSON material list")
    context.add_argument("--offset", type=int, default=0)
    context.add_argument("--limit", type=int, default=8)
    resume = sub.add_parser("resume", aliases=["task-resume"], help="read-only compact recovery view")
    resume.add_argument("--project-root", "--project", dest="project_root", required=True)
    resume.add_argument("--task-id", "--task", dest="task_id", required=True)
    resume.add_argument("--max-chars", type=int, default=4000)
    show = sub.add_parser("show", help="read-only on-demand record or section view")
    show.add_argument("--project-root", "--project", dest="project_root", required=True)
    show.add_argument("record_id", nargs="?")
    show.add_argument("--record-id", dest="record_id_option")
    show.add_argument("--section")
    tr = sub.add_parser("task-record-evidence-review"); tr.add_argument("--project-root", required=True); tr.add_argument("task_id"); tr.add_argument("--operation-id", required=True); tr.add_argument("--assessment-json", required=True)
    ju = sub.add_parser("task-record-judgment-update"); ju.add_argument("--project-root", required=True); ju.add_argument("task_id"); ju.add_argument("--operation-id", required=True); ju.add_argument("--update-json", required=True)
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
    if args.command == "enable-research":
        from research_project import enable_research
        out = enable_research(args.project_root, args.project_id)
    elif args.command == "zotero-search":
        from mining_research_kernel.zotero_workflow import search_zotero
        out = search_zotero(args.registration, query=args.query,
                            collection_key=args.collection_key, limit=args.limit)
        if out.get("status") != "PASS":
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    elif args.command == "zotero-read":
        from mining_research_kernel.zotero_workflow import read_zotero
        result = read_zotero(
            args.project_root, registration=args.registration, task_id=args.task_id,
            question=args.question, item_key=args.item_key, attachment_key=args.attachment_key,
            pages=args.pages, collection_key=args.collection_key, task_context=args.task_context,
            max_reading_chars=args.max_reading_chars,
        )
        if "task_packet" not in result:
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        packet = result["task_packet"]
        out = {"type": "ZoteroReadReceipt", "task_id": result["task_id"],
               "status": result.get("status"), "diagnostics": result.get("diagnostics", []),
               "decision_id": result["decision_id"], "asset_refs": packet["asset_refs"],
               "evidence_refs": packet["evidence_refs"], "replayed": result["replayed"],
               "query_performed": result.get("query_performed", False),
               "source_read_attempted": result.get("source_read_attempted", False),
               "source_read_performed": result.get("source_read_performed", False),
               "originaltext_not_reread": result.get("originaltext_not_reread", False),
               "capture_summary": result["capture_summary"],
               "completion_scope": packet.get("completion_scope"),
               "research_judgment_status": packet["research_judgment_status"],
               "reading_texts": result.get("reading_texts", []),
               "run_created": False, "verification_created": False}
        if result.get("status") != "PASS" or packet["research_judgment_status"] == "INSUFFICIENT":
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    elif args.command == "itasca-query":
        from providers.itasca import query_itasca
        out = query_itasca(args.registration, operation=args.operation, software=args.software,
                           version=args.version, query=args.query, command=args.itasca_command,
                           topic=args.topic, limit=args.limit, max_reading_chars=args.max_reading_chars)
        if out.get("status") not in {"READ_WITH_LIMITS", "DISCOVERY_ONLY"}:
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    elif args.command == "documentation-read":
        from mining_research_kernel.documentation_reading import record_documentation_reading
        result = record_documentation_reading(
            args.project_root, task_id=args.task_id, question=args.question,
            registration=args.registration, provider=args.provider, page=args.page,
            product=args.product, product_version=args.product_version, anchor=args.anchor,
            operation=args.operation, software=args.software, version=args.version,
            query=args.query, command=args.itasca_command, topic=args.topic, limit=args.limit,
            max_reading_chars=args.max_reading_chars, task_context=args.task_context,
        )
        packet = result["task_packet"]
        out = {"type": "DocumentationReadingReceipt", "task_id": packet["task_id"],
               "decision_id": result["decision_id"], "asset_refs": packet["asset_refs"],
               "evidence_refs": packet["evidence_refs"], "documentation_result": result["documentation_result"],
               "reading_texts": result.get("reading_texts", []), "replayed": result["replayed"],
               "query_performed": result.get("query_performed", False),
               "source_read_performed": result.get("source_read_performed", False),
               "state": packet["state"], "completion_scope": packet.get("completion_scope"),
               "research_judgment_status": packet["research_judgment_status"],
               "run_created": False, "verification_created": False}
        if packet["research_judgment_status"] == "INSUFFICIENT":
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    elif args.command in {"research-begin", "research-continue"}:
        from mining_research_kernel.research_continuation import begin_research, continue_research
        if args.command == "research-begin":
            result = begin_research(args.project_root, task_id=args.task_id, question=args.question,
                                    asset_refs=args.asset_ref, mode=args.mode, dimensions=args.dimension,
                                    task_context=args.task_context)
        else:
            result = continue_research(args.project_root, task_id=args.task_id, from_task_id=args.from_task_id,
                                       asset_refs=args.asset_ref, reason=args.reason)
        packet = result["task_packet"]
        out = {"type": "ContinuingResearchTask", "task_id": packet["task_id"],
               "question_id": result["question_id"], "task_packet": packet, "state": packet["state"],
               "asset_refs": packet["asset_refs"], "evidence_refs": packet["evidence_refs"],
               "sources": result["sources"], "replayed": result["replayed"],
               "continuation": packet.get("input", {}).get("research_continuation"),
               "source_queries_performed": False}
        for template in ("comparison_template", "review_template"):
            if template in result:
                out[template] = result[template]
    elif args.command == "research-progress":
        from mining_research_kernel.research_continuation import research_progress
        out = research_progress(args.project_root, task_id=args.task_id)
    elif args.command == "research-report":
        from mining_research_kernel.research_report import render_research_report
        markdown = render_research_report(args.project_root, task_id=args.task_id)
        if args.output is None:
            print(markdown, end="" if markdown.endswith("\n") else "\n")
            return 0
        target, digest = _write_research_report(args.project_root, args.task_id, args.output, markdown)
        out = {"type": "ResearchReportReceipt", "task_id": args.task_id, "output": target,
               "sha256": digest, "authority": "derived", "source_queries_performed": False,
               "run_created": False, "verification_created": False}
    elif args.command == "literature-start":
        from mining_research_kernel.literature_comparison import start_literature_comparison
        result = start_literature_comparison(
            args.project_root, task_id=args.task_id, question=args.question, asset_refs=args.asset_ref,
            dimensions=args.dimension, task_context=args.task_context)
        packet = result["task_packet"]
        out = {"type": "LiteratureComparisonStart", "task_id": packet["task_id"],
               "state": packet["state"], "asset_refs": packet["asset_refs"],
               "evidence_refs": packet["evidence_refs"], "sources": result["sources"],
               "comparison_template": result["comparison_template"], "replayed": result["replayed"],
               "source_queries_performed": False}
    elif args.command == "literature-review":
        from mining_research_kernel.literature_comparison import record_literature_comparison
        with Path(args.comparison_file).expanduser().open("rb") as stream:
            raw = stream.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValueError("literature comparison exceeds 256 KiB")
        def unique_comparison_object(pairs):
            value = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("literature comparison has duplicate JSON keys")
                value[key] = item
            return value
        comparison = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_comparison_object,
                                parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
        result = record_literature_comparison(
            args.project_root, task_id=args.task_id, operation_id=args.operation_id,
            comparison=comparison, judgment_status=args.judgment)
        packet = result["task_packet"]
        out = {"type": "LiteratureComparisonReceipt", "task_id": packet["task_id"],
               "state": packet["state"], "decision_id": packet["review_record_ref"],
               "completion_scope": packet.get("completion_scope"),
               "asset_refs": packet["asset_refs"], "evidence_refs": packet["evidence_refs"],
               "research_judgment_status": packet["research_judgment_status"],
               "source_queries_performed": False, "run_created": False, "verification_created": False}
    elif args.command == "research-start":
        from mining_research_kernel.source_review import start_source_review
        result = start_source_review(args.project_root, task_id=args.task_id,
                                     question=args.question, asset_refs=args.asset_ref,
                                     task_context=args.task_context)
        packet = result["task_packet"]
        out = {"type": "SourceResearchStart", "task_id": packet["task_id"],
               "state": packet["state"], "asset_refs": packet["asset_refs"],
               "evidence_refs": packet["evidence_refs"], "sources": result["sources"],
               "review_template": result["review_template"], "replayed": result["replayed"],
               "source_queries_performed": False}
    elif args.command == "research-review":
        from mining_research_kernel.source_review import record_source_review
        with Path(args.review_file).expanduser().open("rb") as stream:
            note_bytes = stream.read(65537)
        if len(note_bytes) > 65536:
            raise ValueError("research review exceeds 64 KiB")
        result = record_source_review(
            args.project_root, task_id=args.task_id, operation_id=args.operation_id,
            note=note_bytes.decode("utf-8-sig"), judgment_status=args.judgment,
        )
        packet = result["task_packet"]
        out = {"type": "SourceResearchReviewReceipt", "task_id": packet["task_id"],
               "state": packet["state"], "decision_id": packet["review_record_ref"],
               "completion_scope": packet.get("completion_scope"),
               "asset_refs": packet["asset_refs"], "evidence_refs": packet["evidence_refs"],
               "research_judgment_status": packet["research_judgment_status"],
               "source_queries_performed": False, "run_created": False, "verification_created": False}
    elif args.command in {"zotero-record", "validate-zotero-reading"}:
        from mining_research_kernel.zotero_reading import validate_capture
        capture_path = Path(args.capture).expanduser()
        with capture_path.open("rb") as stream:
            capture_bytes = stream.read(256 * 1024 + 1)
        if len(capture_bytes) > 256 * 1024:
            raise ValueError("Zotero reading capture exceeds 256 KiB")
        capture = validate_capture(json.loads(capture_bytes.decode("utf-8-sig")))
        if args.command == "validate-zotero-reading":
            out = {"valid": True, "item_key": capture["item"]["key"],
                   "metadata_status": capture["metadata_status"],
                   "page_ranges": len(capture["pages"]), "source_revalidated": False}
        else:
            from mining_research_kernel.zotero_records import record_zotero_reading
            from mining_research_kernel.r2_workflow import load_json_value
            result = record_zotero_reading(
                args.project_root, task_id=args.task_id, question=args.question,
                capture=capture, findings=load_json_value(args.findings_json, "findings-json"),
                task_context=args.task_context,
            )
            packet = result["task_packet"]
            out = {"type": "ZoteroReadingRecordReceipt", "task_id": result["task_id"],
                   "decision_id": result["decision_id"], "asset_refs": packet["asset_refs"],
                   "evidence_refs": packet["evidence_refs"], "replayed": result["replayed"],
                   "query_performed": False, "source_revalidated": False,
                   "capture_origin": capture["origin"], "captured_at": capture["captured_at"],
                   "source": {"instance_id": capture["instance_id"], "library_id": capture["library_id"],
                              "item_key": capture["item"]["key"], "item_version": capture["item"]["version"]},
                   "metadata_status": capture["metadata_status"],
                   "reading_status": result["capture_summary"]["reading_status"],
                   "page_ranges_read": [{"attachment_key": p["attachment_key"],
                                         "start_page": p["start_page"], "end_page": p["end_page"]}
                                        for p in capture["pages"] if p["status"] == "read"],
                   "task_state": packet["state"], "completion_scope": packet["completion_scope"],
                   "research_judgment_status": packet["research_judgment_status"],
                   "run_created": False, "verification_created": False}
            if packet["research_judgment_status"] == "INSUFFICIENT":
                print(json.dumps(out, ensure_ascii=False, indent=2))
                return 2
    elif args.command == "documentation-record":
        from mining_research_kernel.documentation_records import record_documentation_query
        out = record_documentation_query(
            args.project_root, task_id=args.task_id, question=args.question,
            registration=args.registration, page=args.page, command=args.syntax_command,
            product=args.product, product_version=args.product_version,
            anchor=args.anchor, task_context=args.task_context,
        )
        # Return the observation and its record locators once. Full packets,
        # Decisions and transaction payloads remain available through show.
        packet = out["task_packet"]
        out = {
            "type": "DocumentationRecordReceipt",
            "task_id": out["task_id"], "decision_id": out["decision_id"],
            "asset_refs": packet["asset_refs"], "evidence_refs": packet["evidence_refs"],
            "documentation_result": out["documentation_result"],
            "replayed": out["replayed"], "query_performed": out["query_performed"],
            "task_state": packet["state"], "completion_scope": packet["completion_scope"],
            "research_judgment_status": packet["research_judgment_status"],
            "run_created": False, "verification_created": False,
        }
        if out["documentation_result"].get("status") not in {"VERIFIED", "SYNTHETIC_VERIFIED"}:
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return 2
    elif args.command == "init-workspace":
        from workspace_init import init_workspace
        out = {"initialized": str(init_workspace(args.path, args.project_id, args.question)),
               "project_id": args.project_id, "files": ["AGENTS.md", "INDEX.md", f"projects/{args.project_id}/START.md"]}
    elif args.command == "workspace-context":
        from mining_research_kernel.workspace_context import workspace_context
        out = workspace_context(args.workspace_root)
    elif args.command == "task-start":
        from mining_research_kernel.r2_workflow import load_json_value, task_start
        request = load_json_value(args.request_json, "request-json")
        if not isinstance(request, dict):
            raise ValueError("request-json must contain a JSON object")
        if args.documentation_result is not None:
            documentation = load_json_value(args.documentation_result, "documentation-result")
            if not isinstance(documentation, dict):
                raise ValueError("documentation-result must contain a JSON object")
            request["documentation_result"] = documentation
        out = task_start(args.project_root, request)
    elif args.command == "task-inspect":
        from mining_research_kernel.r2_workflow import task_inspect
        out = task_inspect(args.project_root, args.task_id)
    elif args.command == "project-context":
        from mining_research_kernel.project_context import project_context
        out = project_context(args.project_root, manifest=args.manifest, offset=args.offset, limit=args.limit)
    elif args.command in {"resume", "task-resume"}:
        from mining_research_kernel.on_demand import resume_task
        out = resume_task(args.project_root, args.task_id, max_chars=args.max_chars)
    elif args.command == "show":
        from mining_research_kernel.on_demand import show_record
        record_id = args.record_id_option or args.record_id
        if not record_id:
            raise ValueError("show requires a record id")
        out = show_record(args.project_root, record_id, section=args.section)
    elif args.command == "task-record-evidence-review":
        from mining_research_kernel.r2_workflow import load_json_value, task_record_evidence_review
        out = task_record_evidence_review(
            args.project_root, args.task_id, args.operation_id,
            load_json_value(args.assessment_json, "assessment-json"),
        )
    elif args.command == "task-record-judgment-update":
        from mining_research_kernel.r2_workflow import load_json_value, task_record_judgment_update
        out = task_record_judgment_update(
            args.project_root, args.task_id, args.operation_id,
            load_json_value(args.update_json, "update-json"),
        )
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
