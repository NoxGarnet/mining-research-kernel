"""Minimal read-only Zotero MCP source adapter.

The kernel does not own MCP transport or credentials.  A caller may inject a
reader callable for one explicitly allowed operation; without one, inspection
degrades to CANNOT_VERIFY.  No write operation is represented by this module.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable


READ_OPERATIONS = frozenset({
    "zotero_get_collections",
    "zotero_get_collection_items",
    "zotero_get_item_metadata",
    "zotero_get_item_children",
    "zotero_get_item_fulltext",
    "zotero_search_items",
    "zotero_read_pdf_pages",
})


class FulltextUnavailableError(RuntimeError):
    """The selected item has no readable full text."""


class ItemReadError(RuntimeError):
    """One selected Zotero item could not be read."""


def _diagnostic(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _mcp_error(result: Any) -> bool:
    """Recognize explicit MCP errors without scanning returned article text."""
    if isinstance(result, str):
        if re.search(r"(?m)^# PDF Pages \d+-\d+ of PDF\s*$", result):
            return False
        text = re.sub(r"^# Zotero Collections\s*\r?\n\s*", "", result, count=1)
        return bool(re.match(r"^\s*(?:Error(?: fetching [^\r\n:]+)?|Exception|Failed)\s*:", text, re.I))
    if not isinstance(result, dict):
        return False
    if result.get("isError") is True:
        return True
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and _mcp_error(structured):
        return True
    if "result" in result and _mcp_error(result["result"]):
        return True
    content = result.get("content")
    if not isinstance(content, list):
        return False
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            continue
        text = part.get("text")
        if not isinstance(text, str):
            continue
        # A PDF payload has an explicit page envelope; text inside it is article
        # content and must never be interpreted as an MCP transport error.
        if re.search(r"(?m)^# PDF Pages \d+-\d+ of PDF\s*$", text):
            continue
        text = re.sub(r"^# Zotero Collections\s*\r?\n\s*", "", text, count=1)
        if re.match(r"^\s*(?:Error(?: fetching [^\r\n:]+)?|Exception|Failed)\s*:", text, re.I):
            return True
    return False


def _base(action: str, status: str, diagnostics: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "extension_id": "zotero_mcp_readonly",
        "kind": "source",
        "capabilities": ["discover", "inspect", "read_only"],
        "action": action,
        "status": status,
        "transport": "external_codex_mcp",
        "allowed_operations": sorted(READ_OPERATIONS),
        "diagnostics": diagnostics,
    }


def dispatch(
    workspace: Path,
    *,
    action: str = "discover",
    reader: Callable[[str, dict[str, Any]], Any] | None = None,
    operation: str | None = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Discover or inspect the source without acquiring write capability."""
    del workspace  # Registry compatibility; the live source is host-local.
    if action == "discover":
        return _base("discover", "REGISTERED_READ_ONLY", [])
    if action != "inspect":
        raise ValueError(f"unsupported source action: {action}")
    if operation is not None and operation not in READ_OPERATIONS:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("operation_not_allowed", f"read-only source rejects operation: {operation}"),
        ])
    if reader is None:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("extension_not_running", "no external Zotero MCP reader was supplied"),
        ])
    if operation is None:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("missing_operation", "inspect requires one allowed read operation"),
        ])

    try:
        result = reader(operation, dict(params or {}))
        if _mcp_error(result):
            return _base("inspect", "CANNOT_VERIFY", [
                _diagnostic("source_read_failed", "external Zotero MCP returned an error response"),
            ])
    except ConnectionError as exc:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("zotero_closed", str(exc) or "Zotero source is unavailable"),
        ])
    except PermissionError as exc:
        code = "local_api_403" if "403" in str(exc) else "local_api_denied"
        return _base("inspect", "CANNOT_VERIFY", [_diagnostic(code, str(exc))])
    except FulltextUnavailableError as exc:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("fulltext_unavailable", str(exc)),
        ])
    except ItemReadError as exc:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("item_read_failed", str(exc)),
        ])
    except Exception as exc:
        return _base("inspect", "CANNOT_VERIFY", [
            _diagnostic("source_read_failed", f"{type(exc).__name__}: {exc}"),
        ])

    output = _base("inspect", "PASS", [])
    output["operation"] = operation
    output["result"] = result
    return output
