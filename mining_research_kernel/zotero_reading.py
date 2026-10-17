"""Bounded, read-only capture of external Zotero reader observations.

Captures are observations supplied by an external MCP reader. They do not
verify the underlying publication or imply freshness of Zotero versions.
The JSON Schema describes field structure; runtime validation additionally
checks relational page bounds and cross-field reading-state requirements.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from adapters.zotero_mcp_readonly import READ_OPERATIONS, dispatch
from zotero_snapshot import normalize_doi


ROOT_KEYS = {"schema_version", "kind", "origin", "instance_id", "library_id",
             "captured_at", "item", "collection_key", "metadata_status",
             "pages", "diagnostics"}
ITEM_KEYS = {"key", "version", "title", "item_type", "doi"}
PAGE_KEYS = {"attachment_key", "attachment_version", "start_page", "end_page",
             "status", "text_sha256", "excerpt"}
DIAGNOSTIC_KEYS = {"code", "message"}
KEY_RE = re.compile(r"^[A-Za-z0-9]{8}$")
LIBRARY_RE = re.compile(r"^(?:users|groups)/\d+$")
INSTANCE_RE = re.compile(r"^[a-f0-9]{16,64}$")
HASH_RE = re.compile(r"^[a-f0-9]{64}$")
UTC_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$")
_PAGE_HEADER_RE = re.compile(r"(?m)^## Page (\d+)\s*$")
_ITEM_HEADER_RE = re.compile(r"(?m)^\*\*Item Key:\*\*\s*([A-Za-z0-9]{8})\s*$")
_RANGE_HEADER_RE = re.compile(r"(?m)^# PDF Pages (\d+)-(\d+) of PDF\s*$")
_MAX_REQUESTS = 10
_MAX_PAGES_PER_REQUEST = 10
_MAX_EXCERPT = 1000


class CaptureValidationError(ValueError):
    """A reading capture violates the runtime contract."""


def _object(value: Any, where: str) -> dict:
    if not isinstance(value, dict):
        raise CaptureValidationError(f"{where} must be an object")
    return value


def _exact_keys(value: dict, expected: set[str], where: str) -> None:
    missing, extra = expected - value.keys(), value.keys() - expected
    if missing:
        raise CaptureValidationError(f"{where} missing fields: {sorted(missing)}")
    if extra:
        raise CaptureValidationError(f"unknown fields at {where}: {sorted(extra)}")


def _string(value: Any, where: str, *, nonempty: bool = True) -> str:
    if not isinstance(value, str):
        raise CaptureValidationError(f"{where} must be a string")
    if nonempty and not value.strip():
        raise CaptureValidationError(f"{where} must be non-empty")
    if value.startswith(("/", "\\")) or re.search(
        r"(?i)(?:(?<![A-Za-z0-9+.-])[A-Z]:[\\/]|file:/{0,3}|(?:^|[\s('=])/(?:[^/\s]+/)+[^/\s]*|\\\\[^\\/\s]+[\\/])", value
    ):
        raise CaptureValidationError(f"local or absolute paths are forbidden at {where}")
    return value


def _version(value: Any, where: str) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
        raise CaptureValidationError(f"{where} must be a nonnegative integer or null")


def _page_number(value: Any, where: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise CaptureValidationError(f"{where} must be a positive integer")


def _utc(value: str) -> bool:
    if not UTC_ISO_RE.fullmatch(value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def validate_capture(capture: Any) -> dict:
    """Validate and return a deep copy of a capture, rejecting unknown fields."""
    data = _object(capture, "capture")
    _exact_keys(data, ROOT_KEYS, "root")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise CaptureValidationError("schema_version must be integer 1")
    if data["kind"] != "zotero_reading_capture":
        raise CaptureValidationError("kind must be zotero_reading_capture")
    if not isinstance(data["origin"], str) or data["origin"] not in {"external_mcp", "synthetic"}:
        raise CaptureValidationError("origin must be external_mcp or synthetic")
    instance_id = _string(data["instance_id"], "instance_id")
    if not INSTANCE_RE.fullmatch(instance_id):
        raise CaptureValidationError("instance_id must be lowercase hex of length 16..64")
    library_id = _string(data["library_id"], "library_id")
    if not LIBRARY_RE.fullmatch(library_id):
        raise CaptureValidationError("library_id must be users/<integer> or groups/<integer>")
    captured_at = _string(data["captured_at"], "captured_at")
    if not _utc(captured_at):
        raise CaptureValidationError("captured_at must be a UTC ISO timestamp")
    item = _object(data["item"], "item")
    _exact_keys(item, ITEM_KEYS, "item")
    if not isinstance(item["key"], str) or not KEY_RE.fullmatch(item["key"]):
        raise CaptureValidationError("item.key must use eight letters/digits")
    _version(item["version"], "item.version")
    _string(item["title"], "item.title", nonempty=False)
    _string(item["item_type"], "item.item_type", nonempty=False)
    if item["doi"] is not None:
        try:
            normalized = normalize_doi(item["doi"])
        except (TypeError, ValueError) as exc:
            raise CaptureValidationError(f"item.doi: {exc}") from exc
        if normalized != item["doi"]:
            raise CaptureValidationError("item.doi must be normalized lowercase DOI text")
    collection_key = data["collection_key"]
    if collection_key is not None and (not isinstance(collection_key, str) or not KEY_RE.fullmatch(collection_key)):
        raise CaptureValidationError("collection_key must be eight letters/digits or null")
    if not isinstance(data["metadata_status"], str) or data["metadata_status"] not in {"read", "unavailable"}:
        raise CaptureValidationError("metadata_status must be read or unavailable")
    if data["metadata_status"] == "read" and not item["title"].strip():
        raise CaptureValidationError("metadata cannot be read with an empty title")
    pages = data["pages"]
    if not isinstance(pages, list) or len(pages) > _MAX_REQUESTS:
        raise CaptureValidationError("pages must be an array of at most 10 page-range requests")
    for i, raw in enumerate(pages):
        page = _object(raw, f"pages[{i}]")
        _exact_keys(page, PAGE_KEYS, f"pages[{i}]")
        if not isinstance(page["attachment_key"], str) or not KEY_RE.fullmatch(page["attachment_key"]):
            raise CaptureValidationError(f"pages[{i}].attachment_key must use eight letters/digits")
        _version(page["attachment_version"], f"pages[{i}].attachment_version")
        _page_number(page["start_page"], f"pages[{i}].start_page")
        _page_number(page["end_page"], f"pages[{i}].end_page")
        count = page["end_page"] - page["start_page"] + 1
        if count < 1 or count > _MAX_PAGES_PER_REQUEST:
            raise CaptureValidationError(f"pages[{i}] must request 1..10 pages")
        if not isinstance(page["status"], str) or page["status"] not in {"read", "unavailable"}:
            raise CaptureValidationError(f"pages[{i}].status must be read or unavailable")
        _string(page["excerpt"], f"pages[{i}].excerpt", nonempty=False)
        if len(page["excerpt"]) > _MAX_EXCERPT:
            raise CaptureValidationError(f"pages[{i}].excerpt exceeds 1000 characters")
        digest = page["text_sha256"]
        if digest is not None and (not isinstance(digest, str) or not HASH_RE.fullmatch(digest)):
            raise CaptureValidationError(f"pages[{i}].text_sha256 must be lowercase SHA-256 or null")
        if page["status"] == "read":
            if data["metadata_status"] != "read" or digest is None or not page["excerpt"]:
                raise CaptureValidationError(f"pages[{i}] read status requires metadata, digest, and excerpt")
        elif digest is not None or page["excerpt"]:
            raise CaptureValidationError(f"pages[{i}] unavailable status cannot retain text or digest")
    diagnostics = data["diagnostics"]
    if not isinstance(diagnostics, list):
        raise CaptureValidationError("diagnostics must be an array")
    for i, raw in enumerate(diagnostics):
        diagnostic = _object(raw, f"diagnostics[{i}]")
        _exact_keys(diagnostic, DIAGNOSTIC_KEYS, f"diagnostics[{i}]")
        _string(diagnostic["code"], f"diagnostics[{i}].code")
        _string(diagnostic["message"], f"diagnostics[{i}].message")
    return deepcopy(data)


def _unwrap(result: Any) -> Any:
    """Extract MCP JSON/content text without ever treating error text as data."""
    if isinstance(result, dict):
        if result.get("isError") is True:
            raise ValueError("MCP returned an error")
        structured = result.get("structuredContent")
        if isinstance(structured, dict):
            if "result" in structured:
                return _unwrap(structured["result"])
            return structured
        if "result" in result:
            return _unwrap(result["result"])
        content = result.get("content")
        if isinstance(content, list):
            texts = [part.get("text") for part in content
                     if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)]
            if len(texts) != 1:
                raise ValueError("MCP response did not contain exactly one text result")
            return _unwrap(texts[0])
        return result
    if isinstance(result, str):
        text = result.strip()
        if not text:
            raise ValueError("empty MCP response")
        if text.startswith("{") or text.startswith("["):
            try:
                def unique_pairs(pairs):
                    result = {}
                    for key, value in pairs:
                        if key in result:
                            raise ValueError("duplicate JSON response key")
                        result[key] = value
                    return result
                return _unwrap(json.loads(text, object_pairs_hook=unique_pairs))
            except json.JSONDecodeError:
                pass
        return result
    return result


def _metadata_object(value: Any, expected_key: str, expected_library: str) -> dict:
    value = _unwrap(value)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError("metadata was not raw JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("metadata was not an object")
    record = value.get("data", value)
    if not isinstance(record, dict):
        raise ValueError("metadata data was not an object")
    response_keys = [obj[field] for obj in (value, record) for field in ("key", "itemKey")
                     if isinstance(obj, dict) and field in obj]
    if response_keys and any(found != response_keys[0] for found in response_keys[1:]):
        raise ValueError("metadata contained conflicting response keys")
    key = record.get("key", record.get("itemKey"))
    if key != expected_key:
        raise ValueError("metadata key did not match the requested key")
    library = value.get("library", record.get("library"))
    if not isinstance(library, dict):
        raise ValueError("metadata did not identify its library")
    lib_id, lib_type = library.get("id"), library.get("type")
    expected_type, expected_id = expected_library.split("/", 1)
    if lib_id is None or str(lib_id) != expected_id or lib_type != expected_type[:-1]:
        raise ValueError("metadata library did not match the requested library")
    return record


def _page_text(value: Any, attachment_key: str, start: int, end: int) -> tuple[str, str]:
    value = _unwrap(value)
    if isinstance(value, dict):
        value = value.get("text", value.get("markdown", value.get("result")))
    if not isinstance(value, str):
        raise ValueError("page response contained no text")
    item_match = _ITEM_HEADER_RE.search(value)
    range_match = _RANGE_HEADER_RE.search(value)
    if not item_match or item_match.group(1) != attachment_key:
        raise ValueError("page response attachment key did not match")
    if not range_match or (int(range_match.group(1)), int(range_match.group(2))) != (start, end):
        raise ValueError("page response range did not match")
    headings = list(_PAGE_HEADER_RE.finditer(value))
    numbers = [int(match.group(1)) for match in headings]
    if numbers != list(range(start, end + 1)):
        raise ValueError("page response did not contain exactly the requested pages")
    bodies = []
    for index, heading in enumerate(headings):
        body_start = heading.end()
        if body_start < len(value) and value[body_start] == "\n":
            body_start += 1
        body_end = headings[index + 1].start() if index + 1 < len(headings) else len(value)
        body = value[body_start:body_end].strip()
        if not body:
            raise ValueError(f"page {numbers[index]} had no page text")
        bodies.append(body)
    return value, "\n\n".join(bodies)


def _call_read(reader: Callable[[str, dict[str, Any]], Any], operation: str,
               params: dict[str, Any]) -> Any:
    if operation not in READ_OPERATIONS:
        raise ValueError("collector requested a non-allowlisted operation")
    result = dispatch(Path("."), action="inspect", reader=reader,
                      operation=operation, params=params)
    if result["status"] != "PASS":
        raise ValueError("external Zotero MCP read failed")
    return result["result"]


def collect_reading(
    reader: Callable[[str, dict[str, Any]], Any] | None,
    *,
    instance_id: str,
    library_id: str,
    item_key: str,
    pages: list[dict[str, Any]] | None = None,
    collection_key: str | None = None,
    origin: str = "external_mcp",
) -> dict:
    """Collect metadata and bounded selected-page observations via read-only MCP calls."""
    if not isinstance(instance_id, str) or not INSTANCE_RE.fullmatch(instance_id):
        raise ValueError("instance_id must be lowercase hex of length 16..64")
    if not isinstance(library_id, str) or not LIBRARY_RE.fullmatch(library_id):
        raise ValueError("library_id must be users/<integer> or groups/<integer>")
    if not isinstance(item_key, str) or not KEY_RE.fullmatch(item_key):
        raise ValueError("item_key must use eight letters/digits")
    if not isinstance(origin, str) or origin not in {"external_mcp", "synthetic"}:
        raise ValueError("origin must be external_mcp or synthetic")
    if collection_key is not None and (not isinstance(collection_key, str) or not KEY_RE.fullmatch(collection_key)):
        raise ValueError("collection_key must use eight letters/digits or null")
    if reader is None:
        raise ValueError("an external read-only MCP reader is required")
    requested = [] if pages is None else pages
    if not isinstance(requested, list) or len(requested) > _MAX_REQUESTS:
        raise ValueError("pages must contain at most 10 page-range requests")
    for i, page in enumerate(requested):
        if not isinstance(page, dict) or set(page) != {"attachment_key", "start_page", "end_page"}:
            raise ValueError(f"pages[{i}] must contain attachment_key, start_page, end_page")
        if not isinstance(page["attachment_key"], str) or not KEY_RE.fullmatch(page["attachment_key"]):
            raise ValueError(f"pages[{i}].attachment_key must use eight letters/digits")
        _page_number(page["start_page"], f"pages[{i}].start_page")
        _page_number(page["end_page"], f"pages[{i}].end_page")
        if not 1 <= page["end_page"] - page["start_page"] + 1 <= _MAX_PAGES_PER_REQUEST:
            raise ValueError(f"pages[{i}] must request 1..10 pages")

    diagnostics: list[dict[str, str]] = []
    item = {"key": item_key, "version": None, "title": "", "item_type": "", "doi": None}
    metadata_status = "unavailable"
    attachment_versions: dict[str, int | None] = {}
    collection_verified = collection_key is None
    try:
        raw = _call_read(reader, "zotero_get_item_metadata", {"item_key": item_key, "format": "json", "include_abstract": False})
        record = _metadata_object(raw, item_key, library_id)
        title = record.get("title")
        item_type = record.get("itemType", record.get("item_type"))
        if isinstance(title, str) and title.strip() and isinstance(item_type, str) and item_type.strip():
            version = record.get("version")
            if version is not None and (not isinstance(version, int) or isinstance(version, bool) or version < 0):
                raise ValueError("metadata version was invalid")
            doi = normalize_doi(record.get("DOI", record.get("doi")))
            item = {"key": item_key, "version": version, "title": title.strip(),
                    "item_type": item_type.strip(), "doi": doi}
            metadata_status = "read"
            if collection_key is not None:
                collections = record.get("collections")
                if isinstance(collections, list) and all(isinstance(key, str) for key in collections):
                    collection_verified = collection_key in collections
        else:
            diagnostics.append({"code": "metadata_unavailable", "message": "metadata had no nonempty title and item type"})
    except Exception as exc:
        diagnostics.append({"code": "metadata_unavailable", "message": f"metadata could not be read: {type(exc).__name__}"})
        metadata_status = "unavailable"
        item = {"key": item_key, "version": None, "title": "", "item_type": "", "doi": None}
        attachment_versions.clear()

    if collection_key is not None and not collection_verified:
        diagnostics.append({
            "code": "collection_unavailable",
            "message": "selected collection membership could not be confirmed in parent metadata",
        })

    if metadata_status == "read" and collection_verified:
        for raw_page in requested:
            key = raw_page["attachment_key"]
            if key in attachment_versions:
                continue
            try:
                if key == item_key:
                    raise ValueError("attachment key must differ from selected parent item key")
                child = _call_read(reader, "zotero_get_item_metadata", {
                    "item_key": key, "format": "json", "include_abstract": False,
                })
                child_record = _metadata_object(child, key, library_id)
                if child_record.get("parentItem") != item_key:
                    raise ValueError("attachment parentItem did not match selected item")
                if child_record.get("itemType") != "attachment":
                    raise ValueError("selected child was not an attachment")
                content_type = child_record.get("contentType")
                if not isinstance(content_type, str) or content_type.split(";", 1)[0].strip().lower() != "application/pdf":
                    raise ValueError("selected attachment was not a PDF")
                child_version = child_record.get("version")
                if child_version is not None and (not isinstance(child_version, int) or isinstance(child_version, bool) or child_version < 0):
                    raise ValueError("attachment version was invalid")
                attachment_versions[key] = child_version
            except Exception:
                diagnostics.append({"code": "attachment_unavailable", "message": f"attachment {key} could not be bound to selected item"})

    captured_pages = []
    for request in requested:
        key, start, end = request["attachment_key"], request["start_page"], request["end_page"]
        page = {"attachment_key": key, "attachment_version": attachment_versions.get(key),
                "start_page": start, "end_page": end, "status": "unavailable",
                "text_sha256": None, "excerpt": ""}
        if metadata_status == "read" and collection_verified and key in attachment_versions:
            try:
                response = _call_read(reader, "zotero_read_pdf_pages", {
                    "item_key": key, "start_page": start, "end_page": end,
                })
                complete_text, body_text = _page_text(response, key, start, end)
                page.update(status="read", text_sha256=hashlib.sha256(complete_text.encode("utf-8")).hexdigest(),
                            excerpt=body_text[:_MAX_EXCERPT])
            except Exception as exc:
                diagnostics.append({"code": "page_unavailable", "message": f"pages {start}-{end} for {key} unavailable: {type(exc).__name__}"})
        else:
            if not any(d["code"] == "attachment_unavailable" and key in d["message"] for d in diagnostics):
                diagnostics.append({"code": "attachment_unavailable", "message": f"attachment {key} was not bound to the selected item"})
        captured_pages.append(page)

    capture = {"schema_version": 1, "kind": "zotero_reading_capture", "origin": origin,
               "instance_id": instance_id, "library_id": library_id,
               "captured_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
               "item": item, "collection_key": collection_key,
               "metadata_status": metadata_status, "pages": captured_pages,
               "diagnostics": diagnostics}
    return validate_capture(capture)
