"""Filesystem-native run ledger (standard library only)."""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
STAGES = ("exploration", "plan", "execution", "test", "acceptance")
ROLE_BY_STAGE = {
    "exploration": "sol",
    "plan": "sol",
    "execution": "execution_agent",
    "test": "execution_agent",
    "acceptance": "sol",
}
STAGE_FILES = {
    "exploration": "exploration.yaml",
    "plan": "plan.yaml",
    "execution": "execution.json",
    "test": "test_report.json",
    "acceptance": "acceptance.json",
}
BUNDLE_FILES = (
    "request.yaml",
    "exploration.yaml",
    "plan.yaml",
    "inputs.json",
    "execution.json",
    "test_report.json",
    "acceptance.json",
    "manifest.json",
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RECORD_STATUSES = {"completed", "waiting_for_human", "failed"}


class RunLedgerError(ValueError):
    """Raised when a run request or bundle violates the ledger contract."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def validate_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_RE.fullmatch(run_id):
        raise RunLedgerError("invalid run_id: use 1-64 ASCII letters, digits, '.', '_' or '-' and start with alphanumeric")
    if run_id in {".", ".."}:
        raise RunLedgerError("invalid run_id")
    return run_id


def resolve_run_dir(runs_root: str | Path, run_id: str) -> Path:
    """Resolve a validated run below the caller-supplied allowed root."""
    validate_run_id(run_id)
    root = Path(runs_root).expanduser().resolve()
    run_dir = (root / run_id).resolve()
    if run_dir == root or root not in run_dir.parents:
        raise RunLedgerError("run directory escapes runs_root")
    return run_dir


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _atomic_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunLedgerError(f"cannot read {path.name}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunLedgerError(f"{path.name} must contain a JSON object")
    return value


def _stage_document(run_id: str, stage: str) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "run_id": run_id, "stage": stage, "attempts": []}


def _string_list(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise RunLedgerError(f"{field} must be a list of non-empty strings")
    if nonempty and not value:
        raise RunLedgerError(f"{field} must not be empty")
    return value


def _validate_completed_evidence(stage: str, data: dict[str, Any]) -> None:
    if stage == "plan":
        if not isinstance(data.get("steps"), list):
            raise RunLedgerError("plan completed requires steps list")
        _string_list(data.get("risks"), "plan risks")
    elif stage == "execution":
        commands = _string_list(data.get("commands"), "execution commands")
        return_codes = data.get("return_codes")
        if not isinstance(return_codes, list) or not all(isinstance(code, int) and not isinstance(code, bool) for code in return_codes):
            raise RunLedgerError("execution return_codes must be an integer list")
        if len(commands) != len(return_codes):
            raise RunLedgerError("execution commands and return_codes lengths must match")
        _string_list(data.get("output_paths"), "execution output_paths")
    elif stage == "test":
        if not isinstance(data.get("test_results"), list):
            raise RunLedgerError("test completed requires test_results list")
    elif stage == "acceptance":
        _string_list(data.get("unresolved_risks"), "acceptance unresolved_risks")
        verdict = data.get("verdict")
        if verdict == "PASS":
            _string_list(data.get("test_evidence"), "acceptance PASS test_evidence", nonempty=True)
        elif verdict == "FAIL":
            _string_list(data.get("test_evidence"), "acceptance FAIL test_evidence", nonempty=True)
            if data.get("return_to") not in {"execution", "test"}:
                raise RunLedgerError("acceptance FAIL requires return_to execution or test")
        elif verdict == "CANNOT_VERIFY":
            if not isinstance(data.get("reason"), str) or not data["reason"].strip():
                raise RunLedgerError("acceptance CANNOT_VERIFY requires reason")
        else:
            raise RunLedgerError("acceptance completed requires verdict PASS, FAIL, or CANNOT_VERIFY")


def create_run(runs_root: str | Path, run_id: str, request: Any = None, inputs: Any = None) -> dict[str, Any]:
    run_dir = resolve_run_dir(runs_root, run_id)
    run_dir.parent.mkdir(parents=True, exist_ok=True)
    if run_dir.exists():
        raise RunLedgerError(f"run already exists: {run_id}")
    if inputs is None:
        inputs = {"input_hashes": []}
    if not isinstance(inputs, dict):
        raise RunLedgerError("inputs must be an object containing input_hashes")
    _string_list(inputs.get("input_hashes"), "input_hashes")
    created_at = _now()
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "type": "Run",
        "run_id": run_id,
        "status": "active",
        "current_stage": "exploration",
        "created_at": created_at,
        "updated_at": created_at,
        "stages": {
            stage: {"role": ROLE_BY_STAGE[stage], "status": "active" if stage == "exploration" else "pending", "attempt_count": 0}
            for stage in STAGES
        },
        "history": [{"event": "run_created", "at": created_at, "current_stage": "exploration"}],
    }
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=str(run_dir.parent)))
    try:
        _atomic_write(temp_dir / "request.yaml", {"schema_version": SCHEMA_VERSION, "run_id": run_id, "request": request})
        _atomic_write(temp_dir / "inputs.json", {"schema_version": SCHEMA_VERSION, "run_id": run_id, "inputs": inputs})
        for stage in STAGES:
            _atomic_write(temp_dir / STAGE_FILES[stage], _stage_document(run_id, stage))
        _atomic_write(temp_dir / "manifest.json", manifest)
        os.replace(temp_dir, run_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    return manifest


def _advance(manifest: dict[str, Any], stage: str) -> None:
    index = STAGES.index(stage)
    manifest["stages"][stage]["status"] = "completed"
    if stage == "acceptance":
        return
    next_stage = STAGES[index + 1]
    manifest["current_stage"] = next_stage
    manifest["status"] = "active"
    manifest["stages"][next_stage]["status"] = "active"


def record_stage(
    runs_root: str | Path,
    run_id: str,
    stage: str,
    role: str,
    status: str,
    data: Any = None,
    *,
    model: str,
    inputs: Any = None,
    outputs: Any = None,
) -> dict[str, Any]:
    run_dir = resolve_run_dir(runs_root, run_id)
    manifest = _load_json(run_dir / "manifest.json")
    errors = validate_bundle(runs_root, run_id)
    if errors:
        raise RunLedgerError("invalid run bundle: " + "; ".join(errors))
    if stage not in STAGES:
        raise RunLedgerError(f"unknown stage: {stage}")
    if role != ROLE_BY_STAGE[stage]:
        raise RunLedgerError(f"stage {stage} requires role {ROLE_BY_STAGE[stage]}")
    if status not in RECORD_STATUSES:
        raise RunLedgerError(f"unsupported record status: {status}")
    if stage == "acceptance" and status == "failed":
        raise RunLedgerError("acceptance does not allow status failed; use completed with verdict FAIL")
    if not isinstance(model, str) or not model.strip():
        raise RunLedgerError("model must be a non-empty string")
    if manifest.get("current_stage") != stage:
        raise RunLedgerError(f"cannot record {stage}; current_stage is {manifest.get('current_stage')!r}")

    data = {} if data is None else data
    if not isinstance(data, dict):
        raise RunLedgerError("stage data must be an object")
    if status == "completed":
        _validate_completed_evidence(stage, data)
    recorded_at = _now()
    document = _load_json(run_dir / STAGE_FILES[stage])
    attempt = {
        "attempt": len(document["attempts"]) + 1,
        "at": recorded_at,
        "role": role,
        "model": model.strip(),
        "status": status,
        "inputs": inputs,
        "outputs": outputs,
        "data": data,
    }
    document["attempts"].append(attempt)
    manifest["stages"][stage]["attempt_count"] += 1

    if status == "waiting_for_human":
        manifest["status"] = "waiting_for_human"
        manifest["stages"][stage]["status"] = "waiting_for_human"
    elif status == "failed":
        manifest["status"] = "failed"
        manifest["stages"][stage]["status"] = "failed"
    elif stage != "acceptance":
        _advance(manifest, stage)
    else:
        verdict = data.get("verdict")
        if verdict == "PASS":
            _string_list(data.get("test_evidence"), "acceptance PASS test_evidence", nonempty=True)
            manifest["stages"][stage]["status"] = "completed"
            manifest["status"] = "accepted"
            manifest["current_stage"] = None
        elif verdict == "FAIL":
            _string_list(data.get("test_evidence"), "acceptance FAIL test_evidence", nonempty=True)
            return_to = data.get("return_to")
            if return_to not in {"execution", "test"}:
                raise RunLedgerError("acceptance FAIL requires return_to execution or test")
            manifest["stages"][stage]["status"] = "rejected"
            manifest["status"] = "rejected"
            manifest["current_stage"] = return_to
            start = STAGES.index(return_to)
            for later in STAGES[start:]:
                manifest["stages"][later]["status"] = "active" if later == return_to else "pending"
        elif verdict == "CANNOT_VERIFY":
            reason = data.get("reason")
            if not isinstance(reason, str) or not reason.strip():
                raise RunLedgerError("acceptance CANNOT_VERIFY requires reason")
            manifest["status"] = "waiting_for_human"
            manifest["stages"][stage]["status"] = "waiting_for_human"
        else:
            raise RunLedgerError("acceptance completed requires verdict PASS, FAIL, or CANNOT_VERIFY")

    manifest["updated_at"] = recorded_at
    manifest["history"].append({
        "event": "stage_recorded",
        "at": recorded_at,
        "stage": stage,
        "attempt": attempt["attempt"],
        "record_status": status,
        "manifest_status": manifest["status"],
        "current_stage": manifest["current_stage"],
    })
    _atomic_write(run_dir / STAGE_FILES[stage], document)
    _atomic_write(run_dir / "manifest.json", manifest)
    return manifest


def validate_bundle(runs_root: str | Path, run_id: str) -> list[str]:
    try:
        run_dir = resolve_run_dir(runs_root, run_id)
    except RunLedgerError as exc:
        return [str(exc)]
    errors: list[str] = []
    if not run_dir.is_dir():
        return [f"missing run directory: {run_id}"]
    documents: dict[str, dict[str, Any]] = {}
    for name in BUNDLE_FILES:
        path = run_dir / name
        if not path.is_file():
            errors.append(f"missing bundle file: {name}")
            continue
        try:
            documents[name] = _load_json(path)
        except RunLedgerError as exc:
            errors.append(str(exc))
    for name, doc in documents.items():
        if doc.get("schema_version") != SCHEMA_VERSION:
            errors.append(f"{name} unsupported schema_version: {doc.get('schema_version')!r}")
        if doc.get("run_id") != run_id:
            errors.append(f"{name} run_id mismatch")
    inputs_doc = documents.get("inputs.json")
    if inputs_doc is not None:
        inputs_value = inputs_doc.get("inputs")
        try:
            if not isinstance(inputs_value, dict):
                raise RunLedgerError("inputs must be an object containing input_hashes")
            _string_list(inputs_value.get("input_hashes"), "input_hashes")
        except RunLedgerError as exc:
            errors.append(f"inputs.json {exc}")
    for stage, name in STAGE_FILES.items():
        doc = documents.get(name)
        if doc is None:
            continue
        if doc.get("stage") != stage:
            errors.append(f"{name} stage mismatch")
        attempts = doc.get("attempts")
        if not isinstance(attempts, list):
            errors.append(f"{name} attempts must be a list")
        elif any(not isinstance(attempt, dict) for attempt in attempts):
            errors.append(f"{name} attempts entries must be objects")
    manifest = documents.get("manifest.json")
    if manifest is not None:
        if manifest.get("type") != "Run":
            errors.append("manifest.json type must be Run")
        stages = manifest.get("stages")
        if manifest.get("status") not in {"active", "waiting_for_human", "failed", "accepted", "rejected"}:
            errors.append("manifest.json status is invalid")
        if not isinstance(stages, dict) or set(stages) != set(STAGES):
            errors.append("manifest.json stages must contain exactly the fixed stages")
        else:
            active = [stage for stage in STAGES if isinstance(stages.get(stage), dict) and stages[stage].get("status") == "active"]
            for stage in STAGES:
                state = stages[stage]
                if not isinstance(state, dict):
                    errors.append(f"manifest.json {stage} state must be an object")
                    continue
                if state.get("role") != ROLE_BY_STAGE[stage]:
                    errors.append(f"manifest.json {stage} role mismatch")
                if state.get("status") not in {"pending", "active", "waiting_for_human", "failed", "completed", "rejected"}:
                    errors.append(f"manifest.json {stage} status is invalid")
                if not isinstance(state.get("attempt_count"), int) or state.get("attempt_count") < 0:
                    errors.append(f"manifest.json {stage} attempt_count is invalid")
            current = manifest.get("current_stage")
            if current is not None and current not in STAGES:
                errors.append("manifest.json current_stage is invalid")
            if len(active) > 1:
                errors.append("manifest.json has multiple active/current stages")
            if current is None and active:
                errors.append("manifest.json has active stage but no current_stage")
            manifest_status = manifest.get("status")
            if current is not None and manifest_status in {"active", "rejected"} and active != [current]:
                errors.append("manifest.json current_stage does not match the single active stage")
            if current is not None and manifest_status in {"waiting_for_human", "failed"}:
                if active or stages[current].get("status") != manifest_status:
                    errors.append("manifest.json current_stage status mismatch")
            if manifest.get("status") == "accepted":
                acceptance = documents.get("acceptance.json", {}).get("attempts", [])
                latest = acceptance[-1] if acceptance else {}
                latest_data = latest.get("data", {}) if isinstance(latest, dict) else {}
                evidence = latest_data.get("test_evidence") if isinstance(latest_data, dict) else None
                risks = latest_data.get("unresolved_risks") if isinstance(latest_data, dict) else None
                if manifest.get("current_stage") is not None:
                    errors.append("accepted run must have current_stage null")
                if any(stages[stage].get("status") != "completed" for stage in STAGES):
                    errors.append("accepted run must have all stages completed")
                if (not acceptance or latest.get("role") != "sol" or latest.get("status") != "completed"
                        or latest_data.get("verdict") != "PASS"):
                    errors.append("accepted run lacks latest Sol acceptance PASS")
                if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
                    errors.append("accepted run has invalid test_evidence")
                if not isinstance(risks, list) or not all(isinstance(item, str) and item.strip() for item in risks):
                    errors.append("accepted run has invalid unresolved_risks")
            for stage, name in STAGE_FILES.items():
                attempts = documents.get(name, {}).get("attempts")
                if isinstance(attempts, list) and stages[stage].get("attempt_count") != len(attempts):
                    errors.append(f"manifest.json {stage} attempt_count mismatch")
                if isinstance(attempts, list):
                    for index, attempt in enumerate(attempts, 1):
                        if not isinstance(attempt, dict):
                            continue
                        if attempt.get("attempt") != index:
                            errors.append(f"{name} attempt numbering mismatch")
                        if attempt.get("role") != ROLE_BY_STAGE[stage]:
                            errors.append(f"{name} attempt role mismatch")
                        if not isinstance(attempt.get("model"), str) or not attempt.get("model").strip():
                            errors.append(f"{name} attempt model is invalid")
                        if "inputs" not in attempt or "outputs" not in attempt:
                            errors.append(f"{name} attempt must record inputs and outputs")
                        if attempt.get("status") not in RECORD_STATUSES:
                            errors.append(f"{name} attempt status is invalid")
                        if stage == "acceptance" and attempt.get("status") == "failed":
                            errors.append("acceptance.json does not allow failed attempts")
                        if attempt.get("status") == "completed":
                            data = attempt.get("data")
                            if not isinstance(data, dict):
                                errors.append(f"{name} completed attempt data must be an object")
                            else:
                                try:
                                    _validate_completed_evidence(stage, data)
                                except RunLedgerError as exc:
                                    errors.append(f"{name} {exc}")
        if not isinstance(manifest.get("history"), list):
            errors.append("manifest.json history must be a list")
    return errors


def inspect_run(runs_root: str | Path, run_id: str) -> dict[str, Any]:
    errors = validate_bundle(runs_root, run_id)
    if errors:
        raise RunLedgerError("invalid run bundle: " + "; ".join(errors))
    return _load_json(resolve_run_dir(runs_root, run_id) / "manifest.json")
