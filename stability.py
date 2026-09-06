"""Read-only stability checks and deterministic regression helpers."""
from __future__ import annotations
import hashlib, json, re, subprocess, sys, time
import os
if os.name == "nt":
    import ctypes
    import msvcrt
else:
    ctypes = None
    msvcrt = None
from pathlib import Path
from typing import Any
from mining_research_kernel.artifacts import ensure_output_directory

SCHEMA_VERSION = 1
VOLATILE_FIELDS = {"at", "created_at", "updated_at", "last_verified", "exported_at"}
STABILITY_ROOT = Path(__file__).resolve().parent
DEFAULT_COMMAND_TIMEOUT = 30.0
MAX_COMMAND_TIMEOUT = 120.0
_REGISTERED_STABILITY_CHECKS = (
    (str(Path(sys.executable).resolve()), "-B", "-c",
     "from pathlib import Path; [compile(p.read_text(encoding='utf-8-sig'), str(p), 'exec') for p in Path('.').rglob('*.py')]"),
)

def canonical(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: canonical(v) for k, v in sorted(value.items()) if k not in VOLATILE_FIELDS}
    if isinstance(value, list):
        return [canonical(v) for v in value]
    return value

def canonical_json(value: Any) -> str:
    return json.dumps(canonical(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

def _walk(value: Any, where: str = "root"):
    if isinstance(value, dict):
        yield value, where
        for key, child in value.items():
            yield from _walk(child, f"{where}.{key}")
    elif isinstance(value, list):
        for i, child in enumerate(value):
            yield from _walk(child, f"{where}[{i}]")


def _workspace_candidate(root: Path, value: Any) -> tuple[Path | None, str | None]:
    if not isinstance(value, str) or not value:
        return None, "invalid"
    normalized = value.replace("\\", "/")
    relative = Path(normalized)
    if (relative.is_absolute() or normalized.startswith(("/", "//", "file:"))
            or re.match(r"^[A-Za-z]:", normalized) or ".." in relative.parts):
        return None, "unsafe"
    try:
        candidate = (root / relative).resolve()
    except (OSError, RuntimeError):
        return None, "unsafe"
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, "unsafe"
    return candidate, None


def _windows_handle_path(descriptor: int) -> Path | None:
    if os.name != "nt":
        return None
    handle = msvcrt.get_osfhandle(descriptor)
    buffer = ctypes.create_unicode_buffer(32768)
    length = ctypes.windll.kernel32.GetFinalPathNameByHandleW(
        ctypes.c_void_p(handle), buffer, len(buffer), 0
    )
    if not length or length >= len(buffer):
        raise OSError("could not resolve the opened file handle")
    value = buffer.value
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return Path(value)


def _read_verified_bytes(root: Path, candidate: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(candidate, flags)
    try:
        actual = _windows_handle_path(descriptor)
        if actual is not None:
            actual = actual.resolve()
            try:
                actual.relative_to(root)
            except ValueError as exc:
                raise ValueError("opened source escaped the workspace") from exc
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            return stream.read()
    finally:
        os.close(descriptor)

def diagnose(records: list[dict[str, Any]], workspace: str | Path | None = None) -> dict[str, Any]:
    """Return deterministic diagnostics without mutating records or files."""
    errors: list[dict[str, Any]] = []
    ids: dict[str, list[str]] = {}; paths: dict[str, list[str]] = {}; projects: dict[str, set[str]] = {}
    root = Path(workspace).resolve() if workspace else None
    for index, project in enumerate(records):
        if not isinstance(project, dict):
            errors.append({"code": "invalid_record", "record": index}); continue
        version = project.get("schema_version")
        if version != SCHEMA_VERSION:
            errors.append({"code": "unknown_schema_version", "record": index, "found": version, "expected": SCHEMA_VERSION})
        pid = project.get("project_id", f"record[{index}]")
        projects.setdefault(str(pid), set()).add(str(project.get("status")))
        for ai, asset in enumerate(project.get("assets", [])):
            if not isinstance(asset, dict): continue
            aid = str(asset.get("asset_id", "")); path = str(asset.get("path", ""))
            ids.setdefault(aid, []).append(f"{pid}.assets[{ai}]")
            paths.setdefault(path, []).append(f"{pid}.assets[{ai}]")
            if root and path:
                candidate, path_error = _workspace_candidate(root, path)
                if path_error:
                    errors.append({"code": "unsafe_workspace_path", "asset_id": aid, "path": path})
                    continue
                if candidate is None or not candidate.exists():
                    errors.append({"code": "missing_source_or_attachment", "asset_id": aid, "path": path})
                expected = asset.get("sha256")
                if expected and candidate is not None and candidate.is_file():
                    try:
                        content = _read_verified_bytes(root, candidate)
                    except ValueError:
                        errors.append({"code": "unsafe_workspace_path", "asset_id": aid, "path": path})
                        continue
                    except OSError as exc:
                        errors.append({"code": "unreadable_source", "asset_id": aid, "path": path,
                                       "detail": str(exc)})
                        continue
                    actual = hashlib.sha256(content).hexdigest()
                    if actual != expected:
                        errors.append({"code": "registered_hash_drift", "asset_id": aid, "path": path, "expected": expected, "actual": actual})
        for obj, where in _walk(project):
            if "schema_version" in obj and obj["schema_version"] != SCHEMA_VERSION:
                errors.append({"code": "unknown_schema_version", "where": where, "found": obj["schema_version"], "expected": SCHEMA_VERSION})
            for key in ("path", "attachment_path", "source_path"):
                value = obj.get(key)
                if root and isinstance(value, str) and value:
                    candidate, path_error = _workspace_candidate(root, value)
                    if path_error:
                        errors.append({"code": "unsafe_workspace_path", "where": where, "path": value})
                    elif candidate is None or not candidate.exists():
                        errors.append({"code": "missing_source_or_attachment", "where": where, "path": value})
    for aid, locations in sorted(ids.items()):
        if aid and len(locations) > 1: errors.append({"code": "duplicate_asset_id", "asset_id": aid, "locations": locations})
    for path, locations in sorted(paths.items()):
        if path and len(locations) > 1: errors.append({"code": "duplicate_asset_path", "path": path, "locations": locations})
    for pid, statuses in sorted(projects.items()):
        if len(statuses) > 1: errors.append({"code": "project_status_conflict", "project_id": pid, "statuses": sorted(statuses)})
    return {"schema_version": SCHEMA_VERSION, "valid": not errors, "errors": errors,
            "error_counts": {code: sum(e["code"] == code for e in errors) for code in sorted({e["code"] for e in errors})}}

def _observed_roots(inventory_text: str) -> dict[str, str]:
    roots: dict[str, str] = {}
    current_host: str | None = None
    in_hosts = False
    for line in inventory_text.splitlines():
        if line.strip() == "hosts:":
            in_hosts = True
            current_host = None
            continue
        if not in_hosts:
            continue
        host_match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if host_match:
            current_host = host_match.group(1)
            continue
        root_match = re.match(r"^\s{4}workspace_root_observed:\s*(.+?)\s*$", line)
        if root_match and current_host:
            roots[current_host] = root_match.group(1).strip().strip("'\"")
    return roots

def _norm_root(value: str | Path) -> str:
    return str(Path(value).resolve()).replace("\\", "/").rstrip("/").casefold()

def host_capabilities(workspace: str | Path, inventory_path: str | Path) -> dict[str, Any]:
    """Report directly observable current and historical workspace facts."""
    root = Path(workspace); text = Path(inventory_path).read_text(encoding="utf-8"); roots = _observed_roots(text)
    current = next((host for host, observed in roots.items() if _norm_root(observed) == _norm_root(root)), None)
    hosts = {}
    for host, observed in roots.items():
        is_current = host == current
        workspace_exists = root.is_dir() if is_current else None
        hosts[host] = {"status": "current_verified" if is_current else "historical_unverified",
                       "workspace_root": "." if is_current else "historical workspace root",
                       "capabilities": ({"filesystem_workspace": "verified" if workspace_exists else "unverified",
                                          "read_only_reporting": "verified" if workspace_exists else "unverified"}
                                         if is_current else {"runtime": "historical/unverified", "current_files": "historical/unverified"})}
    if current is None:
        for host in hosts: hosts[host]["status"] = "historical_unverified"
    return {"schema_version": SCHEMA_VERSION, "current_host": current or "unknown_current_host", "hosts": hosts,
        "nonportable_local_state": ["credentials", "caches", "SQLite databases", "licenses", "virtual environments", "desktop services"],
        "inference_policy": "Non-current host status is not inferred from the current workspace; it remains historical/unverified."}

def ledger_metrics(runs_root: str | Path, run_ids: list[str]) -> dict[str, Any]:
    """Derive explicit history metrics from immutable stage ledgers."""
    root = Path(runs_root); per_run = {}
    for run_id in run_ids:
        run = root / run_id; stages = {}; totals = {"attempt_count": 0, "additional_attempts": 0, "acceptance_failures": 0, "waiting_events": 0}
        for stage in ("exploration", "plan", "execution", "test", "acceptance"):
            path = run / ("exploration.yaml" if stage == "exploration" else "plan.yaml" if stage == "plan" else "test_report.json" if stage == "test" else f"{stage}.json")
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"attempts": []}
            attempts = data.get("attempts", [])
            failures = sum(1 for a in attempts if stage == "acceptance" and (a.get("data", {}).get("verdict") == "FAIL" or a.get("data", {}).get("return_to")))
            waiting = sum(1 for a in attempts if a.get("status") == "waiting_for_human")
            additional = max(0, len(attempts)-1)
            stages[stage] = {"attempt_count": len(attempts), "additional_attempts": additional, "acceptance_failures": failures, "waiting_events": waiting}
            totals["attempt_count"] += len(attempts); totals["additional_attempts"] += additional; totals["acceptance_failures"] += failures; totals["waiting_events"] += waiting
        per_run[run_id] = {"stages": stages, "totals": totals}
    overall = {key: sum(run["totals"][key] for run in per_run.values()) for key in ("attempt_count", "additional_attempts", "acceptance_failures", "waiting_events")}
    return {"schema_version": SCHEMA_VERSION, "runs": per_run, "totals": overall,
            "metric_definitions": {"additional_attempts": "attempt_count minus one per stage, floored at zero; acceptance failures are reported separately and may overlap", "acceptance_failures": "acceptance attempts with verdict FAIL or return_to", "waiting_events": "attempts whose status is waiting_for_human"}}

def run_command(argv: list[str], cwd: str | Path, *, timeout: float = DEFAULT_COMMAND_TIMEOUT) -> dict[str, Any]:
    """Run one exact pre-registered stability check, never an arbitrary command."""
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) for arg in argv):
        raise ValueError("argv must be a non-empty list of strings")
    if tuple(argv) not in _REGISTERED_STABILITY_CHECKS:
        raise ValueError("argv must match a pre-registered stability check")
    run_cwd = Path(cwd).resolve()
    if run_cwd != STABILITY_ROOT:
        raise ValueError("cwd must be the repository root")
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= MAX_COMMAND_TIMEOUT:
        raise ValueError(f"timeout must be between 0 and {MAX_COMMAND_TIMEOUT} seconds")
    start = time.perf_counter(); result = subprocess.run(argv, cwd=str(run_cwd), capture_output=True, text=True,
                                                          shell=False, timeout=float(timeout), check=False)
    return {"command": " ".join(argv), "elapsed_seconds": round(time.perf_counter()-start, 6), "return_code": result.returncode,
            "stdout": result.stdout[-2000:], "stderr": result.stderr[-2000:]}

def rebuild_relation_artifacts(run_artifacts: str | Path, snapshot_paths: list[str | Path], manifest: str | Path, ris: str | Path, markdown_root: str | Path) -> dict[str, Any]:
    from relation_map import combine_snapshots, load_snapshot, build_mapping, write_artifacts
    out = ensure_output_directory(run_artifacts)
    result = build_mapping(combine_snapshots([load_snapshot(p) for p in snapshot_paths]), manifest, ris, markdown_root)
    write_artifacts(result, out)
    return {"schema_version": SCHEMA_VERSION, "rebuildable": True, "artifact_names": sorted(p.name for p in out.glob("*.json")),
            "relation_summary": result["summary"], "source_policy": "snapshots, manifest, RIS and relative Markdown names only; no attachment/body/hash reads"}
