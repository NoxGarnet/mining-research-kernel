"""Small generic project configuration reads used by kernel services."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def load_route_policy(project_root: str | Path) -> dict[str, Any]:
    """Read only the generic route policy without importing a domain adapter.

    Project initialisation currently writes JSON with a ``.yaml`` filename.
    The small fallback accepts the one nested YAML scalar needed by the route
    service so a hand-written config remains usable without a YAML dependency.
    """
    path = Path(project_root).resolve() / "flac3d_project.yaml"
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
