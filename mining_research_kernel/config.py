"""Small generic project configuration reads used by kernel services."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mining_research_kernel.artifacts import _reject_reparse_chain


def load_route_policy(project_root: str | Path) -> dict[str, Any]:
    """Read only the generic route policy without importing a domain adapter.

    Project initialisation currently writes JSON with a ``.yaml`` filename.
    The small fallback accepts the one nested YAML scalar needed by the route
    service so a hand-written config remains usable without a YAML dependency.
    """
    root = Path(project_root).expanduser()
    _reject_reparse_chain(root, "project root")
    root = root.resolve()
    neutral = root / "research_project.json"
    legacy = root / "flac3d_project.yaml"
    _reject_reparse_chain(neutral, "research project configuration")
    _reject_reparse_chain(legacy, "legacy project configuration")
    if neutral.exists() and legacy.exists():
        raise ValueError("both research_project.json and flac3d_project.yaml exist; resolve explicitly")
    if neutral.exists():
        from research_project import load_config
        return dict(load_config(root).get("route_policy", {}))
    path = legacy
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read project configuration: {exc}") from exc
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"(?m)^\s*route_policy:\s*\n\s+max_active_routes:\s*([0-9]+)\s*$", text)
        data = {"route_policy": {"max_active_routes": int(match.group(1))}} if match else {}
    if not isinstance(data, dict):
        raise ValueError("project configuration must contain an object")
    policy = data.get("route_policy", {})
    if not isinstance(policy, dict):
        raise ValueError("route_policy must be an object")
    return dict(policy)


__all__ = ["load_route_policy"]
