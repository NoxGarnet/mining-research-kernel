"""Search, read, and record bounded observations from an explicitly selected Zotero Host."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any

from adapters.zotero_mcp_readonly import dispatch
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.zotero_reading import (
    KEY_RE, _page_text, collect_reading,
)
from mining_research_kernel.zotero_records import record_zotero_reading
from mining_research_kernel.r2_workflow import _id
from providers.zotero import ZoteroHostError, ZoteroReader, load_registration

_PAGE_RANGE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


def _failure(reason: str, message: str) -> dict[str, Any]:
    return {"status": "CANNOT_VERIFY", "diagnostics": [{"code": reason, "message": message}]}


def _parse_pages(value: str | None, attachment_key: str | None) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, str) or not value.strip():
        raise ValueError("pages must be a comma-separated list such as 1,3-4")
    parts = value.split(",")
    if len(parts) > 10:
        raise ValueError("pages may contain at most 10 ranges")
    if attachment_key is None or not isinstance(attachment_key, str) or not KEY_RE.fullmatch(attachment_key):
        raise ValueError("an explicit attachment_key using eight letters/digits is required with pages")
    result = []
    for part in parts:
        match = _PAGE_RANGE_RE.fullmatch(part.strip())
        if not match:
            raise ValueError("pages must be a comma-separated list such as 1,3-4")
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start < 1 or end < start or end - start + 1 > 10:
            raise ValueError("each page range must contain 1..10 positive pages")
        result.append({"attachment_key": attachment_key, "start_page": start, "end_page": end})
    return result


def _replay(project_root: str | Path, task_id: str, registration: dict[str, Any], question: str,
            item_key: str, collection_key: str | None, ranges: list[dict[str, Any]],
            task_context: str) -> dict[str, Any] | None:
    store = ResearchStore(Path(project_root).expanduser())
    task = store.latest_record(task_id, "TaskState")
    if task is None:
        return None
    packet = task.get("packet", {})
    asset_refs = packet.get("asset_refs", [])
    asset = store.latest_record(asset_refs[0], "Asset") if asset_refs else None
    try:
        saved_request = asset["payload"]["request"]
        capture = saved_request["capture"]
    except (TypeError, KeyError):
        raise ValueError(f"task_id already exists for a different task: {task_id}") from None
    saved_ranges = [{"attachment_key": page["attachment_key"], "start_page": page["start_page"],
                     "end_page": page["end_page"]} for page in capture.get("pages", [])]
    range_match = ranges == saved_ranges
    same = (packet.get("input", {}).get("question") == question
            and packet.get("task_context", task_context) == task_context
            and capture.get("instance_id") == registration["instance_id"]
            and capture.get("library_id") == registration["library_id"]
            and capture.get("item", {}).get("key") == item_key
            and capture.get("collection_key") == collection_key
            and range_match)
    if not same:
        raise ValueError(f"task_id already records a different Zotero reading request: {task_id}")
    recorded = record_zotero_reading(project_root, task_id=task_id, question=question,
                                     capture=capture, task_context=task_context)
    complete = (capture.get("metadata_status") == "read"
                and all(page.get("status") == "read" for page in capture.get("pages", []))
                and not any(item.get("code") == "collection_unavailable"
                            for item in capture.get("diagnostics", [])))
    recorded.update({"status": "PASS" if complete else "CANNOT_VERIFY",
                     "diagnostics": [] if complete else [{
                         "code": "zotero_read_unavailable",
                         "message": "The stored Zotero observation was incomplete; the source was not reread.",
                     }], "query_performed": False,
                     "source_read_attempted": False, "source_read_performed": False,
                     "reading_texts": [],
                     "originaltext_not_reread": True})
    return recorded


def search_zotero(registration: str | Path, *, query: str, collection_key: str | None = None,
                  limit: int = 10) -> dict[str, Any]:
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise ValueError("query must be a non-empty string of at most 500 characters")
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer from 1 to 50")
    if collection_key is not None and (not isinstance(collection_key, str) or not KEY_RE.fullmatch(collection_key)):
        raise ValueError("collection_key must use eight letters/digits")
    profile = load_registration(registration)
    try:
        with ZoteroReader(profile) as reader:
            availability = dispatch(Path("."), action="inspect", reader=reader,
                                    operation="zotero_get_collections", params={})
            if availability["status"] != "PASS":
                return _failure("zotero_unavailable", "Zotero collection availability could not be confirmed")
            params: dict[str, Any] = {"query": query.strip(), "limit": limit}
            if collection_key is not None:
                params["collection_key"] = collection_key
            result = dispatch(Path("."), action="inspect", reader=reader,
                              operation="zotero_search_items", params=params)
            if result["status"] != "PASS":
                return _failure("search_unavailable", "Zotero search did not complete")
            return {"status": "PASS", "diagnostics": [], "result": result["result"],
                    "query_performed": True}
    except (ZoteroHostError, OSError):
        return _failure("zotero_unavailable", "Zotero Host connection could not be completed")


def read_zotero(project_root: str | Path, *, registration: str | Path, task_id: str,
                question: str, item_key: str, attachment_key: str | None = None,
                pages: str | None = None, collection_key: str | None = None,
                task_context: str = "production", max_reading_chars: int = 12000) -> dict[str, Any]:
    # Validate every caller-controlled field before loading a Host executable or changing the ledger.
    task_id = _id(task_id, "task_id")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if not isinstance(item_key, str) or not KEY_RE.fullmatch(item_key):
        raise ValueError("item_key must use eight letters/digits")
    if attachment_key is not None and (not isinstance(attachment_key, str) or not KEY_RE.fullmatch(attachment_key)):
        raise ValueError("attachment_key must use eight letters/digits")
    if collection_key is not None and (not isinstance(collection_key, str) or not KEY_RE.fullmatch(collection_key)):
        raise ValueError("collection_key must use eight letters/digits")
    if task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")
    if type(max_reading_chars) is not int or not 1 <= max_reading_chars <= 48000:
        raise ValueError("max_reading_chars must be an integer from 1 to 48000")
    requested = _parse_pages(pages, attachment_key)
    if attachment_key is not None and pages is None:
        raise ValueError("attachment_key requires an explicit pages request")
    profile = load_registration(registration)
    replay = _replay(project_root, task_id, profile, question.strip(), item_key,
                     collection_key, requested, task_context)
    if replay is not None:
        return replay

    reading_texts: list[dict[str, Any]] = []
    intercepted: list[dict[str, Any]] = []
    source_calls = 0
    resolved_ranges = requested
    try:
        with ZoteroReader(profile) as reader:
            def tracked_reader(operation: str, params: dict[str, Any]) -> Any:
                nonlocal source_calls
                source_calls += 1
                return reader(operation, params)

            # Confirm connection health before any search-like empty result is trusted.
            availability = dispatch(Path("."), action="inspect", reader=tracked_reader,
                                    operation="zotero_get_collections", params={})
            if availability["status"] != "PASS":
                raise ZoteroHostError("zotero_unavailable")
            def capture_reader(operation: str, params: dict[str, Any]) -> Any:
                response = tracked_reader(operation, params)
                if operation == "zotero_read_pdf_pages":
                    intercepted.append({"params": dict(params), "response": response})
                return response

            capture = collect_reading(capture_reader, instance_id=profile["instance_id"],
                                      library_id=profile["library_id"], item_key=item_key,
                                      pages=resolved_ranges, collection_key=collection_key,
                                      origin="external_mcp")
            budget = max_reading_chars
            for request in intercepted:
                params = request["params"]
                key = params.get("attachment_key", params.get("item_key"))
                start = params.get("start_page", params.get("start"))
                end = params.get("end_page", params.get("end"))
                try:
                    _, text = _page_text(request["response"], key, start, end)
                except Exception:
                    text = ""
                take = min(len(text), budget)
                reading_texts.append({"attachment_key": key, "start_page": start, "end_page": end,
                                      "text": text[:take], "truncated": take < len(text),
                                      "original_char_count": len(text)})
                budget -= take
    except (ZoteroHostError, OSError, TimeoutError, RuntimeError):
        # A valid, explicitly selected Host that is offline produces a durable unavailable observation.
        capture = _unavailable_capture(profile, item_key, collection_key, resolved_ranges)
        failure = _failure("zotero_unavailable", "Zotero Host connection or read did not complete")
    else:
        incomplete = (capture["metadata_status"] != "read"
                      or any(page["status"] != "read" for page in capture["pages"])
                      or any(item["code"] == "collection_unavailable" for item in capture["diagnostics"]))
        failure = (_failure("zotero_read_unavailable",
                            "Zotero metadata or one or more selected page ranges could not be read")
                   if incomplete else None)

    receipt = record_zotero_reading(project_root, task_id=task_id, question=question.strip(),
                                    capture=capture, task_context=task_context)
    source_read_performed = (capture["metadata_status"] == "read"
                             and all(page["status"] == "read" for page in capture["pages"])
                             and not any(item["code"] == "collection_unavailable"
                                         for item in capture["diagnostics"]))
    receipt.update({"status": failure["status"] if failure else "PASS",
                    "diagnostics": failure["diagnostics"] if failure else capture["diagnostics"],
                    "query_performed": source_calls > 0, "source_read_attempted": source_calls > 0,
                    "source_read_performed": source_read_performed,
                    "reading_texts": reading_texts, "originaltext_not_reread": False})
    return receipt


def _unavailable_capture(profile: dict[str, Any], item_key: str, collection_key: str | None,
                         pages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "kind": "zotero_reading_capture", "origin": "external_mcp",
            "instance_id": profile["instance_id"], "library_id": profile["library_id"],
            "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "item": {"key": item_key, "version": None, "title": "", "item_type": "", "doi": None},
            "collection_key": collection_key, "metadata_status": "unavailable",
            "pages": [{"attachment_key": page["attachment_key"], "attachment_version": None,
                       "start_page": page["start_page"], "end_page": page["end_page"],
                       "status": "unavailable", "text_sha256": None, "excerpt": ""}
                      for page in pages if "attachment_key" in page],
            "diagnostics": [{"code": "zotero_unavailable", "message": "Zotero Host connection or read did not complete"}]}


__all__ = ["read_zotero", "search_zotero"]
