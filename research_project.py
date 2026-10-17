"""Optional, domain-neutral configuration for persistent research records."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from mining_research_kernel.artifacts import _reject_reparse_chain

RESEARCH_CONFIG = "research_project.json"
LEGACY_CONFIG = "flac3d_project.yaml"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)


def _relative(value: Any, field: str) -> str:
    if (not isinstance(value, str) or not value or "\x00" in value or
            "\\" in value or ":" in value):
        raise ValueError(f"{field} must be a safe project-relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{field} must be a safe project-relative path")
    return path.as_posix()


def _read_neutral(root: Path) -> dict[str, Any]:
    config_path = root / RESEARCH_CONFIG
    _reject_reparse_chain(config_path, "research project configuration")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {RESEARCH_CONFIG}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{RESEARCH_CONFIG} must contain an object")
    extra = set(data) - {"schema_version", "project_id", "entry", "research_map", "route_policy"}
    if extra:
        raise ValueError("unknown research project fields: " + ", ".join(sorted(extra)))
    if data.get("schema_version") != 1 or isinstance(data.get("schema_version"), bool):
        raise ValueError("research project schema_version must be 1")
    project_id = data.get("project_id")
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ValueError("project_id must match ASCII [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    entry = _relative(data.get("entry", "START.md"), "entry")
    research_map = _relative(data.get("research_map", "research/map.json"), "research_map")
    policy = data.get("route_policy", {})
    if not isinstance(policy, dict) or set(policy) - {"max_active_routes"}:
        raise ValueError("route_policy must contain only max_active_routes")
    max_active = policy.get("max_active_routes", 3)
    if not isinstance(max_active, int) or isinstance(max_active, bool) or not 1 <= max_active <= 3:
        raise ValueError("route_policy.max_active_routes must be an integer from 1 to 3")
    for relative, label in ((entry, "entry"), (research_map, "research_map")):
        _reject_reparse_chain(root / relative, f"research project {label}")
    return {
        "schema_version": 1,
        "project_id": project_id,
        "domain": "mining research",
        "product": "research",
        "product_version": "unknown",
        "entry": entry,
        "research_map": research_map,
        "execution": {"provider": "disabled"},
        "route_policy": {"max_active_routes": max_active},
    }


def load_config(root: str | Path) -> dict[str, Any]:
    """Load the neutral contract, or delegate legacy validation unchanged."""
    raw_root = Path(root).expanduser()
    _reject_reparse_chain(raw_root, "project root")
    resolved = raw_root.resolve()
    if not resolved.is_dir():
        raise ValueError("project root must be an existing directory")
    neutral = resolved / RESEARCH_CONFIG
    legacy = resolved / LEGACY_CONFIG
    _reject_reparse_chain(neutral, "research project configuration")
    _reject_reparse_chain(legacy, "legacy project configuration")
    has_neutral, has_legacy = neutral.exists(), legacy.exists()
    if has_neutral and has_legacy:
        raise ValueError("both research_project.json and flac3d_project.yaml exist; resolve explicitly")
    if has_neutral:
        return _read_neutral(resolved)
    if has_legacy:
        try:
            from flac3d_project import load_config as load_legacy_config
            return load_legacy_config(resolved)
        except Exception as exc:
            raise ValueError(f"invalid legacy project config: {exc}") from exc
    raise ValueError("missing project config: research_project.json or flac3d_project.yaml")


def enable_research(project_root: str | Path, project_id: str) -> dict[str, Any]:
    """Add exactly one neutral config to an existing project, without scaffolding."""
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ValueError("project_id must match ASCII [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    raw_root = Path(project_root).expanduser()
    _reject_reparse_chain(raw_root, "project root")
    root = raw_root.resolve()
    if not root.is_dir():
        raise ValueError("project root must be an existing directory")
    neutral, legacy = root / RESEARCH_CONFIG, root / LEGACY_CONFIG
    _reject_reparse_chain(neutral, "research project configuration")
    _reject_reparse_chain(legacy, "legacy project configuration")
    if neutral.exists() and legacy.exists():
        raise ValueError("both research_project.json and flac3d_project.yaml exist; resolve explicitly")
    if legacy.exists():
        config = load_config(root)
        return {"status": "legacy_present", "config_path": LEGACY_CONFIG,
                "project_id": config["project_id"], "requested_project_id": project_id,
                "project_preserved": True}
    if neutral.exists():
        config = load_config(root)
        if config["project_id"] != project_id:
            raise ValueError("research project is already enabled with a different project_id")
        return {"status": "already_enabled", "config_path": RESEARCH_CONFIG,
                "project_id": project_id, "project_preserved": True}
    records = root / "research" / "records"
    _reject_reparse_chain(records, "research records")
    if records.exists():
        raise ValueError("research/records exists without a project config; refusing to claim existing records")
    _reject_reparse_chain(root / "START.md", "research project entry")
    _reject_reparse_chain(root / "research" / "map.json", "research project map")
    payload = {"schema_version": 1, "project_id": project_id}
    # Exclusive creation prevents overwriting a concurrent or pre-existing file.
    try:
        with neutral.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise ValueError("research_project.json appeared during enablement; refusing to overwrite") from exc
    _read_neutral(root)
    return {"status": "enabled", "config_path": RESEARCH_CONFIG,
            "project_id": project_id, "project_preserved": True}


__all__ = ["enable_research", "load_config"]
