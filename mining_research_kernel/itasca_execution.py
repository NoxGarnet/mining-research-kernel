"""Prepare and resume bounded observations of Agent-run Itasca MCP tasks.

This module records calls already made by the Agent. It never submits work,
queries an engine, enables static checks, or interprets solver success as
scientific or engineering acceptance.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.artifacts import _absolute_without_follow, _reject_reparse_chain
from mining_research_kernel.records import ResearchStore, WriterLockedError
from mining_research_kernel.r2_workflow import _record, _relationship


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
_HEX = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_SCRIPT_LIMIT = 256 * 1024
_OBSERVATION_LIMIT = 128 * 1024
_OUTPUT_LIMIT = 64 * 1024
_TERMINAL = {"completed", "failed", "interrupted"}
_TRANSITIONS = {
    "prepared": {"submission_unknown", "pending", "failed"},
    "submission_unknown": {"submission_unknown", "pending", "running", "completed", "failed", "interrupted"},
    "pending": {"pending", "running", "completed", "failed", "interrupted"},
    "running": {"running", "completed", "failed", "interrupted"},
    "completed": {"completed"}, "failed": {"failed"}, "interrupted": {"interrupted"},
}
_METADATA_REQUIRED = {"software", "product_version", "purpose", "stop_conditions",
                      "output_root", "engine_session", "origin"}
_METADATA_ALLOWED = _METADATA_REQUIRED | {"question_id"}
_OBSERVATION_KEYS = {"schema_version", "kind", "origin", "captured_at", "phase", "tool_result"}


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise ValueError(f"value must be finite JSON: {exc}") from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError(f"{name} must be a stable record-safe identifier")
    return value


def _project_root(value: str | os.PathLike[str]) -> Path:
    raw = _absolute_without_follow(value)
    _reject_reparse_chain(raw, "Itasca execution project root")
    root = raw.resolve()
    if not root.is_dir():
        raise ValueError("project_root must be an existing directory")
    return root


def _string(value: Any, name: str, limit: int, *, allow_empty: bool = False) -> str:
    if (not isinstance(value, str) or len(value) > limit or "\x00" in value
            or (not allow_empty and not value.strip())):
        raise ValueError(f"{name} must be a string of at most {limit} characters")
    return value


def _timestamp(value: Any, name: str) -> str:
    text = _string(value, name, 40)
    try:
        parsed = datetime.fromisoformat(text[:-1] + "+00:00" if text.endswith("Z") else text)
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0:
        raise ValueError(f"{name} must be UTC")
    return text


def _relative_file(root: Path, value: Any, name: str, *, must_exist: bool,
                   expect: str = "directory") -> tuple[str, Path]:
    text = _string(value, name, 512)
    if ("\\" in text or ":" in text or text.startswith("/")
            or Path(text).is_absolute() or any(part in {"", ".", ".."} for part in text.split("/"))):
        raise ValueError(f"{name} must be a safe project-relative path")
    raw = root.joinpath(*text.split("/"))
    try:
        resolved = raw.resolve(strict=must_exist)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{name} resolves outside the project or cannot be resolved") from exc
    _reject_reparse_chain(raw, name)
    if (must_exist or expect == "file") and resolved.exists() and not resolved.is_file():
        raise ValueError(f"{name} must identify a regular file")
    if must_exist and not resolved.exists():
        raise ValueError(f"{name} must identify an existing file")
    if expect == "directory" and resolved.exists() and not resolved.is_dir():
        raise ValueError(f"{name} must identify a directory")
    return resolved.relative_to(root).as_posix(), resolved


def _read_script(root: Path, path: str, expected_hash: str | None = None) -> tuple[bytes, str]:
    _, resolved = _relative_file(root, path, "script path", must_exist=True, expect="file")
    try:
        with resolved.open("rb") as stream:
            raw = stream.read(_SCRIPT_LIMIT + 1)
    except OSError as exc:
        raise ValueError(f"cannot read script: {exc}") from exc
    if len(raw) > _SCRIPT_LIMIT:
        raise ValueError("script exceeds the 256 KiB snapshot limit")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("script must be valid UTF-8") from exc
    digest = hashlib.sha256(raw).hexdigest()
    if expected_hash is not None and digest != expected_hash:
        raise ValueError("current entry script bytes differ from the prepared plan")
    return raw, text


def _validate_metadata(root: Path, metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, Mapping) or set(metadata) - _METADATA_ALLOWED or _METADATA_REQUIRED - set(metadata):
        raise ValueError("metadata has unknown or missing fields")
    if metadata["software"] != "flac3d":
        raise ValueError("software must be flac3d")
    version = _string(metadata["product_version"], "product_version", 120)
    purpose = _string(metadata["purpose"], "purpose", 500)
    session = _string(metadata["engine_session"], "engine_session", 120)
    origin = metadata["origin"]
    if not isinstance(origin, str) or origin not in {"provided_script", "synthetic"}:
        raise ValueError("origin must be provided_script or synthetic")
    stops = metadata["stop_conditions"]
    if (not isinstance(stops, list) or not 1 <= len(stops) <= 20
            or any(not isinstance(item, str) or not item.strip() or len(item) > 300 for item in stops)):
        raise ValueError("stop_conditions must contain 1 to 20 bounded non-empty strings")
    output_root, _ = _relative_file(root, metadata["output_root"], "output_root", must_exist=False)
    normalized = {"software": "flac3d", "product_version": version, "purpose": purpose,
                  "stop_conditions": list(stops), "output_root": output_root,
                  "engine_session": session, "origin": origin}
    if "question_id" in metadata:
        normalized["question_id"] = _id(metadata["question_id"], "question_id")
    return normalized


def _validate_observation(data: Any, task_context: str) -> dict[str, Any]:
    if not isinstance(data, Mapping) or set(data) != _OBSERVATION_KEYS:
        raise ValueError("observation must match the strict top-level contract")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("observation schema_version must be integer 1")
    if data["kind"] != "itasca_execution_observation":
        raise ValueError("invalid observation kind")
    origin = data["origin"]
    if not isinstance(origin, str) or origin not in {"agent_supplied", "synthetic"}:
        raise ValueError("origin must be agent_supplied or synthetic")
    if (origin == "synthetic") != (task_context == "synthetic"):
        raise ValueError("synthetic and production observations cannot be mixed")
    phase = data["phase"]
    if not isinstance(phase, str) or phase not in {"submission", "status"}:
        raise ValueError("phase must be submission or status")
    result = data["tool_result"]
    if not isinstance(result, Mapping) or set(result) != {"ok", "data"} and set(result) != {"ok", "error"}:
        raise ValueError("tool_result must be the actual MCP {ok,data} or {ok:false,error} object")
    if type(result.get("ok")) is not bool:
        raise ValueError("tool_result.ok must be boolean")
    if result["ok"] and (set(result) != {"ok", "data"} or not isinstance(result["data"], Mapping)):
        raise ValueError("successful tool_result requires a data object")
    if not result["ok"] and (set(result) != {"ok", "error"} or not isinstance(result["error"], Mapping)):
        raise ValueError("failed tool_result requires an error object")
    encoded = _canonical(dict(data))
    if len(encoded) > _OBSERVATION_LIMIT:
        raise ValueError("observation exceeds the 128 KiB limit")
    result_copy = json.loads(encoded.decode("utf-8"))
    tool_copy = result_copy["tool_result"]
    if tool_copy["ok"]:
        payload = tool_copy["data"]
        task_id = payload.get("task_id")
        if task_id is not None:
            _id(task_id, "tool_result task_id")
        if phase == "submission":
            if payload.get("task_status") != "pending" or not task_id:
                raise ValueError("successful submission must include task_id and pending status")
            _string(payload.get("entry_script"), "entry_script", 2048)
        else:
            if (not isinstance(payload.get("task_status"), str)
                    or payload.get("task_status") not in {"pending", "running", "completed", "failed", "interrupted"}):
                raise ValueError("successful status result has an unsupported task_status")
            if not task_id:
                raise ValueError("successful status result must include task_id")
        if "output" in payload:
            if not isinstance(payload["output"], str):
                raise ValueError("tool output must be text")
            if len(payload["output"].encode("utf-8")) > _OUTPUT_LIMIT:
                raise ValueError("captured tool output exceeds the 64 KiB limit")
        if "pagination" in payload and payload["pagination"] is not None and not isinstance(payload["pagination"], Mapping):
            raise ValueError("pagination must be an object when supplied")
    else:
        error = tool_copy["error"]
        if not isinstance(error.get("code"), str) or not isinstance(error.get("message"), str):
            raise ValueError("MCP error requires string code and message")
        details = error.get("details")
        if details is not None and not isinstance(details, Mapping):
            raise ValueError("MCP error details must be an object")
        task_id = details.get("task_id") if isinstance(details, Mapping) else None
        if task_id is not None:
            _id(task_id, "error task_id")
    return {"schema_version": 1, "kind": "itasca_execution_observation", "origin": origin,
            "captured_at": _timestamp(data["captured_at"], "captured_at"), "phase": phase,
            "tool_result": tool_copy}


def _latest_records(store: ResearchStore) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for tx in store.list_transactions():
        for record in tx["records"]:
            if record["revision"] >= latest.get(record["id"], {"revision": 0})["revision"]:
                latest[record["id"]] = copy.deepcopy(record)
    return latest


def _record_revision(store: ResearchStore, record_id: str, revision: int, record_type: str) -> dict[str, Any] | None:
    matches = [record for tx in store.list_transactions() for record in tx["records"]
               if record.get("id") == record_id and record.get("revision") == revision
               and record.get("type") == record_type]
    if len(matches) > 1:
        raise ValueError(f"duplicate persisted {record_type} revision {record_id}@{revision}")
    return copy.deepcopy(matches[0]) if matches else None


def _suffix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _op_id(prefix: str, value: str) -> str:
    return f"{prefix}.{_suffix(value)}"


@contextmanager
def _writer_retry(store: ResearchStore, operation_id: str):
    for attempt in range(100):
        lock = store.writer(operation_id)
        try:
            lock.__enter__()
            break
        except WriterLockedError:
            if attempt == 99:
                raise
            time.sleep(0.025)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _plan_for(store: ResearchStore, run_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    suffix = _suffix(run_id)
    run_ref = store.latest_record(f"itasca.run.{suffix}", "RunReference")
    if run_ref is None:
        raise ValueError(f"unknown Itasca run: {run_id}")
    plan_asset_ref = run_ref.get("plan_asset_ref")
    plan_asset_revision = run_ref.get("plan_asset_revision")
    if not isinstance(plan_asset_ref, str) or type(plan_asset_revision) is not int or plan_asset_revision < 1:
        raise ValueError("RunReference has no valid pinned plan Asset revision")
    asset = _record_revision(store, plan_asset_ref, plan_asset_revision, "Asset")
    if asset is None or asset.get("asset_kind") != "itasca_execution_plan" or not isinstance(asset.get("payload"), dict):
        raise ValueError("Itasca execution plan Asset is missing or damaged")
    plan = asset["payload"].get("plan")
    if not isinstance(plan, dict) or plan.get("run_id") != run_id or _sha(plan) != run_ref.get("manifest_sha256"):
        raise ValueError("Itasca execution plan manifest hash or run identity is invalid")
    if asset.get("content_sha256") != _sha(asset["payload"]):
        raise ValueError("Itasca execution plan Asset payload hash is invalid")
    legal_states = {"prepared", "pending", "running", "completed", "failed", "interrupted", "submission_unknown"}
    if (not isinstance(run_ref.get("status"), str) or run_ref.get("status") not in legal_states
            or run_ref.get("state") != run_ref.get("status")):
        raise ValueError("RunReference status/state is invalid or inconsistent")
    if run_ref["status"] in {"pending", "running", "completed", "failed", "interrupted"} and not run_ref.get("task_id"):
        raise ValueError("RunReference observed lifecycle status requires its external task_id")
    script = plan.get("script")
    if (not isinstance(script, dict) or set(script) != {"path", "sha256", "text"}
            or not isinstance(script.get("sha256"), str) or not _HEX.fullmatch(script["sha256"])
            or not isinstance(script.get("text"), str)
            or hashlib.sha256(script["text"].encode("utf-8")).hexdigest() != script["sha256"]):
        raise ValueError("Itasca plan script snapshot or byte hash is invalid")
    _relative_file(store.project_root, script["path"], "plan script path", must_exist=False, expect="file")
    _relative_file(store.project_root, plan.get("output_root"), "plan output_root", must_exist=False)
    return run_ref, asset, plan


def prepare_itasca_run(project_root: str | os.PathLike[str], *, run_id: str, script: str,
                       metadata: Mapping[str, Any], task_context: str = "production") -> dict[str, Any]:
    """Persist a bounded script snapshot and route, without executing it."""
    run_id = _id(run_id, "run_id")
    if not isinstance(task_context, str) or task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")
    root = _project_root(project_root)
    normalized = _validate_metadata(root, metadata)
    if (normalized["origin"] == "synthetic") != (task_context == "synthetic"):
        raise ValueError("synthetic input must use synthetic task_context, and vice versa")
    script_path, _ = _relative_file(root, script, "script", must_exist=True, expect="file")
    raw, text = _read_script(root, script_path)
    store = ResearchStore(root)
    question_id = normalized.pop("question_id", None)
    if question_id is not None:
        question = store.latest_record(question_id, "ResearchQuestion")
        if question is None or question.get("project_id") != store.project_id:
            raise ValueError("question_id must reference an existing ResearchQuestion in this project")
    plan = {"schema_version": 1, "kind": "itasca_execution_plan", "run_id": run_id,
            "script": {"path": script_path, "sha256": hashlib.sha256(raw).hexdigest(), "text": text},
            "software": normalized["software"], "product_version": normalized["product_version"],
            "purpose": normalized["purpose"], "stop_conditions": normalized["stop_conditions"],
            "output_root": normalized["output_root"], "engine_session": normalized["engine_session"],
            "task_context": task_context, "origin": normalized["origin"],
            "limitations": ["plan preparation does not authorize execution or prove a complete static check",
                            "Agent supplied MCP observations are not independently queried"]}
    if question_id is not None:
        plan["question_id"] = question_id
    run_suffix = _suffix(run_id)
    run_record_id = f"itasca.run.{run_suffix}"
    route_id = f"itasca.route.{run_suffix}"
    asset_id = f"itasca.plan.{run_suffix}"
    evidence_ref = [f"itasca_run:{run_id}", f"asset:{asset_id}", f"route:{route_id}"]
    plan_payload = {"kind": "itasca_execution_plan_record", "plan": plan}
    asset = _record("Asset", asset_id, store.project_id, evidence_ref,
                    asset_kind="itasca_execution_plan",
                    locator={"path": f"record:{asset_id}#payload", "path_kind": "record_embedded",
                             "record_id": asset_id, "field": "payload", "embedded_payload": "payload"},
                    content_sha256=_sha(plan_payload), authority="derived", status="observed", payload=plan_payload)
    question_new = question_id is None
    if question_new:
        question_id = f"itasca.question.{run_suffix}"
        question = _record("ResearchQuestion", question_id, store.project_id, evidence_ref,
                           statement=f"Itasca execution observation: {normalized['purpose']}", status="active")
    route = _record("Route", route_id, store.project_id, evidence_ref,
                    status="active", route_id=route_id, question_id=question_id,
                    research_question_id=question_id, hypothesis_id=None, claim_id=None, task_id=None,
                    workflow_id="mining_research_kernel.workflow.itasca_execution",
                    method_id="agent_supplied_itasca_mcp_observation", budget=1, runs_used=0,
                    stop_conditions=list(normalized["stop_conditions"]), outputs=[], reservations=[],
                    write_set=["research/records"], stop_reason=None)
    run_ref = _record("RunReference", run_record_id, store.project_id, evidence_ref,
                      run_id=run_id, status="prepared", manifest_sha256=_sha(plan),
                      plan_asset_ref=asset_id, plan_asset_revision=asset["revision"],
                      route_id=route_id, task_context=task_context,
                      engine_session=normalized["engine_session"], observation_refs=[], task_id=None,
                      state="prepared", state_history=[{"state": "prepared", "at": None}])
    question_record = question if question_new else store.latest_record(question_id, "ResearchQuestion")
    relationships = [
        _relationship(f"itasca.edge.{run_suffix}.question", "route_addresses_question", route,
                      question_record, store.project_id, evidence_ref),
        _relationship(f"itasca.edge.{run_suffix}.run-route", "run_executes_route", run_ref,
                      route, store.project_id, evidence_ref),
        _relationship(f"itasca.edge.{run_suffix}.route-plan", "route_reads_asset", route,
                      asset, store.project_id, evidence_ref),
    ]
    records = [asset] + ([question] if question_new else []) + [route, run_ref]
    op = _op_id("itasca.prepare", run_id)
    with _writer_retry(store, op):
        current = _latest_records(store)
        prior = current.get(run_record_id)
        if prior is not None:
            loaded_ref, _, prior_plan = _plan_for(store, run_id)
            if prior_plan != plan:
                raise ValueError(f"run_id already records a different plan: {run_id}")
            return {"status": "replayed", "run_ref": loaded_ref, "plan": prior_plan,
                    "plan_asset_ref": asset_id, "route_id": route_id}
        expected = {question_id: int(question_record["revision"])} if not question_new else {}
        store.commit(op, {"role": "host", "model": "itasca_execution"}, records,
                     relationships, expected_revisions=expected, lock_held=True)
    return {"status": "prepared", "run_ref": run_ref, "plan": plan,
            "plan_asset_ref": asset_id, "route_id": route_id}


def _observation_task_id(observation: Mapping[str, Any]) -> str | None:
    result = observation["tool_result"]
    if result["ok"]:
        return result["data"].get("task_id")
    details = result["error"].get("details")
    return details.get("task_id") if isinstance(details, Mapping) else None


def _status_from_observation(observation: Mapping[str, Any], current: str) -> str:
    result = observation["tool_result"]
    if observation["phase"] == "submission":
        if result["ok"]:
            return "pending"
        # A failed MCP call carrying a task ID may have been accepted.
        return "submission_unknown" if _observation_task_id(observation) else "submission_unknown"
    if not result["ok"]:
        return "submission_unknown" if current == "submission_unknown" else current
    status = result["data"]["task_status"]
    return status


def _check_task_identity(run_ref: Mapping[str, Any], plan: Mapping[str, Any],
                         observation: Mapping[str, Any], existing_task_id: str | None) -> str | None:
    task_id = _observation_task_id(observation)
    if task_id is None:
        if observation["phase"] == "submission" and not observation["tool_result"]["ok"]:
            return None
        raise ValueError("observation does not identify a task_id")
    if existing_task_id is not None and task_id != existing_task_id:
        raise ValueError("observation task_id does not match the run's existing task")
    if observation["phase"] == "status" and existing_task_id is None:
        raise ValueError("status recovery requires an already associated task_id")
    if observation["phase"] == "submission" and observation["tool_result"]["ok"]:
        payload = observation["tool_result"]["data"]
        root = Path(run_ref["_project_root"])
        resolved = (root / plan["script"]["path"]).resolve(strict=True)
        if not resolved.is_file():
            raise ValueError("prepared entry script is no longer a file")
        _, text = _read_script(root, plan["script"]["path"], plan["script"]["sha256"])
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != plan["script"]["sha256"]:
            raise ValueError("prepared entry script changed")
        supplied = Path(payload["entry_script"])
        if not supplied.is_absolute():
            raise ValueError("successful submission entry_script must be absolute")
        if os.path.normcase(str(supplied.resolve())) != os.path.normcase(str(resolved)):
            raise ValueError("submission entry_script does not match the prepared plan path")
    return task_id


def _record_for_asset(store: ResearchStore, asset_id: str) -> dict[str, Any] | None:
    return store.latest_record(asset_id, "Asset")


def record_itasca_observation(project_root: str | os.PathLike[str], *, run_id: str,
                              operation_id: str, observation: Mapping[str, Any]) -> dict[str, Any]:
    """Record one already obtained MCP submission or status result atomically."""
    run_id = _id(run_id, "run_id")
    operation_id = _id(operation_id, "operation_id")
    root = _project_root(project_root)
    store = ResearchStore(root)
    initial_ref, _, plan = _plan_for(store, run_id)
    normalized = _validate_observation(observation, initial_ref["task_context"])
    if normalized["origin"] != ("synthetic" if plan["origin"] == "synthetic" else "agent_supplied"):
        raise ValueError("observation origin does not match the prepared run")
    request = {"run_id": run_id, "operation_id": operation_id,
               "observation": normalized, "plan_sha256": initial_ref["manifest_sha256"]}
    request_hash = _sha(request)
    op_suffix = _suffix(run_id + "\0" + operation_id)
    asset_id, evidence_id = f"itasca.obs.{op_suffix}", f"itasca.ev.{op_suffix}"
    asset_payload = {"kind": "itasca_execution_observation_record", "request": request,
                     "request_sha256": request_hash,
                     "limitations": ["tool result was supplied by the Agent and not re-queried"]}
    refs = [f"itasca_run:{run_id}", f"operation:{operation_id}", f"asset:{asset_id}", f"evidence:{evidence_id}"]
    asset = _record("Asset", asset_id, store.project_id, refs,
                    asset_kind="itasca_execution_observation", locator={
                        "path": f"record:{asset_id}#payload", "path_kind": "record_embedded",
                        "record_id": asset_id, "field": "payload", "embedded_payload": "payload"},
                    content_sha256=_sha(asset_payload), authority="derived", status="observed", payload=asset_payload)
    evidence = _record("Evidence", evidence_id, store.project_id, refs,
                       evidence_kind="itasca_execution_observation", asset_ref=asset_id,
                       locator={"record_id": asset_id, "field": "payload"}, status="observed")
    with _writer_retry(store, _op_id("itasca.observe", run_id + "\0" + operation_id)):
        # Reload everything under the ResearchStore project writer lock.
        current = _latest_records(store)
        run_record_id = f"itasca.run.{_suffix(run_id)}"
        run_ref = current.get(run_record_id)
        if run_ref is None or run_ref.get("type") != "RunReference":
            raise ValueError("Itasca RunReference disappeared")
        old_asset = current.get(asset_id)
        if old_asset is not None:
            payload = old_asset.get("payload")
            if (payload != asset_payload or old_asset.get("content_sha256") != _sha(asset_payload)
                    or old_asset.get("asset_kind") != "itasca_execution_observation"):
                raise ValueError("operation_id already records a different or damaged observation")
            old_ev = current.get(evidence_id)
            if old_ev != evidence:
                raise ValueError("replayed observation Evidence is damaged")
            loaded = load_itasca_run(root, run_id)
            return {"status": "replayed", "asset_ref": asset_id, "evidence_ref": evidence_id,
                    "run_ref": loaded["run_ref"], "state": loaded["run_ref"]["state"]}
        if run_ref.get("manifest_sha256") != _sha(plan):
            raise ValueError("RunReference plan hash changed")
        bound_task = run_ref.get("task_id")
        if normalized["phase"] == "submission" and run_ref.get("state", "prepared") != "prepared":
            raise ValueError("submission is allowed only once from prepared; recover an uncertain task by task_id status")
        request_task_id = _observation_task_id(normalized)
        if request_task_id is not None:
            _check_task_identity({"_project_root": str(root)}, plan, normalized, bound_task)
            for candidate in current.values():
                if (candidate.get("type") == "RunReference" and candidate.get("id") != run_record_id
                        and candidate.get("engine_session") == plan["engine_session"]
                        and candidate.get("task_id") == request_task_id):
                    raise ValueError("task_id is already associated with another run in this engine_session")
        elif normalized["phase"] != "submission" or normalized["tool_result"]["ok"]:
            raise ValueError("task_id is required for this observation")
        state = run_ref.get("state", "prepared")
        new_state = _status_from_observation(normalized, state)
        if new_state not in _TRANSITIONS.get(state, set()):
            raise ValueError(f"terminal status cannot move from {state} to {new_state}")
        if state in _TERMINAL and new_state != state:
            raise ValueError("terminal status cannot regress or change")
        next_task = bound_task or request_task_id
        if normalized["phase"] == "submission" and not normalized["tool_result"]["ok"]:
            # Keep uncertain/failed submission distinct; it must never trigger an automatic retry.
            new_state = "submission_unknown"
        if state == "submission_unknown" and not normalized["tool_result"]["ok"]:
            new_state = "submission_unknown"
        history = copy.deepcopy(run_ref.get("state_history", []))
        if not history or history[-1].get("state") != new_state:
            history.append({"state": new_state, "at": normalized["captured_at"]})
        revision = int(run_ref["revision"]) + 1
        next_ref = copy.deepcopy(run_ref)
        next_ref.update({"revision": revision, "status": new_state, "state": new_state,
                         "task_id": next_task, "observation_refs": [*run_ref.get("observation_refs", []), evidence_id],
                         "state_history": history})
        ev_relation = _relationship(f"itasca.edge.{op_suffix}.asset", "evidence_derived_from_asset",
                                    evidence, asset, store.project_id, refs)
        run_relation = _relationship(f"itasca.edge.{op_suffix}.run-evidence", "run_produces_evidence",
                                     next_ref, evidence, store.project_id, refs)
        transaction = store.commit(_op_id("itasca.observe", run_id + "\0" + operation_id),
                                   {"role": "host", "model": "itasca_execution"},
                                   [asset, evidence, next_ref], [ev_relation, run_relation],
                                   expected_revisions={run_record_id: int(run_ref["revision"]),
                                       run_ref["plan_asset_ref"]: int(run_ref["plan_asset_revision"])},
                                   lock_held=True)
    return {"status": "recorded", "asset_ref": asset_id, "evidence_ref": evidence_id,
            "state": new_state, "task_id": next_task, "run_ref": next_ref,
            "transaction": transaction}


def load_itasca_run(project_root: str | os.PathLike[str], run_id: str) -> dict[str, Any]:
    """Rebuild one run and its observation history from transaction records."""
    run_id = _id(run_id, "run_id")
    root = _project_root(project_root)
    store = ResearchStore(root)
    run_ref, plan_asset, plan = _plan_for(store, run_id)
    if run_ref.get("plan_asset_ref") != plan_asset["id"] or not isinstance(run_ref.get("route_id"), str):
        raise ValueError("RunReference plan or route identity is damaged")
    observations = []
    expected_ids = list(run_ref.get("observation_refs", []))
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("RunReference observation_refs contains duplicate Evidence IDs")
    all_transactions = store.list_transactions()
    historical_records = {(record["id"], record["revision"]): record
                          for tx in all_transactions for record in tx["records"]}
    for evidence_id in expected_ids:
        bindings = []
        for tx in all_transactions:
            evidence_edges = [edge for edge in tx.get("relationships", [])
                              if edge.get("relation") == "run_produces_evidence"
                              and edge.get("from_id") == run_ref["id"]
                              and edge.get("to_id") == evidence_id]
            for edge in evidence_edges:
                run_revision = historical_records.get((run_ref["id"], edge["from_revision"]))
                evidence_at_revision = next((record for record in tx["records"]
                    if record.get("id") == evidence_id and record.get("revision") == edge["to_revision"]
                    and record.get("type") == "Evidence"), None)
                if (run_revision is None or run_revision.get("type") != "RunReference"
                        or evidence_at_revision is None):
                    continue
                asset_edges = [item for item in tx.get("relationships", [])
                               if item.get("relation") == "evidence_derived_from_asset"
                               and item.get("from_id") == evidence_id
                               and item.get("from_revision") == edge["to_revision"]]
                for asset_edge in asset_edges:
                    asset_at_revision = next((record for record in tx["records"]
                        if record.get("id") == asset_edge["to_id"]
                        and record.get("revision") == asset_edge["to_revision"]
                        and record.get("type") == "Asset"), None)
                    if asset_at_revision is not None:
                        bindings.append((tx, edge, asset_edge, evidence_at_revision, asset_at_revision))
        if len(bindings) != 1:
            raise ValueError("RunReference observation has missing or ambiguous revision-pinned provenance")
        _, _, _, evidence, asset = bindings[0]
        if evidence.get("evidence_kind") != "itasca_execution_observation":
            raise ValueError("RunReference points to missing or invalid observation Evidence")
        if (asset.get("id") != evidence.get("asset_ref")
                or asset.get("asset_kind") != "itasca_execution_observation"
                or not isinstance(asset.get("payload"), dict)
                or asset.get("content_sha256") != _sha(asset["payload"])):
            raise ValueError("execution observation Asset is missing or its payload hash is invalid")
        request = asset["payload"].get("request")
        if not isinstance(request, dict) or request.get("run_id") != run_id:
            raise ValueError("execution observation request is bound to a different run")
        observation = _validate_observation(request.get("observation"), run_ref.get("task_context", "production"))
        if _sha({"run_id": run_id, "operation_id": request.get("operation_id"),
                 "observation": observation, "plan_sha256": run_ref["manifest_sha256"]}) != asset["payload"].get("request_sha256"):
            raise ValueError("execution observation request hash is invalid")
        observations.append(observation)
    return {"run_ref": run_ref, "plan": plan, "observations": observations}


def itasca_run_progress(project_root: str | os.PathLike[str], *, run_id: str) -> dict[str, Any]:
    loaded = load_itasca_run(project_root, run_id)
    run_ref, plan, observations = loaded["run_ref"], loaded["plan"], loaded["observations"]
    outputs = []
    store = ResearchStore(project_root)
    for tx in store.list_transactions():
        for edge in tx.get("relationships", []):
            if edge.get("relation") == "run_produces_evidence" and edge.get("from_id") == run_ref["id"]:
                evidence = store.latest_record(edge.get("to_id"), "Evidence")
                if evidence and evidence.get("evidence_kind") == "itasca_output":
                    outputs.append(evidence["id"])
    return {"run_id": plan["run_id"], "status": run_ref.get("status", "prepared"),
            "run_ref": run_ref, "plan": plan, "observations": observations,
            "state": run_ref.get("state", "prepared"),
            "task_id": run_ref.get("task_id"), "engine_session": plan["engine_session"],
            "observation_count": len(observations), "terminal": run_ref.get("state") in _TERMINAL,
            "submission_unknown": run_ref.get("state") == "submission_unknown",
            "output_evidence_refs": list(dict.fromkeys(outputs)),
            "last_observed_at": observations[-1]["captured_at"] if observations else None}


def render_itasca_run_report(project_root: str | os.PathLike[str], *, run_id: str) -> str:
    loaded = load_itasca_run(project_root, run_id)
    plan = loaded["plan"]
    progress = itasca_run_progress(project_root, run_id=run_id)
    lines = [f"# Itasca execution run `{run_id}`", "",
             f"- Software: FLAC3D {plan['product_version']}",
             f"- Purpose: {plan['purpose']}", f"- Engine session label: `{plan['engine_session']}`",
             f"- Input script: `{plan['script']['path']}` (SHA-256 `{plan['script']['sha256']}`)",
             f"- Output root: `{plan['output_root']}`", f"- Origin: `{plan['origin']}`",
             "- Stop conditions: " + "; ".join(plan["stop_conditions"]),
             f"- Current observed state: **{progress['state']}**",
             f"- External task ID: `{progress['task_id'] or 'unknown'}`", "",
             "## State history", ""]
    lines.extend(f"- `{entry.get('at') or 'not observed'}`: `{entry.get('state', 'unknown')}`"
                 for entry in loaded["run_ref"].get("state_history", []))
    lines.extend(["", "## Recorded MCP observations", ""])
    evidence_refs = loaded["run_ref"].get("observation_refs", [])
    for index, observation in enumerate(loaded["observations"], 1):
        result = observation["tool_result"]
        status = result["data"].get("task_status") if result["ok"] else result["error"].get("code")
        lines.append(f"{index}. `{observation['captured_at']}` {observation['phase']}: `{status or 'unknown'}`")
        if index <= len(evidence_refs):
            lines.append(f"   - Observation Evidence: `{evidence_refs[index - 1]}`")
        if not result["ok"]:
            error = result["error"]
            lines.append(f"   - {error.get('message', 'tool call failed')}")
        elif observation["phase"] == "status":
            pagination = result["data"].get("pagination")
            if pagination is not None:
                lines.append(f"   - Captured log page: `{pagination.get('line_range', 'unspecified')}` of `{pagination.get('total_lines', 'unknown')}` lines; this is a bounded page, not the full log.")
            output = result["data"].get("output")
            if isinstance(output, str):
                preview = output[:2000]
                truncated = len(output) > len(preview)
                longest_ticks = max((len(match.group(0)) for match in re.finditer(r"`+", preview)), default=0)
                fence = "`" * max(3, longest_ticks + 1)
                lines.extend([f"   - Stored output preview: first {len(preview)} characters; truncated: {'yes' if truncated else 'no'}. This is not the complete log.",
                              "", fence, preview, fence])
    if not loaded["observations"]:
        lines.append("No Agent-supplied MCP call result has been recorded.")
    if progress["submission_unknown"]:
        if progress["task_id"]:
            lines.extend(["", "Submission outcome is unknown. This workflow does not resubmit; recovery requires a later status observation for the saved task ID."])
        else:
            lines.extend(["", "Submission outcome is unknown and no task ID was returned. The task cannot be associated or recovered from this record; this workflow will not guess an ID or resubmit."])
    lines.extend(["", "## Limits", "",
                  "- Tool results were supplied by the Agent; this report did not re-query the MCP or engine.",
                  "- Preparation is not execution authorization and is not a complete production `static_check`.",
                  "- Solver completion does not establish convergence quality, scientific validity, or engineering acceptance.",
                  "- No engineering Verification record is created by this workflow.",
                  "- Output references, when present, identify separately recorded `itasca_output` Evidence only.", ""])
    if progress["output_evidence_refs"]:
        lines.extend(["## Recorded output evidence", ""])
        lines.extend(f"- `{ref}`" for ref in progress["output_evidence_refs"])
        lines.append("")
    return "\n".join(lines)
