"""Portable project contract and conservative initializers."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

PROJECT_SCHEMA_VERSION = 1
PROJECT_CONFIG = "flac3d_project.yaml"
_ID = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")


def _relative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError(f"{field} must be a non-empty relative path")
    p = Path(value.replace("\\", "/"))
    if p.is_absolute() or ":" in value or ".." in p.parts:
        raise ValueError(f"{field} contains an unsafe relative path: {value}")
    return p.as_posix()


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    if os.name == "nt":
        try:
            return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x0400)
        except FileNotFoundError:
            return False
    return False


def _reject_reparse_chain(path: Path) -> None:
    """Reject links in the user-selected initialization path before resolve."""
    current = Path(os.path.abspath(os.fspath(path.expanduser())))
    while True:
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ValueError("refusing to initialize through a symlink or junction")
        parent = current.parent
        if parent == current:
            return
        current = parent


def _scalar(value: str):
    value = value.strip()
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        if value in {"true", "True"}: return True
        if value in {"false", "False"}: return False
        if value in {"null", "Null", "~"}: return None
        if (len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'"):
            return value[1:-1]
        return value


def _limited_yaml(text: str):
    """Parse the deliberately small YAML subset used by project configs.

    JSON is YAML 1.2, so generated files take the safer JSON path.  The
    fallback accepts mappings, list items, and scalar values only.
    """
    lines = [(len(line) - len(line.lstrip(" ")), line.strip())
             for line in text.splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    if not lines: return {}
    if lines[0][0] != 0: raise ValueError("config YAML must start at indentation zero")

    def parse(index, indent):
        if index >= len(lines) or lines[index][0] != indent:
            raise ValueError("invalid config indentation")
        is_list = lines[index][1].startswith("-")
        out = [] if is_list else {}
        while index < len(lines) and lines[index][0] == indent:
            raw = lines[index][1]
            if is_list:
                if not raw.startswith("-"):
                    raise ValueError("mixed mapping and list at one indentation")
                rest = raw[1:].strip()
                if not rest:
                    if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                        raise ValueError("list item requires a value")
                    item, index = parse(index + 1, lines[index + 1][0]); out.append(item); continue
                out.append(_scalar(rest)); index += 1; continue
            if ":" not in raw or raw.startswith(":"):
                raise ValueError("mapping entry must contain a key")
            key, rest = raw.split(":", 1); key = key.strip()
            if not key or key in out: raise ValueError(f"invalid or duplicate config key: {key}")
            if rest.strip(): out[key] = _scalar(rest); index += 1
            else:
                if index + 1 >= len(lines) or lines[index + 1][0] <= indent:
                    raise ValueError(f"missing value for config key: {key}")
                out[key], index = parse(index + 1, lines[index + 1][0])
        return out, index
    result, end = parse(0, 0)
    if end != len(lines): raise ValueError("invalid config indentation")
    return result


def load_config(root: Path) -> dict:
    path = root / PROJECT_CONFIG
    text = path.read_text(encoding="utf-8-sig")
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = _limited_yaml(text)
    if not isinstance(data, dict): raise ValueError("flac3d_project.yaml must contain an object")
    allowed = {"schema_version", "project_id", "domain", "product", "product_version", "entry", "baseline",
               "errors", "decisions", "research_map", "documentation", "execution", "verification",
               "route_policy"}
    extra = sorted(set(data) - allowed)
    if extra: raise ValueError("unknown config fields: " + ", ".join(extra))
    if data.get("schema_version") != PROJECT_SCHEMA_VERSION:
        raise ValueError(f"unsupported FLAC3D project schema_version: {data.get('schema_version')!r}")
    required = ("project_id", "domain", "product", "product_version", "entry", "baseline",
                "errors", "decisions", "research_map", "documentation", "execution", "verification")
    missing = [key for key in required if key not in data]
    if missing: raise ValueError("missing required config fields: " + ", ".join(missing))
    for field in ("domain", "product", "product_version"):
        if not isinstance(data[field], str) or not data[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    # Accept the pre-boundary spelling on read, but normalize all in-memory
    # configuration to the contract spelling used by new files.
    if isinstance(data["product"], str):
        data["product"] = data["product"].casefold()
    if data["product"] not in {"flac3d", "synthetic"}:
        raise ValueError("product must be flac3d or synthetic")
    project_id = data["project_id"]
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ValueError("project_id must match ^[a-z][a-z0-9_-]{1,63}$")
    for field in ("entry", "baseline", "errors", "decisions", "research_map"):
        data[field] = _relative(data[field], field)
    if not isinstance(data["documentation"], dict) or not isinstance(data["execution"], dict):
        raise ValueError("documentation and execution must be objects")
    for field in ("documentation", "execution"):
        allowed_provider_fields = {"provider", "root", "version", "lookup"} if field == "documentation" else {"provider"}
        extra = sorted(set(data[field]) - allowed_provider_fields)
        if extra: raise ValueError(f"unknown {field} fields: " + ", ".join(extra))
        provider = data[field].get("provider")
        if not isinstance(provider, str) or not provider.strip():
            raise ValueError(f"{field}.provider is required")
        if field == "documentation" and "root" in data[field]:
            data[field]["root"] = _relative(data[field]["root"], "documentation.root")
        if field == "documentation" and "version" in data[field] and not isinstance(data[field]["version"], str):
            raise ValueError("documentation.version must be a string")
    if not isinstance(data["verification"], dict):
        raise ValueError("verification must be an object")
    extra = sorted(set(data["verification"]) - {"project_checks"})
    if extra: raise ValueError("unknown verification fields: " + ", ".join(extra))
    checks = data["verification"].get("project_checks")
    if not isinstance(checks, list) or not all(isinstance(x, str) and x.strip() for x in checks):
        raise ValueError("verification.project_checks must be a list of strings")
    route_policy = data.get("route_policy", {})
    if not isinstance(route_policy, dict) or set(route_policy) - {"max_active_routes"}:
        raise ValueError("route_policy must contain only max_active_routes")
    max_active = route_policy.get("max_active_routes", 3)
    if not isinstance(max_active, int) or isinstance(max_active, bool) or not 1 <= max_active <= 3:
        raise ValueError("route_policy.max_active_routes must be an integer from 1 to 3")
    data["route_policy"] = {"max_active_routes": max_active}
    return data


def init_project(target: Path, project_id: str, template: str = "blank", *,
                 product: str = "flac3d", domain: str | None = None) -> Path:
    if not isinstance(project_id, str) or not _ID.fullmatch(project_id):
        raise ValueError("project_id must match ^[a-z][a-z0-9_-]{1,63}$")
    if template not in {"blank", "synthetic"}: raise ValueError("template must be blank or synthetic")
    if product not in {"flac3d", "synthetic"}: raise ValueError("product must be flac3d or synthetic")
    _reject_reparse_chain(target)
    target = target.resolve()
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("refusing to initialize a non-empty directory")
    target.mkdir(parents=True, exist_ok=True)
    files = {"flac3d_project.yaml": {
        "schema_version": 1, "project_id": project_id,
        "domain": domain or ("mining geomechanics" if product == "flac3d" else "synthetic research fixture"),
        "product": product, "product_version": "unknown" if product == "flac3d" else "fixture-1", "entry": "START.md",
        "baseline": "cases/main.dat", "errors": "docs/error-journal.jsonl", "decisions": "docs/decisions.jsonl",
        "research_map": "research/map.json", "documentation": {"provider": "auto"},
        "execution": {"provider": "disabled"}, "verification": {"project_checks": ["entry_exists", "baseline_exists"]},
        "route_policy": {"max_active_routes": 3}},
        "START.md": "# Portable %s project\n\nThis is a %s template. Define an authorized model and validation plan before execution.\n" % (product.upper(), template),
        "cases/main.dat": "",
        "docs/error-journal.jsonl": "", "docs/decisions.jsonl": "",
        "research/map.json": "{\"schema_version\":1,\"type\":\"ResearchMap\",\"project_id\":\"%s\",\"nodes\":[],\"edges\":[]}\n" % project_id}
    for relative, content in files.items():
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists(): raise ValueError(f"refusing to overwrite existing file: {relative}")
        path.write_text(json.dumps(content, ensure_ascii=False, indent=2) + "\n" if relative.endswith(".yaml") else content, encoding="utf-8", newline="\n")
    return target


def init_synthetic_project(target: Path, project_id: str) -> Path:
    """Create a domain-neutral fixture project for extension acceptance."""
    return init_project(target, project_id, "synthetic", product="synthetic")
