"""Read bounded documentation passages through an allowlisted Itasca MCP profile."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from typing import Any

from mining_research_kernel.mcp_transport import (
    MCPHostError,
    MCPStdioReader,
    _MAX_CONFIG,
    _absolute_path,
    _unique_object,
)
from mining_research_kernel.artifacts import _reject_reparse_chain

ITASCA_READ_OPERATIONS = frozenset({
    "itasca_query_command",
    "itasca_browse_commands",
    "itasca_browse_reference",
})
MAX_TRANSIENT_CHARS = 12_000
MAX_SAVED_CHARS = 2_000
MAX_QUERY_RESULTS = 20
_VERSION = re.compile(r"^\d+(?:\.\d+){1,2}$")


def validate_registration(value: Any) -> dict[str, Any]:
    """Validate the explicit Itasca Host profile without retaining paths in results."""
    required = {"schema_version", "kind", "instance_id", "command", "args"}
    optional = {"cwd", "timeout_seconds"}
    if not isinstance(value, dict) or set(value) - required - optional or required - set(value):
        raise ValueError("registration_fields_invalid")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("registration_schema_version_invalid")
    if value["kind"] != "itasca_stdio":
        raise ValueError("registration_kind_invalid")
    if not isinstance(value["instance_id"], str) or not re.fullmatch(r"[0-9a-f]{16,64}", value["instance_id"]):
        raise ValueError("instance_id_invalid")
    command = _absolute_path(value["command"], "command")
    args = value["args"]
    if not isinstance(args, list) or any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise ValueError("args_invalid")
    timeout = value.get("timeout_seconds", 30)
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("timeout_invalid")
    profile = {
        "schema_version": 1,
        "kind": "itasca_stdio",
        "instance_id": value["instance_id"],
        "command": command,
        "args": list(args),
        "timeout_seconds": timeout,
    }
    if "cwd" in value:
        profile["cwd"] = _absolute_path(value["cwd"], "cwd", directory=True)
    return profile


def load_registration(registration: Any) -> dict[str, Any]:
    """Load a strict JSON profile, capped like the existing Host profiles."""
    if isinstance(registration, dict):
        raw = registration
    else:
        path = Path(registration).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise ValueError("registration_path_invalid")
        _reject_reparse_chain(path, "registration path")
        try:
            with path.open("rb") as stream:
                data = stream.read(_MAX_CONFIG + 1)
        except OSError as exc:
            raise ValueError("registration_unreadable") from exc
        if len(data) > _MAX_CONFIG:
            raise ValueError("registration_too_large")
        try:
            raw = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object,
                             parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid_json_number")))
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise ValueError("registration_invalid_json") from exc
    try:
        encoded_size = len(json.dumps(raw, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError("registration_invalid_json") from exc
    if encoded_size > _MAX_CONFIG:
        raise ValueError("registration_too_large")
    return validate_registration(raw)


class ItascaReader(MCPStdioReader):
    """Read-only Itasca reader with its own fixed documentation allowlist."""

    def __init__(self, profile: dict[str, Any]):
        super().__init__(validate_registration(profile), ITASCA_READ_OPERATIONS)

    def _load_tools(self) -> None:
        cursor = None
        cursors: set[str] = set()
        found: set[str] = set()
        for _ in range(100):
            page = self._rpc("tools/list", {} if cursor is None else {"cursor": cursor})
            tools = page.get("tools")
            if not isinstance(tools, list):
                raise MCPHostError("malformed_tool_list")
            found.update(item["name"] for item in tools
                         if isinstance(item, dict) and isinstance(item.get("name"), str))
            cursor = page.get("nextCursor")
            if cursor is None:
                self._tools = found & ITASCA_READ_OPERATIONS
                return
            if not isinstance(cursor, str) or not cursor or cursor in cursors:
                raise MCPHostError("malformed_tool_cursor")
            cursors.add(cursor)
        raise MCPHostError("tool_list_page_limit")

    def __call__(self, operation: str, params: dict[str, Any]) -> dict[str, Any]:
        if operation not in ITASCA_READ_OPERATIONS:
            raise MCPHostError("operation_not_allowed")
        if operation not in self._tools:
            raise MCPHostError("required_read_tool_missing")
        try:
            result = self._rpc("tools/call", {"name": operation, "arguments": params})
            self.tool_call_started = True
            return result
        except MCPHostError as exc:
            self.tool_call_started = True
            exc.tool_call_started = True
            raise


def call_tool(registration: Any, operation: str, params: dict[str, Any], allowlist=None) -> dict[str, Any]:
    allowed = ITASCA_READ_OPERATIONS if allowlist is None else frozenset(allowlist) & ITASCA_READ_OPERATIONS
    if operation not in allowed:
        raise MCPHostError("operation_not_allowed")
    profile = load_registration(registration)
    with ItascaReader(profile) as reader:
        return reader(operation, params)


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{name}_required")
    return value.strip()


def _failure(reason: str, software: Any, version: Any) -> dict[str, Any]:
    return {
        "status": "CANNOT_READ",
        "stop_reason": reason,
        "coverage_scope": "mcp_documentation_reading_only",
        "citation": {
            "source_id": "itasca_mcp.community", "product": software, "document_family": version,
            "document_build": None, "page": None, "anchor": None,
            "trust_class": "community_mcp", "sha256_body": None,
            "official_source_verified": False, "requested_version": version,
            "returned_version": None, "requested_software": software,
        },
        "passages": [],
        "reading_texts": [],
        "uncovered": ["parameter_combinations", "full_script", "numerical_validity",
                      "engineering_suitability", "official_source_identity_unverified"],
        "applicability_status": "INSUFFICIENT",
        "_query_performed": False,
    }


def _response_value(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or raw.get("isError") is True:
        return None
    value = raw.get("structuredContent")
    if isinstance(value, dict):
        return value
    for block in raw.get("content", []):
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            try:
                decoded = json.loads(block["text"])
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(decoded, dict):
                return decoded
    return None


def _entry_text(entry: dict[str, Any]) -> str:
    doc = entry.get("doc")
    if isinstance(doc, dict):
        content = {key: value for key, value in doc.items() if value not in (None, "", [], {})}
        content.pop("source", None)
    else:
        content = {key: entry.get(key) for key in
                   ("path", "name", "syntax", "short_description", "description")
                   if entry.get(key) not in (None, "", [], {})}
    if not content:
        return ""
    return json.dumps(content, ensure_ascii=False, sort_keys=True, indent=2)


def query_itasca(
    registration: Any,
    *,
    operation: str,
    software: str,
    version: str,
    query: str | None = None,
    command: str | None = None,
    topic: str | None = None,
    limit: int = 10,
    max_reading_chars: int = MAX_TRANSIENT_CHARS,
) -> dict[str, Any]:
    """Call one of the three documentation tools and normalize bounded output."""
    result = _failure("invalid_request", software, version)
    if not isinstance(operation, str) or operation not in ITASCA_READ_OPERATIONS:
        result["stop_reason"] = "operation_not_allowed"
        return result
    try:
        software = _nonempty(software, "software")
        version = _nonempty(version, "version")
        if not _VERSION.fullmatch(version):
            raise ValueError("version_invalid")
        if type(max_reading_chars) is not int or max_reading_chars < 1:
            raise ValueError("max_reading_chars_invalid")
        max_reading_chars = min(max_reading_chars, MAX_TRANSIENT_CHARS)
        if operation == "itasca_query_command":
            query = _nonempty(query, "query")
            if len(query) > 2000:
                raise ValueError("query_too_long")
            if type(limit) is not int or not 1 <= limit <= MAX_QUERY_RESULTS:
                raise ValueError("limit_invalid")
        elif operation == "itasca_browse_commands":
            if command is not None and (not isinstance(command, str) or len(command) > 2000
                                        or any(ord(c) < 32 or ord(c) == 127 for c in command)):
                raise ValueError("command_invalid")
        elif operation == "itasca_browse_reference":
            if topic is not None and (not isinstance(topic, str) or len(topic) > 2000
                                      or any(ord(c) < 32 or ord(c) == 127 for c in topic)):
                raise ValueError("topic_invalid")
    except ValueError as exc:
        result["stop_reason"] = str(exc)
        return result

    params: dict[str, Any] = {"software": software, "version": version}
    if operation == "itasca_query_command":
        params.update(query=query, limit=limit)
    elif operation == "itasca_browse_commands" and command is not None:
        params["command"] = command
    elif operation == "itasca_browse_reference" and topic is not None:
        params["topic"] = topic

    try:
        profile = load_registration(registration)
    except (OSError, TypeError, ValueError) as exc:
        result["stop_reason"] = str(exc) if str(exc).startswith("registration_") else "registration_invalid"
        return result
    try:
        raw = call_tool(profile, operation, params, ITASCA_READ_OPERATIONS)
    except (MCPHostError, ValueError) as exc:
        result["_query_performed"] = bool(getattr(exc, "tool_call_started", False))
        result["stop_reason"] = getattr(exc, "code", "registration_invalid")
        return result
    result["_query_performed"] = True

    value = _response_value(raw)
    if value is None:
        result["_query_performed"] = True
        result["stop_reason"] = "mcp_tool_error" if isinstance(raw, dict) and raw.get("isError") else "malformed_response"
        return result
    if value.get("ok") is not True or not isinstance(value.get("data"), dict):
        error = value.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        result["stop_reason"] = "mcp_business_error" + (f":{code}" if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.-]{1,80}", code) else "")
        return result

    data = value["data"]
    summary = data.get("summary") if isinstance(data.get("summary"), dict) else {}
    returned_version = summary.get("version")
    returned_software = summary.get("software")
    result["citation"].update(returned_version=returned_version)
    result["citation"]["product"] = software
    entries = data.get("entries")
    if not isinstance(entries, list):
        result["stop_reason"] = "malformed_response"
        return result
    if operation == "itasca_query_command":
        entries = entries[:limit]

    discovery = (operation == "itasca_query_command"
                 or operation == "itasca_browse_commands" and not (command and command.strip())
                 or operation == "itasca_browse_reference" and not (topic and topic.strip()))
    total_transient = 0
    total_saved = 0
    passages: list[dict[str, Any]] = []
    reading_texts: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        passage_text = _entry_text(entry)
        if not passage_text:
            continue
        remaining = max_reading_chars - total_transient
        if remaining <= 0:
            break
        transient_text = passage_text[:remaining]
        transient_truncated = len(transient_text) < len(passage_text)
        locator = (entry.get("command") or entry.get("path") or entry.get("item")
                   or entry.get("category") or topic or command or operation)
        transient = {
            "text": transient_text,
            "truncated": transient_truncated,
            "original_char_count": len(passage_text),
            "locator": locator,
        }
        reading_texts.append(transient)
        total_transient += len(transient_text)
        saved_room = MAX_SAVED_CHARS - total_saved
        if saved_room <= 0:
            continue
        saved_text = transient_text[:saved_room]
        total_saved += len(saved_text)
        passages.append({
            **transient,
            "text": saved_text,
            "truncated": transient_truncated or len(saved_text) < len(transient_text),
            "sha256": hashlib.sha256(saved_text.encode("utf-8")).hexdigest(),
            "heading": entry.get("command") or entry.get("item") or entry.get("category"),
            "upstream_source": _safe_source_locator(entry),
            "upstream_source_verified": False,
        })

    version_matches = returned_version == version
    software_matches = returned_software is None or str(returned_software).casefold() == software.casefold()
    if operation == "itasca_browse_reference":
        result["uncovered"].append("reference_version_applicability_unverified")
    if not version_matches:
        result["uncovered"].append("mcp_version_unverified")
    if not software_matches:
        result["uncovered"].append("mcp_software_mismatch")
    result["uncovered"].append("community_source_not_officially_verified")
    status = "DISCOVERY_ONLY" if discovery else "READ_WITH_LIMITS" if passages else "CANNOT_READ"
    insufficient = not version_matches or not software_matches or operation == "itasca_browse_reference"
    available_char_count = sum(len(_entry_text(item)) for item in entries if isinstance(item, dict))
    result["reading_truncated"] = available_char_count > total_transient
    result["saved_text_truncated"] = total_saved < total_transient
    result.update({
        "status": status,
        "stop_reason": "bounded_mcp_discovery" if discovery and passages
                       else "discovery_no_matches" if discovery
                       else "bounded_mcp_read" if passages else "no_documentation_passages",
        "coverage_scope": "discovery_only" if discovery else "mcp_documentation_reading_only",
        "citation": {**result["citation"], "page": topic, "anchor": command},
        "passages": passages,
        "reading_texts": reading_texts,
        "applicability_status": "INSUFFICIENT" if insufficient else "LIMITED",
        "diagnostics": ["community_source_not_officially_verified"] +
                       (["returned_version_mismatch_or_missing"] if not version_matches else []) +
                       (["returned_software_mismatch"] if not software_matches else []) +
                       (["reference_version_applicability_unverified"] if operation == "itasca_browse_reference" else []),
    })
    return result


def _safe_source_locator(entry: dict[str, Any]) -> str | None:
    """Retain a community locator as provenance without following it."""
    doc = entry.get("doc")
    source = entry.get("sourceURL")
    if not isinstance(source, str) and isinstance(doc, dict):
        source = doc.get("source")
    if not isinstance(source, str):
        return None
    try:
        parsed = urlsplit(source)
    except ValueError:
        return None
    if (len(source) > 2048 or parsed.scheme.casefold() not in {"http", "https"}
            or not parsed.netloc or parsed.username is not None or parsed.password is not None):
        return None
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


__all__ = ["query_itasca"]
