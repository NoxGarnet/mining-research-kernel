"""Project-local navigation, without registration, source reads or view writes."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .core import safe_path
from .markdown_navigation import inline_code_spans, inline_links, mask_comments_and_fences
from .on_demand import (
    _continuation_parent, _decision_bound_to_task_state, _decision_records,
    _decision_selection, _judgment, _latest_records, _question_and_routes,
    is_research_review_continuation, is_research_review_task,
)
from .records import ResearchStore

MAX_ENTRY_BYTES = 65536
MAX_MANIFEST_BYTES = 131072
FILE_SUFFIXES = {"md", "txt", "csv", "tsv", "json", "yaml", "yml", "toml",
                 "dat", "fis", "py", "pdf", "doc", "docx", "xls", "xlsx"}


def _inline_file_path(value: str) -> str | None:
    """Conservative lexical recognition, not filesystem discovery or code parsing."""
    relative = value.replace("\\", "/")
    if not re.fullmatch(r"(?:\./)?[\w.-]+(?:/[\w.-]+)*", relative):
        return None
    if ".." in relative.split("/"):
        return None
    filename = relative.rsplit("/", 1)[-1]
    stem, dot, suffix = filename.rpartition(".")
    if not dot or not stem or suffix.lower() not in FILE_SUFFIXES:
        return None
    return relative.removeprefix("./")


def _preview(value, limit=280):
    text = str(value or "")
    return {"text": text[:limit], "truncated": len(text) > limit}


def _read_metadata(path: Path, limit: int) -> tuple[str, bool]:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    return raw[:limit].decode("utf-8-sig", errors="replace"), len(raw) > limit


def _argv(root: Path, command: str, *args: str) -> list[str]:
    cli = Path(__file__).resolve().parents[1] / "mining_kernel.py"
    return [sys.executable, "-B", "-X", "utf8", str(cli), command, "--project-root", str(root), *args]


def _location(root: Path, relative: str) -> dict:
    """Resolve explicit locators, never open or hash their target bytes."""
    try:
        if not relative or "\x00" in relative:
            raise ValueError("empty or invalid path")
        path = safe_path(root, relative)
    except (ValueError, OSError, RuntimeError):
        return {"recorded_path": relative, "status": "unsafe_path_not_followed"}
    return {"path": str(path), "status": "not_read_or_verified_this_call",
            "existence": "not_checked"}


def project_context(project_root: str | Path, *, manifest: str | None = None,
                    offset: int = 0, limit: int = 8) -> dict:
    """Enumerate explicit navigation only; all output is a disposable projection.

    Markdown is entry metadata, never interpreted as instructions. Only simple
    inline local links and conservative backtick file paths are extracted. A supplied JSON material list is metadata,
    not a second research authority. Source targets remain unopened.
    """
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("project root must be an existing directory")
    if offset < 0 or not 1 <= limit <= 20:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 20")
    entries, materials, tasks, failures, decisions = [], [], [], [], []
    warnings = []
    neutral_config = safe_path(root, "research_project.json")
    legacy_config = safe_path(root, "flac3d_project.yaml")
    entry_names = ["START.md", "README.md"]
    if neutral_config.exists() or legacy_config.exists():
        from research_project import load_config
        configured_entry = load_config(root).get("entry", "START.md")
        entry_names = list(dict.fromkeys([configured_entry, *entry_names]))
    for name in entry_names:
        path = safe_path(root, name)
        if not path.is_file():
            continue
        text, clipped = _read_metadata(path, MAX_ENTRY_BYTES)
        entries.append({"kind": "entry", "id": name, "preview": _preview(text),
                        "read_location": {"path": str(path)}, "entry_scan_truncated": clipped})
        if clipped:
            warnings.append(f"{name}: only first {MAX_ENTRY_BYTES} bytes inspected for links")
        # Comments and fenced examples are not an entry's material catalogue.
        prose = mask_comments_and_fences(text)
        linked_paths, link_spans = set(), []
        for match in inline_links(prose):
            link_spans.append(match.span())
            title, target = match.groups()
            try:
                url = urlsplit(target.strip("<>"))
            except ValueError as exc:
                warnings.append(f"{name}: malformed link ignored: {exc}")
                continue
            if url.scheme or url.netloc or not url.path:
                continue
            relative = unquote(url.path)
            linked_paths.add(relative.replace("\\", "/").removeprefix("./"))
            materials.append({"kind": "material", "id": f"{name}:{match.start()}",
                              "title": _preview(title), "basis": f"explicit link in {name}",
                              "location": _location(root, (Path(name).parent / relative).as_posix()), "anchor": unquote(url.fragment)})
        for code_start, code_end, width in inline_code_spans(prose):
            if width != 1 or any(start <= code_start < end for start, end in link_spans):
                continue
            relative = _inline_file_path(prose[code_start + 1:code_end - 1])
            if relative is None or relative in linked_paths:
                continue
            linked_paths.add(relative)
            materials.append({"kind": "material", "id": f"{name}:inline:{code_start}",
                              "title": _preview(relative), "basis": f"explicit inline file path in {name}",
                              "entry_line": text.count("\n", 0, code_start) + 1,
                              "location": _location(root, (Path(name).parent / relative).as_posix())})
    if not entries:
        warnings.append("No configured entry, START.md or README.md; no project purpose inferred.")

    if manifest is not None:
        path = safe_path(root, manifest)
        text, clipped = _read_metadata(path, MAX_MANIFEST_BYTES)
        if clipped:
            raise ValueError("material manifest exceeds 131072 bytes; pass a smaller explicit list")
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("materials"), list):
            raise ValueError("manifest.materials must be a list")
        for index, item in enumerate(data["materials"]):
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                raise ValueError(f"manifest.materials[{index}].path must be a string")
            materials.append({"kind": "material", "id": f"manifest:{index}",
                              "title": _preview(item.get("title", item["path"])),
                              "basis": f"explicit manifest {manifest}",
                              "location": _location(root, item["path"])})

    records_path = safe_path(root, "research/records")
    project_id = None
    store_state = "not_initialized"
    revision = None
    if neutral_config.exists() or legacy_config.exists():
        # Use authoritative transactions, not a potentially stale Research Map.
        store = ResearchStore(root)
        transactions = store.list_transactions()
        # Reuse existing record folding without loading transactions twice.
        class Snapshot:
            def list_transactions(self):
                return transactions
        latest = _latest_records(Snapshot())
        project_id = store.project_id
        store_state = "recorded" if transactions else "empty"
        revision = transactions[-1]["sequence"] if transactions else 0
        for record in sorted(latest.values(), key=lambda r: r["id"]):
            rid = record["id"]
            show = _argv(root, "show", "--record-id", rid)
            if record["type"] == "TaskState":
                packet = record["packet"]
                question, _, routes = _question_and_routes(latest, packet)
                inherited = (_continuation_parent(store, rid, packet)
                             if is_research_review_continuation(packet) else None)
                bound_current = _decision_bound_to_task_state(store, record)
                related = _decision_records(latest, rid, packet, [r["id"] for r in routes],
                                            exact_decisions=[d for d in (inherited, bound_current) if d])
                selection = _decision_selection(related, rid, packet,
                                                [inherited] if inherited and not packet.get("review_record_ref") else None)
                current = selection["current"]
                tasks.append({"kind": "task", "id": rid, "revision": record["revision"],
                              "state": record.get("state"), "question": _preview(question),
                              "selection": selection["reason"],
                              "current_decision_count": len(current),
                              "current_decisions_preview": [{"id": d["id"], "revision": d["revision"],
                                  "status": d.get("status"), "summary": _preview(_judgment(d).get("summary", d.get("statement"))),
                                  "limits": "expand resume/show before relying on this judgment"} for d in current[:2]],
                              "inherited_decisions_preview": [{"id": d["id"], "revision": d["revision"],
                                  "summary": _preview(_judgment(d).get("summary", d.get("statement"))),
                                  "state": "inherited_pending",
                                  "expansion_argv": _argv(root, "show", "--record-id", d["id"],
                                                          "--revision", str(d["revision"]),
                                                          "--section", "judgment")} for d in selection.get("inherited", [])],
                              "history_count": len(selection["history"]),
                              "conflict_count": len(selection["conflicts"]),
                              "resume_argv": _argv(root, "resume", "--task", rid)})
                if is_research_review_task(packet):
                    tasks[-1]["research_progress_argv"] = _argv(root, "research-progress", "--task-id", rid)
                    tasks[-1]["research_report_argv"] = _argv(root, "research-report", "--task-id", rid)
                elif packet.get("input", {}).get("review_mode") == "flac3d_script_review":
                    tasks[-1]["script_review_progress_argv"] = _argv(root, "script-review-progress", "--task-id", rid)
                    tasks[-1]["script_review_report_argv"] = _argv(root, "script-review-report", "--task-id", rid)
                elif packet.get("input", {}).get("review_mode") in {"result_csv_import", "result_csv_comparison"}:
                    tasks[-1]["result_progress_argv"] = _argv(root, "result-progress", "--task-id", rid)
                    tasks[-1]["result_report_argv"] = _argv(root, "result-report", "--task-id", rid)
            elif record["type"] == "Asset":
                locator = record.get("locator", {})
                loc = ({"recorded_locator": locator, "status": "caller_label_or_unresolved; supply location explicitly"})
                if isinstance(locator, dict) and locator.get("path_kind") == "project_relative" and isinstance(locator.get("path"), str):
                    loc = _location(root, locator["path"])
                    loc["citation"] = locator.get("citation")
                elif isinstance(locator, dict) and locator.get("path_kind") == "record_embedded":
                    loc = {"recorded_locator": locator,
                           "status": "embedded_record_payload; expand show",
                           "source_original_status": "not_revalidated_this_call"}
                materials.append({"kind": "asset", "id": rid, "revision": record["revision"],
                                  "recorded_status": record.get("status"),
                                  "basis": "registered Asset; not a new read", "location": loc,
                                  "show_argv": show})
                if record.get("asset_kind") == "reading_observation":
                    source = record.get("payload", {}).get("request", {}).get("observation", {}).get("source", {})
                    materials[-1]["title"] = _preview(source.get("title", ""))
                    materials[-1]["source_kind"] = source.get("source_kind")
            elif (record["type"] == "RunReference" and record.get("plan_asset_ref")
                  and record["id"].startswith("itasca.run.")):
                tasks.append({"kind": "external_run", "id": rid, "revision": record["revision"],
                              "run_id": record.get("run_id"), "state": record.get("status"),
                              "scope_note": "saved external execution observations; live engine not queried",
                              "show_argv": show,
                              "progress_argv": _argv(root, "itasca-run-progress", "--run-id", record["run_id"]),
                              "report_argv": _argv(root, "itasca-run-report", "--run-id", record["run_id"])})
            elif record["type"] == "Failure":
                failures.append({"kind": "failure", "id": rid, "revision": record["revision"],
                                 "status": record.get("status"),
                                 "summary": _preview(record.get("observable_failure")),
                                 "scope_note": "project candidate only; applicability requires expansion",
                                 "show_argv": show})
            elif record["type"] == "Decision":
                decisions.append({"kind": "decision", "id": rid, "revision": record["revision"],
                                  "status": record.get("status"), "summary": _preview(record.get("statement")),
                                  "scope_note": "not selected as project-wide current; inspect task/record",
                                  "show_argv": show})
    elif records_path.exists():
        warnings.append("research/records exists without project config; records not interpreted")

    items = entries + tasks + failures + materials + decisions
    args = (["--manifest", manifest] if manifest is not None else [])
    view = {"schema_version": 1, "type": "ProjectContextView", "project_root": str(root),
            "project_id": project_id, "store_state": store_state, "record_sequence": revision,
            "read_only": True, "source_bytes_reopened": False, "active_task": None,
            "selection_policy": "explicit project only; choose a task, never infer current from recency",
            "limitations": ["Entry previews are navigation text, not verified research conclusions.",
                            "Only entry files, an explicit manifest and kernel records were read; source targets not read or rehashed.",
                            "Previews are incomplete; expand before relying on scope, limitations or next actions.",
                            "No semantic relevance search, recursive workspace scan, or automatic registration."],
            "counts": {"entries": len(entries), "tasks": len(tasks), "failures": len(failures),
                       "materials": len(materials), "decisions": len(decisions)},
            "warnings": warnings, "items": items[offset:offset + limit],
            "budget": {"target_unicode_chars": 4000, "oversized_single_entry": False}}
    # Whole rows are paginated, never silently removed. A pathological single
    # row remains inspectable with an explicit over-budget flag instead of error.
    while True:
        count = len(view["items"])
        next_offset = offset + count if offset + count < len(items) else None
        view["page"] = {"offset": offset, "limit": limit, "returned": count,
                        "total": len(items), "next_offset": next_offset,
                        "next_argv": _argv(root, "project-context", *args, "--offset", str(next_offset),
                                           "--limit", str(limit)) if next_offset is not None else None}
        if len(json.dumps(view, ensure_ascii=False, indent=2)) <= 4000:
            return view
        if count <= 1:
            view["budget"]["oversized_single_entry"] = True
            return view
        view["items"].pop()
