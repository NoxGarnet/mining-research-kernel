"""Explicitly selected, read-only Zotero MCP stdio Host connection."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess  # Preserve provider patch targets while transport lives in the kernel.
from typing import Any

from mining_research_kernel.mcp_transport import (
    MCPHostError as ZoteroHostError,
    MCPStdioReader,
    _MAX_CONFIG,
    _absolute_path,
    _unique_object,
)
from mining_research_kernel.artifacts import _reject_reparse_chain
from mining_research_kernel.zotero_reading import INSTANCE_RE, LIBRARY_RE
from adapters.zotero_mcp_readonly import READ_OPERATIONS

def validate_registration(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("registration must be a JSON object")
    required = {"schema_version", "kind", "instance_id", "library_id", "command", "args"}
    optional = {"cwd", "timeout_seconds"}
    if set(value) - required - optional or required - set(value):
        raise ValueError("registration has missing or unknown fields")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if value["kind"] != "zotero_stdio":
        raise ValueError("kind must be zotero_stdio")
    if not isinstance(value["instance_id"], str) or not INSTANCE_RE.fullmatch(value["instance_id"]):
        raise ValueError("instance_id must be lowercase hex of length 16..64")
    if not isinstance(value["library_id"], str) or not LIBRARY_RE.fullmatch(value["library_id"]):
        raise ValueError("library_id must be users/<integer> or groups/<integer>")
    command = _absolute_path(value["command"], "command")
    args = value["args"]
    if not isinstance(args, list) or any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise ValueError("args must be an array of strings")
    if "cwd" in value and value["cwd"] is None:
        raise ValueError("cwd must be an absolute path when supplied")
    cwd = _absolute_path(value["cwd"], "cwd", directory=True) if "cwd" in value else None
    timeout = value.get("timeout_seconds", 30)
    if type(timeout) is not int or not 1 <= timeout <= 60:
        raise ValueError("timeout_seconds must be an integer from 1 to 60")
    normalized = {"schema_version": 1, "kind": "zotero_stdio", "instance_id": value["instance_id"],
                 "library_id": value["library_id"], "command": command, "args": list(args),
                 "timeout_seconds": timeout}
    if cwd is not None:
        normalized["cwd"] = cwd
    return normalized


def load_registration(path: str | Path) -> dict[str, Any]:
    selected = Path(path).expanduser()
    if not selected.is_absolute() or not selected.is_file():
        raise ValueError("registration path must be an existing absolute regular file")
    _reject_reparse_chain(selected, "registration path")
    try:
        with selected.open("rb") as stream:
            raw = stream.read(_MAX_CONFIG + 1)
    except OSError as exc:
        raise ValueError("registration could not be read") from exc
    if len(raw) > _MAX_CONFIG:
        raise ValueError("registration exceeds the 32768-byte limit")
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("invalid JSON number")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("registration is not strict UTF-8 JSON") from exc
    return validate_registration(data)


class ZoteroReader(MCPStdioReader):
    """Short-lived Zotero reader constrained to the provider read allowlist."""

    def __init__(self, registration: dict[str, Any]):
        super().__init__(validate_registration(registration), READ_OPERATIONS)


__all__ = ["ZoteroHostError", "ZoteroReader", "load_registration", "validate_registration"]
