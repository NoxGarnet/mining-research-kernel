"""Project-local navigation, without registration, source reads or view writes."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from .core import safe_path
from .on_demand import (
    _decision_records, _decision_selection, _judgment, _latest_records,
    _question_and_routes,
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
    for name in ("START.md", "README.md"):
        path = safe_path(root, name)
        if not path.is_file():
            continue
        text, clipped = _read_metadata(path, MAX_ENTRY_BYTES)
        entries.append({"kind": "entry", "id": name, "preview": _preview(text),
                        "read_location": {"path": str(path)}, "entry_scan_truncated": clipped})
        if clipped:
            warnings.append(f"{name}: only first {MAX_ENTRY_BYTES} bytes inspected for links")
        # Fenced examples are not an entry's material catalogue.
        prose = re.sub(r"```.*?```|~~~.*?~~~", lambda m: re.sub(r"[^\n]", " ", m[0]), text, flags=re.S)
        linked_paths, link_spans = set(), []
        for match in re.finditer(r"(?<!!)\[([^\]\n]+)\]\((<[^>\n]+>|[^\s()]+)\)", prose):
            link_spans.append(match.span())
            title, target = match.groups()
            url = urlsplit(target.strip("<>"))
            if url.scheme or url.netloc or not url.path:
                continue
            relative = unquote(url.path)
            linked_paths.add(relative.replace("\\", "/").removeprefix("./"))
            materials.append({"kind": "material", "id": f"{name}:{match.start()}",
                              "title": _preview(title), "basis": f"explicit link in {name}",
                              "location": _location(root, relative), "anchor": unquote(url.fragment)})
        for match in re.finditer(r"(?<!`)`([^`\n]+)`(?!`)", prose):
            if any(start <= match.start() < end for start, end in link_spans):
                continue
            relative = _inline_file_path(match[1])
            if relative is None or relative in linked_paths:
                continue
            linked_paths.add(relative)
            materials.append({"kind": "material", "id": f"{name}:inline:{match.start()}",
                              "title": _preview(relative), "basis": f"explicit inline file path in {name}",
                              "entry_line": text.count("\n", 0, match.start()) + 1,
                              "location": _location(root, relative)})
    if not entries:
        warnings.append("No START.md or README.md; no project purpose inferred.")

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

    neutral_config = safe_path(root, "research_project.json")
    legacy_config = safe_path(root, "flac3d_project.yaml")
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
                related = _decision_records(latest, rid, packet, [r["id"] for r in routes])
                selection = _decision_selection(related, rid, packet)
                current = selection["current"]
                tasks.append({"kind": "task", "id": rid, "revision": record["revision"],
                              "state": record.get("state"), "question": _preview(question),
                              "selection": selection["reason"],
                              "current_decision_count": len(current),
                              "current_decisions_preview": [{"id": d["id"], "revision": d["revision"],
                                  "status": d.get("status"), "summary": _preview(_judgment(d).get("summary", d.get("statement"))),
                                  "limits": "expand resume/show before relying on this judgment"} for d in current[:2]],
                              "history_count": len(selection["history"]),
                              "conflict_count": len(selection["conflicts"]),
                              "resume_argv": _argv(root, "resume", "--task", rid)})
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
