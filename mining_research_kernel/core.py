"""Generic filesystem and registry orchestration services."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .interfaces import RegistryView

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
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_record(record: dict, kind: str | None = None, workspace: Path | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(record, dict):
        return ["record must be an object"]
    if record.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"unsupported schema_version: {record.get('schema_version')!r}")
    declared_type = record.get("type") if "type" in record else None
    has_declared_type = "type" in record

    def supported_type(value: Any, label: str) -> bool:
        if not isinstance(value, str):
            errors.append(f"{label} must be a string")
            return False
        if not value.strip():
            errors.append(f"{label} must be a non-empty string")
            return False
        if value not in ALLOWED_TYPES:
            errors.append(f"unsupported {label}: {value!r}")
            return False
        return True

    declared_is_supported = False
    if has_declared_type:
        declared_is_supported = supported_type(declared_type, "record type")
    elif kind is None:
        errors.append("missing record type")

    explicit_is_supported = kind is None
    if kind is not None:
        explicit_is_supported = supported_type(kind, "kind")

    if (kind is not None and declared_is_supported and explicit_is_supported
            and declared_type != kind):
        errors.append(f"expected type {kind}")

    required = {
        "Project": ("project_id", "domain", "project_type", "authority_root", "entry", "status", "status_scope", "known_limits", "verification_gates"),
        "Asset": ("asset_id", "project_id", "path", "asset_type", "authority", "verification_status"),
        "Tool": ("tool_id", "name", "read_only"),
        "Run": ("run_id", "status", "current_stage", "stages", "history"),
        "Verification": ("gate_id", "status", "scope"),
    }
    target = None
    if declared_is_supported and (kind is None or explicit_is_supported and declared_type == kind):
        target = declared_type
    elif not has_declared_type and explicit_is_supported and kind is not None:
        target = kind
    if target in required:
        for key in required[target]:
            if key not in record:
                errors.append(f"missing {key}")
    if target == "Project":
        for key in ("assets", "tools", "verification_gates"):
            if key in record and not isinstance(record[key], list):
                errors.append(f"{key} must be a list")
        if "source_paths" in record:
            if not isinstance(record["source_paths"], list):
                errors.append("source_paths must be a list")
            elif workspace is not None:
                for relative in record["source_paths"]:
                    if not isinstance(relative, str):
                        errors.append("source_paths entries must be strings")
                        continue
                    try:
                        if not safe_path(workspace, relative).exists():
                            errors.append(f"missing source_path: {relative}")
                    except ValueError as exc:
                        errors.append(str(exc))
        if isinstance(record.get("verification_gates"), list):
            for index, gate in enumerate(record["verification_gates"]):
                if not isinstance(gate, dict):
                    errors.append(f"verification_gates[{index}] must be an object")
                    continue
                for key in ("gate_id", "status"):
                    if key not in gate:
                        errors.append(f"verification_gates[{index}] missing {key}")
    return errors


def asset(project_id: str, asset_id: str, path: str, asset_type: str,
          authority: str = "authoritative", verification_status: str = "CANNOT_VERIFY",
          source: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": 1, "type": "Asset", "asset_id": asset_id,
        "project_id": project_id, "path": path, "asset_type": asset_type,
        "authority": authority, "verification_status": verification_status,
        "source": source or "read-only discovery", "sha256": None, "known_limits": [],
    }


def discover_all(workspace: Path, registry: RegistryView) -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for extension in registry.by_kind("project"):
        try:
            projects.append(registry.resolve(extension)(workspace))
        except Exception as exc:
            projects.append({"extension_id": extension.extension_id, "kind": extension.kind,
                             "diagnostics": [f"extension {extension.extension_id} failed: {type(exc).__name__}: {exc}"]})
    return projects


def discover_sources(workspace: Path, registry: RegistryView) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for extension in registry.by_kind("source"):
        try:
            sources.append(registry.resolve(extension)(workspace, action="discover"))
        except Exception as exc:
            sources.append({"extension_id": extension.extension_id, "kind": extension.kind,
                            "status": "CANNOT_VERIFY", "diagnostics": [{
                                "code": "source_discovery_failed",
                                "message": f"{type(exc).__name__}: {exc}",
                            }]})
    return sources


def inspect_source(workspace: Path, source_id: str, registry: RegistryView,
                   *, reader=None, operation=None, params=None) -> dict[str, Any]:
    try:
        extension = registry.record_for(source_id, kind="source")
    except Exception:
        return {"extension_id": source_id, "kind": "source", "status": "CANNOT_VERIFY",
                "diagnostics": [{"code": "unknown_source", "message": f"unknown source: {source_id}"}]}
    try:
        return registry.resolve(extension)(workspace, action="inspect", reader=reader,
                                           operation=operation, params=params)
    except Exception as exc:
        return {"extension_id": extension.extension_id, "kind": extension.kind,
                "status": "CANNOT_VERIFY", "diagnostics": [{
                    "code": "source_inspection_failed",
                    "message": f"{type(exc).__name__}: {exc}",
                }]}
