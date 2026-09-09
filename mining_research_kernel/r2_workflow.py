"""R2 task, evidence, fake-run, and research-map services.

The module is the composition root for the small public R2 surface.  It keeps
the generic task engine and record store unchanged while making all paths
entering persisted records project-relative or caller-labelled.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from flac3d_project import load_config
from mining_research_kernel.cognition import CoreCognition
from mining_research_kernel.records import ResearchStore, ResearchStoreError
from mining_research_kernel.task_engine import (
    TaskEngine, capability_status_for, unavailable_capability,
)
from providers.execution import DisabledExecutionProvider, FakeExecutionProvider
from run_ledger import (
    STAGES,
    create_run,
    inspect_run,
    record_stage,
    resolve_run_dir,
    validate_bundle,
)
from zotero_snapshot import load_snapshot


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", re.ASCII)
_ABS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(_canonical_bytes(value))


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _id(value: Any, field: str) -> str:
    value = _require_string(value, field)
    if not _ID.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def load_json_value(value: Any, field: str) -> Any:
    """Load an inline JSON value or an explicitly caller-selected ``@path``.

    An ``@`` path is deliberately resolved exactly as supplied by the caller;
    no project-root search or implicit path expansion is performed.  The
    operation is read-only.
    """
    if isinstance(value, str) and value.startswith("@"):
        filename = value[1:]
        if not filename:
            raise ValueError(f"{field} @path is empty")
        path = Path(filename).expanduser()
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"cannot read {field} JSON: {exc}") from exc
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{field} must be JSON or @path: {exc}") from exc
    return copy.deepcopy(value)


def _project_path(project_root: Path, value: Any, field: str) -> Path:
    text = _require_string(value, field)
    path = Path(text)
    if path.is_absolute() or text.startswith(("/", "\\")) or ":" in text:
        raise ValueError(f"{field} must be a project-relative path")
    if ".." in path.parts:
        raise ValueError(f"{field} contains an unsafe relative path")
    resolved = (project_root / path).expanduser().resolve()
    root = project_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes project root") from exc
    return resolved


def _public_path(project_root: Path, path: Path, label: str) -> str:
    """Return a stable persisted path without exposing caller private paths."""
    try:
        relative = path.resolve().relative_to(project_root.resolve())
    except ValueError:
        return f"caller:{label or path.name}"
    return relative.as_posix() or "."


def _public_value(value: Any, project_root: Path, field: str = "value") -> Any:
    """Copy JSON data while replacing absolute/local path-looking strings."""
    if isinstance(value, Mapping):
        return {str(key): _public_value(item, project_root, f"{field}.{key}")
                for key, item in value.items()}
    if isinstance(value, list):
        return [_public_value(item, project_root, f"{field}[{index}]")
                for index, item in enumerate(value)]
    if isinstance(value, str):
        text = value.strip()
        if text.startswith(("file:", "/", "\\")) or _ABS_DRIVE.match(text):
            path = Path(text[5:] if text.lower().startswith("file:") else text)
            return f"caller:{path.name or field}"
    return copy.deepcopy(value)


def _task_ids(task_id: str) -> dict[str, str]:
    # Route/question/claim IDs are part of the public contract.  Keep their
    # suffixes within the record store's 64-character ID boundary.
    if len(task_id) > 52:
        raise ValueError("task_id is too long for the R2 route record IDs")
    return {
        "task": task_id,
        "question": f"{task_id}.question.1",
        "claim": f"{task_id}.claim.1",
        "route": f"{task_id}.route.1",
        "asset": f"{task_id}.asset.1",
        "evidence": f"{task_id}.evidence.1",
    }


def _edge_id(task_id: str, label: str) -> str:
    value = f"{task_id}.{label}.1"
    return value if len(value) <= 64 else "edge." + hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _source_ref(*parts: Any) -> str:
    return ":".join(_require_string(str(part), "source reference") for part in parts)


def _record(record_type: str, record_id: str, project_id: str, source_refs: list[str], **fields: Any) -> dict[str, Any]:
    value = {
        "schema_version": 1, "type": record_type, "id": record_id, "revision": 1,
        "project_id": project_id, "scope": {"project_id": project_id},
        "source_refs": source_refs,
    }
    value.update(fields)
    return value


def _relationship(relationship_id: str, relation: str, from_record: Mapping[str, Any],
                  to_record: Mapping[str, Any], project_id: str, source_refs: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1, "relationship_id": relationship_id, "revision": 1,
        "project_id": project_id, "relation": relation,
        "from_id": from_record["id"], "from_revision": from_record["revision"],
        "to_id": to_record["id"], "to_revision": to_record["revision"],
        "source_refs": source_refs,
    }


def _load_project(project_root: str | os.PathLike[str]) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    root = Path(project_root).expanduser().resolve()
    config = load_config(root)
    if config.get("product") == "synthetic":
        # The second-domain fixture has no concrete adapter. Its workflow
        # builder consumes this generic project contract directly.
        project = copy.deepcopy(config)
    else:
        from adapters.flac3d import discover
        discovered = discover(root)
        project = copy.deepcopy(config)
        project.update({key: copy.deepcopy(value) for key, value in discovered.items()
                        if key not in {"assets", "diagnostics", "verification_gates"}})
    return root, config, project


def _request_for_engine(request: Mapping[str, Any], task_id: str, route_id: str) -> dict[str, Any]:
    value = copy.deepcopy(dict(request))
    value["task_id"] = task_id
    value.setdefault("task_type", "mining_research_kernel.task.static_check")
    value.setdefault("maturity", "exploratory")
    value.setdefault("max_runs", 1)
    value["route_id"] = route_id
    if value.get("task_context") == "synthetic":
        value.setdefault("provider", "execution")
    routes = value.get("routes")
    if routes is not None and routes != [route_id]:
        raise ValueError("R2 task-start accepts exactly one route")
    value["routes"] = [route_id]
    value["input"] = _public_value(value.get("input", {}), Path.cwd())
    value.pop("literature_evidence", None)
    return value


def _workflow_builder(request: Mapping[str, Any]):
    value = request.get("workflow_id", request.get("workflow"))
    if value in {"synthetic", "mining_research_kernel.workflow.synthetic"}:
        from workflows.synthetic import build_synthetic_workflow_pack
        return build_synthetic_workflow_pack
    if value in {None, "flac3d", "mining_research_kernel.workflow.flac3d"}:
        from workflows.flac3d import build_flac3d_workflow_pack
        return build_flac3d_workflow_pack
    raise ValueError(f"unknown workflow builder: {value}")


def _engine_for(project: Mapping[str, Any], request: Mapping[str, Any], *, fake: bool,
                documentation_result: Mapping[str, Any] | None = None,
                fake_provider: Any | None = None, workflow_builder: Any | None = None) -> TaskEngine:
    context = request.get("task_context", "production")
    provider = fake_provider if fake_provider is not None else (
        FakeExecutionProvider() if fake or context == "synthetic" else DisabledExecutionProvider()
    )
    providers = {"execution": provider}
    pack = (workflow_builder or _workflow_builder(request))(project, request, providers)
    return TaskEngine(project, pack, providers, documentation_result=documentation_result)


def _current_workflow_pack(root: Path, packet: Mapping[str, Any]) -> Mapping[str, Any] | None:
    """Build a read-only current capability view for an older TaskPacket."""
    try:
        _loaded_root, _config, project = _load_project(root)
        request = {
            "workflow_id": packet.get("workflow_id"),
            "task_type": packet.get("task_type"),
            "task_context": packet.get("task_context", "production"),
            "verification_gates": packet.get("verification_gates", []),
        }
        provider = (FakeExecutionProvider()
                    if request["task_context"] == "synthetic"
                    else DisabledExecutionProvider())
        return _workflow_builder(request)(project, request, {"execution": provider})
    except (OSError, TypeError, ValueError, KeyError):
        return None


def _task_failure_gate(root: Path, task_id: str, route_id: str,
                       request: Mapping[str, Any]) -> dict[str, Any]:
    """Load related failures from the durable store using task-start scope."""
    cognition = CoreCognition(root)
    related: set[str] = set()
    blocking: set[str] = set()
    scopes = [{"task_id": task_id}, {"route_id": route_id},
              {"object_ref": task_id}, {"object_ref": route_id}]
    object_ref = request.get("object_ref")
    if isinstance(object_ref, str) and object_ref.strip():
        scopes.append({"object_ref": object_ref.strip()})
    for scope in scopes:
        gate = cognition.failure_gate(**scope)
        related.update(gate["related_failure_ids"])
        blocking.update(gate["failure_ids"])
    blocking_ids = sorted(blocking)
    return {"status": "blocked" if blocking_ids else "clear",
            "failure_ids": blocking_ids,
            "related_failure_ids": sorted(related),
            "resume_condition": "resolve_or_scope_away_from_related_failures" if blocking_ids else None}


def _literature_records(root: Path, project_id: str, task_id: str, request: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    evidence_input = request.get("literature_evidence")
    if evidence_input is None:
        return [], []
    if not isinstance(evidence_input, Mapping):
        raise ValueError("literature_evidence must be an object")
    snapshot_path = _project_path(root, evidence_input.get("snapshot_path"), "literature_evidence.snapshot_path")
    source_path = _project_path(root, evidence_input.get("source_path"), "literature_evidence.source_path")
    item_key = _require_string(evidence_input.get("item_key"), "literature_evidence.item_key")
    locator = evidence_input.get("locator")
    if not isinstance(locator, Mapping) or not locator:
        raise ValueError("literature_evidence.locator must be a non-empty object")
    question_statement = _require_string(evidence_input.get("question_statement"), "literature_evidence.question_statement")
    claim_statement = _require_string(evidence_input.get("claim_statement"), "literature_evidence.claim_statement")
    if not snapshot_path.is_file():
        raise ValueError(f"literature snapshot does not exist: {snapshot_path}")
    if not source_path.is_file():
        raise ValueError(f"literature source does not exist: {source_path}")
    snapshot_bytes = snapshot_path.read_bytes()
    snapshot = load_snapshot(snapshot_path)
    item = next((candidate for candidate in snapshot["items"] if candidate["item_key"] == item_key), None)
    if item is None:
        raise ValueError(f"literature snapshot has no exact item_key: {item_key}")
    source_bytes = source_path.read_bytes()
    snapshot_hash = _sha256_bytes(snapshot_bytes)
    source_hash = _sha256_bytes(source_bytes)
    ids = _task_ids(task_id)
    refs = [_source_ref("task", task_id), _source_ref("zotero-item", item_key),
            _source_ref("local-source", _public_path(root, source_path, source_path.name))]
    source_locator = {
        "snapshot_path": _public_path(root, snapshot_path, snapshot_path.name),
        "snapshot_sha256": snapshot_hash,
        "snapshot_instance_id": snapshot["instance_id"],
        "item_key": item_key,
        "item_version": item["version"],
        "source_path": _public_path(root, source_path, source_path.name),
        "source_sha256": source_hash,
        "locator": _public_value(locator, root, "literature_evidence.locator"),
    }
    question = _record("ResearchQuestion", ids["question"], project_id, refs,
                       statement=question_statement, status="active")
    claim = _record("Claim", ids["claim"], project_id, refs,
                    statement=claim_statement, status="proposed")
    asset = _record("Asset", ids["asset"], project_id, refs,
                    asset_kind="zotero_local_source", locator=source_locator,
                    content_sha256=source_hash, authority="derived", status="observed",
                    item_key=item_key, item_version=item["version"])
    evidence = _record("Evidence", ids["evidence"], project_id, refs,
                       evidence_kind="document", asset_ref=asset["id"],
                       locator=source_locator, status="observed")
    relationships = [
        _relationship(_edge_id(task_id, "evidence-derived"), "evidence_derived_from_asset", evidence, asset, project_id, refs),
        _relationship(_edge_id(task_id, "source-documents"), "source_documents_claim", evidence, claim, project_id, refs),
    ]
    # The statements are checked against the top-level task request so a
    # literature object cannot silently address a different question.
    if question_statement != request["question_statement"] or claim_statement != request["claim_statement"]:
        raise ValueError("literature evidence question/claim must match task request")
    return [question, claim, asset, evidence], relationships


def task_start(project_root: str | os.PathLike[str], request: Mapping[str, Any] | str,
               documentation_result: Mapping[str, Any] | str | None = None) -> dict[str, Any]:
    """Start a task; documentation_result is reserved for trusted Host evidence.

    Hosts must obtain that argument from their DocumentationProvider, never
    forward an Agent request field or arbitrary CLI JSON into it.
    """
    root, config, project = _load_project(project_root)
    request_value = load_json_value(request, "request-json")
    if not isinstance(request_value, Mapping):
        raise ValueError("request-json must contain a JSON object")
    request_value = copy.deepcopy(dict(request_value))
    if request_value.get("workflow_id") == "synthetic":
        request_value["workflow_id"] = "mining_research_kernel.workflow.synthetic"
    elif request_value.get("workflow_id") == "flac3d":
        request_value["workflow_id"] = "mining_research_kernel.workflow.flac3d"
    task_id = _id(request_value.get("task_id", "task-1"), "task_id")
    ids = _task_ids(task_id)
    question_statement = _require_string(request_value.get("question_statement"), "question_statement")
    claim_statement = _require_string(request_value.get("claim_statement"), "claim_statement")
    request_value["question_statement"] = question_statement
    request_value["claim_statement"] = claim_statement
    request_value["task_id"] = task_id
    route_id = ids["route"]
    engine_request = _request_for_engine(request_value, task_id, route_id)
    failure_gate = _task_failure_gate(root, task_id, route_id, request_value)
    engine_request["refs"] = {"failures": failure_gate["related_failure_ids"]}
    documentation = None if documentation_result is None else load_json_value(documentation_result, "documentation-result")
    if documentation is not None and not isinstance(documentation, Mapping):
        raise ValueError("documentation-result must contain a JSON object")
    engine = _engine_for(project, engine_request, fake=False, documentation_result=documentation,
                         workflow_builder=_workflow_builder(request_value))
    packet = engine.start(engine_request)
    if failure_gate["status"] == "blocked":
        engine._blocked(packet, "unresolved_failure_gate", failure_gate["resume_condition"])
    source_refs = [_source_ref("task", task_id), _source_ref("operation", f"task-start.{task_id}")]
    question = _record("ResearchQuestion", ids["question"], config["project_id"], source_refs,
                       statement=question_statement, status="active")
    claim = _record("Claim", ids["claim"], config["project_id"], source_refs,
                    statement=claim_statement, status="proposed")
    route = _record("Route", route_id, config["project_id"], source_refs,
                    status="active", route_id=route_id, question_id=question["id"], research_question_id=question["id"], hypothesis_id=None,
                    claim_id=claim["id"], task_id=task_id, parent_route_id=None,
                    supersedes_route_id=None,
                    workflow_id=packet["workflow_id"],
                    method_id=_method_for(packet["task_type"], packet["workflow_id"]),
                    budget=int(packet["max_runs"]), runs_used=0,
                    inputs=[_public_value(request_value.get("input", {}), root)],
                    expected_evidence=["task packet and bounded execution observation"],
                    assigned_role="execution_agent", verification_gates=packet.get("verification_gates", []),
                    stop_conditions=packet.get("stop_conditions", []), outputs=[], reservations=[],
                    write_set=["research/records", "runs"], stop_reason=None)
    records = [question, claim, route,
               _record("TaskState", task_id, config["project_id"], source_refs,
                       task_id=task_id, state=packet["state"], packet=packet,
                       operation_results={})]
    literature_records, literature_relationships = _literature_records(root, config["project_id"], task_id, request_value)
    # Replace duplicate question/claim records with the exact same objects and
    # add only the asset/evidence records supplied by the literature bridge.
    if literature_records:
        records.extend(literature_records[2:])
    relationships = [
        _relationship(_edge_id(task_id, "route-addresses"), "route_addresses_question", route, question, config["project_id"], source_refs),
        _relationship(_edge_id(task_id, "route-targets-claim"), "route_targets_claim", route, claim, config["project_id"], source_refs),
        *literature_relationships,
    ]
    store = ResearchStore(root)
    operation_id = f"task-start.{task_id}"
    store.commit(operation_id, {"role": "planning_agent", "model": "r2.workflow"}, records, relationships)
    latest = store.latest_record(task_id, "TaskState")
    if latest is None:
        raise ResearchStoreError("task-start committed without TaskState")
    return copy.deepcopy(latest["packet"])


def _method_for(task_type: str, workflow_id: str = "mining_research_kernel.workflow.flac3d") -> str:
    kind = task_type.rsplit(".", 1)[-1].casefold()
    family = "synthetic" if workflow_id.endswith(".synthetic") else "flac3d"
    return {
        "fake_execution": f"mining_research_kernel.method.{family}.fake_execution",
        "execution": f"mining_research_kernel.method.{family}.fake_execution",
        "static_check": f"mining_research_kernel.method.{family}.static_check",
        "syntax_change": f"mining_research_kernel.method.{family}.syntax_verification",
    }.get(kind, f"mining_research_kernel.method.{family}.static_check")


def task_inspect(project_root: str | os.PathLike[str], task_id: str) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    task_id = _id(task_id, "task_id")
    latest = ResearchStore(root).latest_record(task_id, "TaskState")
    if latest is None:
        raise ValueError(f"unknown task: {task_id}")
    packet = copy.deepcopy(latest["packet"])
    current_pack = _current_workflow_pack(root, packet)
    current_statuses = (copy.deepcopy(current_pack.get("capability_statuses", {}))
                        if isinstance(current_pack, Mapping) else {})
    if current_statuses == packet.get("capability_statuses", {}):
        return packet

    # Keep the persisted packet untouched while making an obsolete executable
    # action visibly safe in the current inspection view.
    packet["historical_next_action"] = copy.deepcopy(packet.get("next_action"))
    packet["historical_capability_statuses"] = copy.deepcopy(packet.get("capability_statuses", {}))
    packet["current_capability_statuses"] = current_statuses
    current_next_action = copy.deepcopy(packet.get("next_action"))
    status = capability_status_for(current_pack or {}, packet.get("task_type", ""))
    unavailable = unavailable_capability(status)
    if unavailable is not None and isinstance(current_next_action, Mapping) and current_next_action.get("executable"):
        reason, resume = unavailable
        current_next_action = {
            "action_id": None, "executable": False, "input_refs": [], "expected_outputs": [],
            "preconditions": [], "reason": reason, "resume_condition": resume,
        }
        packet["next_action"] = current_next_action
    packet["current_next_action"] = current_next_action
    return packet


def _latest_persisted_records(store: ResearchStore) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for transaction in store.list_transactions():
        for record in transaction["records"]:
            if record["revision"] >= latest.get(record["id"], {"revision": 0})["revision"]:
                latest[record["id"]] = copy.deepcopy(record)
    return latest


def _latest_persisted_relationships(store: ResearchStore) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for transaction in store.list_transactions():
        for relationship in transaction["relationships"]:
            current = latest.get(relationship["relationship_id"])
            if current is None or relationship["revision"] >= current["revision"]:
                latest[relationship["relationship_id"]] = copy.deepcopy(relationship)
    return list(latest.values())


def _completion_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or not all(_is_nonempty_string(item) for item in value):
        raise ValueError(f"{field} must be a non-empty list of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")
    return [item.strip() for item in value]


def _completion_reference_map(value: Any, field: str, route_ids: list[str], *, lists: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != set(route_ids):
        raise ValueError(f"{field} must provide exactly one entry for every packet route")
    result: dict[str, Any] = {}
    for route_id in route_ids:
        if lists:
            item = value[route_id]
            if isinstance(item, str):
                item = [item]
            result[route_id] = _completion_string_list(item, f"{field}.{route_id}")
        else:
            result[route_id] = _id(value[route_id], f"{field}.{route_id}")
    return result


def _required_gate_ids(packet: Mapping[str, Any]) -> list[str]:
    declared = packet.get("verification_gates", packet.get("required_gates", []))
    if isinstance(declared, str):
        declared = [declared]
    if not isinstance(declared, (list, tuple)):
        raise ValueError("task packet verification_gates must be a list")
    gates = [gate for gate in declared if _is_nonempty_string(gate)]
    if packet.get("documentation_required") is True and "documentation" not in gates:
        gates.append("documentation")
    statuses = packet.get("gate_statuses", {})
    if not isinstance(statuses, Mapping):
        raise ValueError("task packet gate_statuses must be an object")
    for gate, value in statuses.items():
        if not isinstance(gate, str) or not gate.strip():
            raise ValueError("task packet gate_statuses has an invalid gate id")
        if not isinstance(value, Mapping):
            raise ValueError(f"task packet gate_statuses.{gate} must be an object")
        if value.get("applicable") is True and gate not in gates:
            gates.append(gate)
    for gate in gates:
        status = statuses.get(gate)
        if isinstance(status, Mapping):
            applicable = status.get("applicable", True)
            if applicable is False:
                raise ValueError(f"task packet marks required gate not applicable: {gate}")
            if status.get("status") == "NOT_APPLICABLE":
                raise ValueError(f"task packet has contradictory required gate status: {gate}")
    return list(dict.fromkeys(gates))


def _completion_gate_coverage(value: Any, field: str, route_ids: list[str],
                              packet: Mapping[str, Any]) -> dict[str, dict[str, list[dict[str, str]]]]:
    if not isinstance(value, Mapping) or set(value) != set(route_ids):
        raise ValueError(f"{field} must provide exactly one entry for every packet route")
    required = _required_gate_ids(packet)
    result: dict[str, dict[str, list[dict[str, str]]]] = {}
    for route_id in route_ids:
        route_coverage = value[route_id]
        if not isinstance(route_coverage, Mapping) or set(route_coverage) != set(required):
            raise ValueError(f"{field}.{route_id} must cover exactly the current required gates")
        normalized: dict[str, list[dict[str, str]]] = {}
        for gate in required:
            entries = route_coverage[gate]
            if not isinstance(entries, list) or not entries:
                raise ValueError(f"{field}.{route_id}.{gate} must be a non-empty list")
            normalized[gate] = []
            for index, entry in enumerate(entries):
                if not isinstance(entry, Mapping) or set(entry) != {"verification_id", "verification_gate_id"}:
                    raise ValueError(
                        f"{field}.{route_id}.{gate}[{index}] must identify the Verification and its record gate_id")
                normalized[gate].append({
                    "verification_id": _id(entry["verification_id"],
                                            f"{field}.{route_id}.{gate}[{index}].verification_id"),
                    "verification_gate_id": _require_string(
                        entry["verification_gate_id"],
                        f"{field}.{route_id}.{gate}[{index}].verification_gate_id"),
                })
        seen: dict[str, str] = {}
        for gate, entries in normalized.items():
            for entry in entries:
                verification_id = entry["verification_id"]
                previous_gate = seen.get(verification_id)
                if previous_gate is not None:
                    raise ValueError(
                        f"{field}.{route_id} cannot use one Verification for multiple gates: "
                        f"{previous_gate}, {gate}")
                seen[verification_id] = gate
        result[route_id] = normalized
    return result


def _normalize_task_completion(completion: Mapping[str, Any] | str, packet: Mapping[str, Any]) -> dict[str, Any]:
    value = load_json_value(completion, "completion-json")
    if not isinstance(value, Mapping):
        raise ValueError("completion-json must contain an object")
    allowed = {"route_ids", "run_reference_ids", "verification_ids", "verification_gate_coverage",
               "evidence_refs", "output_refs"}
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError("completion-json has unsupported fields: " + ", ".join(unknown))
    route_ids = _completion_string_list(value.get("route_ids"), "route_ids")
    packet_routes = packet.get("routes")
    if not isinstance(packet_routes, list) or not packet_routes:
        raise ValueError("task packet has no routes to complete")
    packet_routes = _completion_string_list(packet_routes, "packet routes")
    if route_ids != packet_routes:
        raise ValueError("route_ids must explicitly match all packet routes in order")
    verification_ids = _completion_reference_map(value.get("verification_ids"), "verification_ids", route_ids, lists=True)
    verification_gate_coverage = _completion_gate_coverage(
        value.get("verification_gate_coverage"), "verification_gate_coverage", route_ids, packet)
    for route_id in route_ids:
        covered_ids = {entry["verification_id"]
                       for entries in verification_gate_coverage[route_id].values()
                       for entry in entries}
        if set(verification_ids[route_id]) != covered_ids:
            raise ValueError(f"verification_ids must exactly match verification_gate_coverage: {route_id}")
    return {
        "route_ids": route_ids,
        "run_reference_ids": _completion_reference_map(value.get("run_reference_ids"), "run_reference_ids", route_ids),
        "verification_ids": verification_ids,
        "verification_gate_coverage": verification_gate_coverage,
        "evidence_refs": _completion_reference_map(value.get("evidence_refs"), "evidence_refs", route_ids, lists=True),
        "output_refs": _completion_reference_map(value.get("output_refs"), "output_refs", route_ids, lists=True),
    }


def _task_completion_result_matches(existing: Mapping[str, Any], completion: Mapping[str, Any]) -> bool:
    return existing.get("status") == "completed" and existing.get("completion") == completion


def task_complete(project_root: str | os.PathLike[str], task_id: str, operation_id: str,
                  completion: Mapping[str, Any] | str) -> dict[str, Any]:
    """Persist completion after checking the current research records."""
    root = Path(project_root).expanduser().resolve()
    task_id = _id(task_id, "task_id")
    operation_id = _id(operation_id, "operation_id")
    store = ResearchStore(root)
    prior = store.latest_record(task_id, "TaskState")
    if prior is None:
        raise ValueError(f"unknown task: {task_id}")
    prior_results = prior.get("operation_results", {})
    if not isinstance(prior_results, Mapping):
        raise ValueError("TaskState operation_results must be an object")
    existing = prior_results.get(operation_id)
    try:
        normalized = _normalize_task_completion(completion, prior["packet"])
    except ValueError:
        if isinstance(existing, Mapping):
            raise ValueError("operation_id was already used with different completion content")
        raise
    if isinstance(existing, Mapping):
        if not _task_completion_result_matches(existing, normalized):
            raise ValueError("operation_id was already used with different completion content")
        return copy.deepcopy(prior["packet"])
    current_pack = _current_workflow_pack(root, prior["packet"])
    current_capabilities = (current_pack.get("capability_statuses", {})
                            if isinstance(current_pack, Mapping) else prior["packet"].get("capability_statuses", {}))
    if not isinstance(current_capabilities, Mapping):
        current_capabilities = {}
    for gate_id in _required_gate_ids(prior["packet"]):
        unavailable = unavailable_capability(current_capabilities.get(gate_id))
        if unavailable is not None:
            reason, _resume = unavailable
            raise ValueError(f"required capability unavailable: {reason}")
    if prior.get("state") == "completed":
        raise ValueError("task is already completed; use the original operation_id for idempotent recovery")
    if prior.get("state") not in {"ready", "running"}:
        raise ValueError(f"task cannot be completed from state {prior.get('state')}")

    latest = _latest_persisted_records(store)
    relationships = _latest_persisted_relationships(store)
    routes = [latest.get(route_id) for route_id in normalized["route_ids"]]
    for route_id, route in zip(normalized["route_ids"], routes):
        if route is None or route.get("type") != "Route":
            raise ValueError(f"completion route is not a current Route record: {route_id}")
        if route.get("project_id") != store.project_id or route.get("task_id") != task_id:
            raise ValueError(f"completion route does not belong to task: {route_id}")
        if route.get("status") != "completed":
            raise ValueError(f"required route is not completed: {route_id}")
        outputs = route.get("outputs")
        if not isinstance(outputs, list) or not outputs:
            raise ValueError(f"completed route has no recorded research outputs: {route_id}")
        if set(normalized["output_refs"][route_id]) != set(outputs) or len(normalized["output_refs"][route_id]) != len(outputs):
            raise ValueError(f"output_refs must exactly record the current Route outputs: {route_id}")

    packet_route_set = set(normalized["route_ids"])
    extra_routes = [record["id"] for record in latest.values()
                    if record.get("type") == "Route" and record.get("task_id") == task_id
                    and record["id"] not in packet_route_set]
    if extra_routes:
        raise ValueError("task has Route records outside packet routes; complete the explicit packet route set")

    def has_relation(relation: str, from_id: str, from_revision: int,
                     to_id: str, to_revision: int) -> bool:
        return any(edge.get("relation") == relation
                   and edge.get("from_id") == from_id
                   and edge.get("from_revision") == from_revision
                   and edge.get("to_id") == to_id
                   and edge.get("to_revision") == to_revision
                   for edge in relationships)

    referenced_records: dict[str, Any] = {}
    for route_id, route in zip(normalized["route_ids"], routes):
        run_ref_id = normalized["run_reference_ids"][route_id]
        run_ref = latest.get(run_ref_id)
        if run_ref is None or run_ref.get("type") != "RunReference":
            raise ValueError(f"run reference is not a current RunReference record: {run_ref_id}")
        if run_ref.get("project_id") != store.project_id or run_ref.get("route_id") != route_id:
            raise ValueError(f"RunReference is not associated with route: {run_ref_id}")
        if run_ref.get("status") not in {"accepted", "completed"}:
            raise ValueError(f"RunReference is not in an accepted terminal state: {run_ref_id}")
        required_refs = {f"task:{task_id}", f"route:{route_id}", f"run:{run_ref.get('run_id')}"}
        if not required_refs.issubset(set(run_ref.get("source_refs", []))):
            raise ValueError(f"RunReference lacks task/route/run provenance: {run_ref_id}")
        if not has_relation("run_executes_route", run_ref_id, run_ref["revision"], route_id, route["revision"]):
            raise ValueError(f"RunReference is not linked to the current Route: {run_ref_id}")
        run_id = run_ref.get("run_id")
        run_root = root / "research" / "runs"
        try:
            run_errors = validate_bundle(run_root, run_id)
            run_manifest = inspect_run(run_root, run_id) if not run_errors else None
        except Exception as exc:
            raise ValueError(f"Run cannot be read or validated: {run_id}: {exc}") from exc
        if run_errors or not isinstance(run_manifest, Mapping) or run_manifest.get("status") != "accepted":
            raise ValueError(f"Run is not an accepted valid terminal run: {run_id}")

        gate_coverage = normalized["verification_gate_coverage"][route_id]
        verification_ids = normalized["verification_ids"][route_id]
        verification_records: dict[str, Mapping[str, Any]] = {}
        for verification_id in verification_ids:
            verification = latest.get(verification_id)
            if verification is None or verification.get("type") != "Verification":
                raise ValueError(f"verification is not a current Verification record: {verification_id}")
            if verification.get("project_id") != store.project_id or verification.get("status") not in {"PASS", "PASS_WITH_NOTES"}:
                raise ValueError(f"verification does not satisfy task completion: {verification_id}")
            if not has_relation("verification_checks_run", verification_id, verification["revision"], run_ref_id, run_ref["revision"]):
                raise ValueError(f"verification is not linked to the selected RunReference: {verification_id}")
            if not {f"task:{task_id}", f"route:{route_id}", f"run:{run_id}"}.issubset(set(verification.get("source_refs", []))):
                raise ValueError(f"verification lacks task/route/run provenance: {verification_id}")
            if not _is_nonempty_string(verification.get("gate_id")):
                raise ValueError(f"verification lacks a structured gate_id: {verification_id}")
            verification_records[verification_id] = verification

        gate_coverage_refs = {}
        for gate_id, coverage_entries in gate_coverage.items():
            gate_coverage_refs[gate_id] = []
            for entry in coverage_entries:
                verification_id = entry["verification_id"]
                verification = verification_records[verification_id]
                if verification.get("gate_id") != gate_id:
                    raise ValueError(
                        f"Verification does not cover the current packet gate: {verification_id}")
                if verification.get("gate_id") != entry["verification_gate_id"]:
                    raise ValueError(
                        f"gate coverage record gate_id does not match current Verification: {verification_id}")
                gate_coverage_refs[gate_id].append({
                    "verification_id": verification_id,
                    "verification_revision": verification["revision"],
                    "verification_gate_id": verification["gate_id"],
                })

        evidence_ids = normalized["evidence_refs"][route_id]
        run_evidence_count = 0
        route_claim_ids = {edge["to_id"] for edge in relationships
                           if edge.get("relation") == "route_targets_claim"
                           and edge.get("from_id") == route_id
                           and isinstance(edge.get("from_revision"), int)
                           and edge.get("from_revision") <= route["revision"]}
        for evidence_id in evidence_ids:
            evidence = latest.get(evidence_id)
            if evidence is None or evidence.get("type") != "Evidence":
                raise ValueError(f"evidence reference is not a current Evidence record: {evidence_id}")
            run_link = has_relation("run_produces_evidence", run_ref_id, run_ref["revision"], evidence_id, evidence["revision"])
            claim_link = any(edge.get("relation") == "source_documents_claim"
                             and edge.get("from_id") == evidence_id
                             and edge.get("from_revision") == evidence["revision"]
                             and edge.get("to_id") in route_claim_ids
                             for edge in relationships)
            if not run_link and not claim_link:
                raise ValueError(f"evidence is not linked to the selected Run or Route claim: {evidence_id}")
            if run_link:
                run_evidence_count += 1
        if run_evidence_count == 0:
            raise ValueError(f"completion requires evidence produced by the selected Run: {route_id}")
        verification_refs = [{"id": verification_id, "revision": verification["revision"],
                              "gate_id": verification.get("gate_id"), "status": verification["status"]}
                             for verification_id, verification in verification_records.items()]
        referenced_records[route_id] = {
            "route": {"id": route_id, "revision": route["revision"]},
            "run_reference": {"id": run_ref_id, "revision": run_ref["revision"], "run_id": run_id,
                              "status": run_ref["status"]},
            "verification": verification_refs[0] if len(verification_refs) == 1 else verification_refs,
            "verifications": verification_refs,
            "gate_coverage": gate_coverage_refs,
            "evidence": [{"id": evidence_id, "revision": latest[evidence_id]["revision"]} for evidence_id in evidence_ids],
            "output_refs": copy.deepcopy(normalized["output_refs"][route_id]),
        }

    next_packet = copy.deepcopy(prior["packet"])
    next_packet["state"] = "completed"
    next_packet["next_action"] = {
        "action_id": None, "executable": False, "input_refs": [], "expected_outputs": [],
        "preconditions": [], "reason": "task_completed", "resume_condition": None,
    }
    next_packet.setdefault("history", []).append({
        "event": "state_transition", "from": prior["state"], "to": "completed",
        "reason": "verified_research_scope_complete", "resume": False,
    })
    operation_result = {
        "status": "completed", "task_id": task_id, "completion": copy.deepcopy(normalized),
        "record_refs": referenced_records,
    }
    operation_results = copy.deepcopy(dict(prior_results))
    operation_results[operation_id] = operation_result
    source_refs = list(dict.fromkeys([
        *prior.get("source_refs", []), f"task:{task_id}", f"operation:{operation_id}",
        *[f"route:{route_id}" for route_id in normalized["route_ids"]],
        *[f"runref:{refs['run_reference']['id']}" for refs in referenced_records.values()],
        *[f"verification:{verification['id']}" for refs in referenced_records.values()
          for verification in refs["verifications"]],
        *[f"evidence:{evidence['id']}" for refs in referenced_records.values() for evidence in refs["evidence"]],
    ]))
    task_record = _record(
        "TaskState", task_id, store.project_id, source_refs,
        revision=int(prior["revision"]) + 1, task_id=task_id, state="completed",
        packet=next_packet, operation_results=operation_results,
    )
    try:
        transaction = store.commit(
            operation_id, {"role": "acceptance_agent", "model": "r2.workflow"}, [task_record],
            expected_revisions={task_id: int(prior["revision"])},
        )
    except ResearchStoreError:
        latest_after_race = store.latest_record(task_id, "TaskState")
        raced = latest_after_race.get("operation_results", {}).get(operation_id) if latest_after_race else None
        if isinstance(raced, Mapping) and _task_completion_result_matches(raced, normalized):
            return copy.deepcopy(latest_after_race["packet"])
        raise
    result = copy.deepcopy(next_packet)
    result["operation_id"] = operation_id
    result["operation_result"] = copy.deepcopy(operation_result)
    result["transaction"] = transaction
    return result


def _stage_operation_id(operation_id: str, stage: str) -> str:
    return f"r2-{hashlib.sha256((operation_id + "|" + stage).encode("utf-8")).hexdigest()[:40]}"


def _record_complete_stages(runs_root: Path, run_id: str, operation_id: str,
                            task_id: str, route_id: str, fixture_id: str,
                            packet_digest: str, result: Mapping[str, Any]) -> dict[str, Any]:
    stage_data = {
        "exploration": {"observations": ["loaded persisted task packet"], "route_id": route_id},
        "plan": {"steps": ["execute one explicitly selected synthetic fixture"],
                  "risks": ["fake result is not FLAC3D, numerical, physical, or engineering validation"]},
        "execution": {"commands": [f"synthetic-fixture:{fixture_id}"], "return_codes": [0],
                       "output_paths": [f"research/runs/{run_id}/synthetic-result.json"]},
        "test": {"test_results": ["fake provider returned COMPLETED", "result is canonical-hashable"]},
        "acceptance": {"verdict": "PASS", "scope": "kernel_workflow_only",
                       "test_evidence": ["run ledger canonical stages completed", "synthetic result recorded with hash"],
                       "unresolved_risks": ["no FLAC3D execution validation", "no numerical validation",
                                            "no physical validation", "no engineering validation"]},
    }
    inputs = {"task_id": task_id, "route_id": route_id, "fixture_id": fixture_id,
              "task_packet_sha256": packet_digest}
    outputs = {"fixture_id": fixture_id, "result_status": result.get("status"),
               "result_sha256": _sha256_json(result)}
    for stage in STAGES:
        manifest = inspect_run(runs_root, run_id)
        if manifest.get("status") == "accepted":
            break
        if manifest.get("status") in {"failed", "waiting_for_human", "rejected"}:
            raise ValueError(f"cannot complete existing run in status {manifest.get('status')}")
        if manifest.get("current_stage") != stage:
            continue
        record_stage(runs_root, run_id, stage, {
            "exploration": "planning_agent", "plan": "planning_agent",
            "execution": "execution_agent", "test": "execution_agent",
            "acceptance": "acceptance_agent",
        }[stage], "completed", stage_data[stage], model="r2.workflow",
                     inputs=inputs, outputs=outputs, operation_id=_stage_operation_id(operation_id, stage))
    return inspect_run(runs_root, run_id)


def task_run_fake(project_root: str | os.PathLike[str], task_id: str,
                  operation_id: str, fixture_id: str, *,
                  fake_provider: Any | None = None) -> dict[str, Any]:
    root, config, project = _load_project(project_root)
    task_id = _id(task_id, "task_id")
    operation_id = _id(operation_id, "operation_id")
    fixture_id = _require_string(fixture_id, "fixture_id")
    store = ResearchStore(root)
    prior = store.latest_record(task_id, "TaskState")
    if prior is None:
        raise ValueError(f"unknown task: {task_id}")
    prior_results = prior.get("operation_results", {})
    if not isinstance(prior_results, Mapping):
        raise ValueError("TaskState operation_results must be an object")
    existing = prior_results.get(operation_id)
    if isinstance(existing, Mapping):
        if existing.get("fixture_id") != fixture_id:
            raise ValueError("operation_id was already used with a different fixture_id")
        if existing.get("status") in {"completed", "failed", "unknown"}:
            packet = copy.deepcopy(prior["packet"])
            return {**packet, "run_id": existing.get("run_id"), "operation_result": copy.deepcopy(existing)}
        raise ValueError("operation_id has a persisted reservation and requires reconciliation")
    packet = copy.deepcopy(prior["packet"])
    if packet.get("task_context") != "synthetic":
        raise ValueError("production tasks cannot use task-run-fake")
    if packet.get("state") not in {"ready", "failed"}:
        raise ValueError(f"task is not runnable: {packet.get('state')}")
    run_id = f"run-{hashlib.sha256((task_id + '|' + operation_id).encode('utf-8')).hexdigest()[:32]}"
    runs_root = root / "research" / "runs"
    # Reject a pre-existing link before charging the budget or dispatching.
    # Persistence still checks again; concurrent directory swaps are outside
    # the local v0.1.0 boundary.
    resolve_run_dir(runs_root, run_id)
    packet["fixture_id"] = fixture_id
    engine_request = {
        "task_id": task_id, "project_id": config["project_id"],
        "workflow_id": packet["workflow_id"], "task_type": packet["task_type"],
        "maturity": packet["maturity"], "max_runs": packet["max_runs"],
        "task_context": "synthetic", "fixture_id": fixture_id,
        "route_id": packet["routes"][0] if packet.get("routes") else None,
        "routes": packet.get("routes", []), "input": packet.get("input", {}),
    }
    engine = _engine_for(project, engine_request, fake=True, fake_provider=fake_provider,
                         workflow_builder=_workflow_builder(packet))
    engine._tasks[task_id] = copy.deepcopy(packet)
    provider = engine._provider("fake") or engine._provider("execution.fake")
    capability = provider.capability() if hasattr(provider, "capability") else provider
    if not isinstance(capability, Mapping) or not capability.get("available", False):
        raise ValueError("fake execution provider unavailable")

    # Mirror TaskEngine.execute_fake through its in-memory reservation phase,
    # then publish that exact packet before asking the provider to dispatch.
    if packet["state"] == "failed":
        engine.transition(packet, "ready", resume=True)
        packet = engine._tasks[task_id]
    reserved_packet = engine.reserve_execution(packet, operation_id)
    if not reserved_packet.get("last_reservation", {}).get("dispatch", False):
        raise ValueError("task is not dispatchable")
    engine.transition(packet, "running")
    reserved_packet = copy.deepcopy(engine._tasks[task_id])
    reservation = {
        "status": "reserved", "fixture_id": fixture_id, "task_id": task_id,
        "route_id": packet["routes"][0], "reservation": "execution",
    }
    reservation_results = copy.deepcopy(dict(prior_results))
    reservation_results[operation_id] = reservation
    reservation_record = _record(
        "TaskState", task_id, config["project_id"],
        [f"task:{task_id}", f"operation:{operation_id}"],
        revision=int(prior["revision"]) + 1, task_id=task_id,
        state=reserved_packet["state"], packet=reserved_packet,
        operation_results=reservation_results,
    )
    reservation_operation = "task-run-fake-reserve." + hashlib.sha256(
        (task_id + "|" + operation_id).encode("utf-8")
    ).hexdigest()[:32]
    try:
        store.commit(
            reservation_operation, {"role": "execution_agent", "model": "r2.workflow"},
            [reservation_record], expected_revisions={task_id: int(prior["revision"])},
        )
    except ResearchStoreError:
        # A competing process may have won the reservation after our initial
        # read.  Never dispatch after a failed reservation commit.
        latest_after_race = store.latest_record(task_id, "TaskState")
        raced = latest_after_race.get("operation_results", {}).get(operation_id) if latest_after_race else None
        if isinstance(raced, Mapping):
            if raced.get("fixture_id") != fixture_id:
                raise ValueError("operation_id was already used with a different fixture_id")
            raise ValueError("operation_id has a persisted reservation and requires reconciliation")
        raise

    # The reservation is durable here.  Build the provider request only after
    # that commit, so a process failure cannot silently charge a second run.
    request = {
        "operation": "execute", "task_type": reserved_packet["task_type"],
        "task_context": reserved_packet["task_context"], "fixture_id": fixture_id,
        "input": reserved_packet.get("input", {}), "project_id": reserved_packet["project_id"],
        "workflow_id": reserved_packet["workflow_id"],
    }
    result = provider.execute(request) if hasattr(provider, "execute") else provider.dispatch(request)
    raw_outcome = result.get("status") if isinstance(result, Mapping) else "UNKNOWN"
    run_status = "completed" if raw_outcome == "COMPLETED" else "failed"
    run = {
        "schema_version": 1, "type": "Run", "run_id": operation_id,
        "task_id": reserved_packet["task_id"],
        "route_id": reserved_packet["last_reservation"].get("route_id"),
        "provider_id": result.get("provider_id") if isinstance(result, Mapping) else None,
        "status": run_status, "outcome": raw_outcome,
        "fixture_id": result.get("fixture_id") if isinstance(result, Mapping) else None,
        "input_digest": result.get("input_digest") if isinstance(result, Mapping) else None,
        "side_effect": result.get("side_effect", "unknown") if isinstance(result, Mapping) else "unknown",
        "output": copy.deepcopy(result.get("output")) if isinstance(result, Mapping) else None,
    }
    operation = reserved_packet["operations"][operation_id]
    operation_status = "unknown" if str(raw_outcome).casefold() == "unknown" else run_status
    operation.update(status=operation_status, result=copy.deepcopy(result), run=run)
    reserved_packet["last_run"] = copy.deepcopy(run)
    engine._tasks[task_id] = reserved_packet
    if raw_outcome == "COMPLETED":
        completed_packet = engine.transition(reserved_packet, "completed")
    else:
        reason = result.get("stop_reason", "execution_outcome_not_completed") if isinstance(result, Mapping) else "unknown_execution_outcome"
        completed_packet = engine.transition(reserved_packet, "failed", reason=reason)
    operation = completed_packet.get("operations", {}).get(operation_id, {})
    result = operation.get("result") if isinstance(operation, Mapping) else None
    outcome = result.get("status") if isinstance(result, Mapping) else "UNKNOWN"
    if outcome not in {"COMPLETED", "UNKNOWN"}:
        outcome = "UNKNOWN"
    run_dir = resolve_run_dir(runs_root, run_id)
    if not run_dir.exists():
        create_run(runs_root, run_id,
                   {"task_id": task_id, "route_id": packet["routes"][0],
                    "task_context": "synthetic", "fixture_id": fixture_id,
                    "operation_id": operation_id},
                   {"input_hashes": [_sha256_json(packet)]})
    if outcome != "COMPLETED":
        # UNKNOWN is retained as failed and is deliberately not retried under
        # the same operation ID.  The built-in fake provider does not produce
        # this branch, but the boundary remains explicit for provider swaps.
        manifest = inspect_run(runs_root, run_id)
        operation_result = {"status": "unknown", "outcome": outcome,
                            "fixture_id": fixture_id, "run_id": run_id,
                            "result": copy.deepcopy(result)}
        state = "failed"
        verification = None
    else:
        packet_digest = _sha256_json(completed_packet)
        manifest = _record_complete_stages(runs_root, run_id, operation_id, task_id,
                                           packet["routes"][0], fixture_id, packet_digest, result)
        operation_result = {"status": "completed", "outcome": outcome,
                            "fixture_id": fixture_id, "run_id": run_id,
                            "result": copy.deepcopy(result),
                            "manifest_sha256": _sha256_bytes((run_dir / "manifest.json").read_bytes())}
        state = "completed"
        manifest_sha256 = _sha256_bytes((run_dir / "manifest.json").read_bytes())
        verification = _record_run_outputs(config["project_id"], task_id, packet["routes"][0],
                                           run_id, manifest, manifest_sha256, result, fixture_id,
                                           workflow_id=packet["workflow_id"],
                                           method_id=_method_for(packet["task_type"], packet["workflow_id"]))
    next_packet = copy.deepcopy(completed_packet)
    next_packet["state"] = state
    if isinstance(next_packet.get("last_run"), Mapping):
        next_packet["last_run"] = copy.deepcopy(next_packet["last_run"])
        next_packet["last_run"]["run_id"] = run_id
    next_packet["next_action"] = {
        "action_id": None, "executable": False, "input_refs": [], "expected_outputs": [],
        "preconditions": [], "reason": "task_completed" if state == "completed" else "unknown_execution_outcome",
        "resume_condition": None,
    }
    operation_results = copy.deepcopy(dict(prior_results))
    operation_results[operation_id] = operation_result
    revision = int(prior["revision"]) + 2
    task_record = _record("TaskState", task_id, config["project_id"],
                          [f"task:{task_id}", f"operation:{operation_id}"],
                          revision=revision, task_id=task_id, state=state,
                          packet=next_packet, operation_results=operation_results)
    records = [task_record]
    relationships: list[dict[str, Any]] = []
    if verification is not None:
        records.extend(verification["records"])
        relationships.extend(verification["relationships"])
    store_operation = "task-run-fake." + hashlib.sha256((task_id + "|" + operation_id).encode("utf-8")).hexdigest()[:32]
    store.commit(store_operation, {"role": "execution_agent", "model": "r2.workflow"}, records, relationships)
    output = copy.deepcopy(next_packet)
    output["run_id"] = run_id
    output["manifest_sha256"] = operation_result.get("manifest_sha256")
    output["operation_result"] = copy.deepcopy(operation_result)
    return output


def _record_run_outputs(project_id: str, task_id: str, route_id: str, run_id: str,
                        manifest: Mapping[str, Any], manifest_sha256: str,
                        result: Mapping[str, Any], fixture_id: str, *,
                        workflow_id: str = "mining_research_kernel.workflow.flac3d",
                        method_id: str = "mining_research_kernel.method.flac3d.fake_execution") -> dict[str, Any]:
    digest = _sha256_json({"task_id": task_id, "run_id": run_id, "result": result})
    run_ref = _record("RunReference", "runref." + digest[:32], project_id,
                      [f"run:{run_id}", f"task:{task_id}"],
                      run_id=run_id,
                      manifest_sha256=_require_string(manifest_sha256, "manifest_sha256"),
                      status="accepted", route_id=route_id)
    asset = _record("Asset", "asset." + digest[:32], project_id,
                    [f"run:{run_id}"], asset_kind="synthetic_result",
                    locator={"run_id": run_id, "fixture_id": fixture_id, "kind": "fake_execution_result"},
                    content_sha256=_sha256_json(result), authority="derived", status="generated")
    evidence = _record("Evidence", "evidence." + digest[:32], project_id,
                       [f"run:{run_id}", f"asset:{asset['id']}"], evidence_kind="synthetic_execution",
                       asset_ref=asset["id"], locator={"run_id": run_id, "stage": "execution", "fixture_id": fixture_id},
                       status="observed")
    verification = _record("Verification", "verification." + digest[:32], project_id,
                           [f"run:{run_id}"], status="passed", gate_id="kernel_workflow_mechanics",
                           scope={"verification": "kernel_workflow_only"},
                           verification_scope="kernel workflow mechanics", run_id=run_id,
                           unresolved_risks=["no FLAC3D validation", "no numerical validation",
                                             "no physical validation", "no engineering validation"])
    records = [run_ref, asset, evidence, verification]
    relationships = [
        _relationship("edge." + digest[:32] + ".run-route", "run_executes_route", run_ref,
                      _record("Route", route_id, project_id, [f"task:{task_id}"], status="active",
                              question_id=f"{task_id}.question.1", hypothesis_id=None,
                              workflow_id=workflow_id, method_id=method_id, budget=1), project_id,
                      [f"run:{run_id}"]),
        _relationship("edge." + digest[:32] + ".run-evidence", "run_produces_evidence", run_ref, evidence, project_id, [f"run:{run_id}"]),
        _relationship("edge." + digest[:32] + ".verification-run", "verification_checks_run", verification, run_ref, project_id, [f"run:{run_id}"]),
        _relationship("edge." + digest[:32] + ".evidence-asset", "evidence_derived_from_asset", evidence, asset, project_id, [f"run:{run_id}"]),
    ]
    return {"records": records, "relationships": relationships, "run_reference": run_ref,
            "asset": asset, "evidence": evidence, "verification": verification}


def research_map_rebuild(project_root: str | os.PathLike[str], output: str | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    store = ResearchStore(root)
    if output is not None:
        if not isinstance(output, str) or not output.strip() or Path(output).is_absolute():
            raise ValueError("--output must be a relative path within project")
        output = output.strip()
        return store.rebuild_research_map(output)
    # The low-level store keeps ``output=None`` pure for callers that only
    # need a view; this CLI-facing composition root persists the configured
    # project view by default.
    default_output = store._configured_map.relative_to(root).as_posix()
    return store.rebuild_research_map(default_output)


__all__ = ["load_json_value", "task_start", "task_inspect", "task_complete", "task_run_fake", "research_map_rebuild"]
