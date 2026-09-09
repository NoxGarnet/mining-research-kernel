"""Generic in-memory task state machine and bounded execution composition."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_NAMESPACED = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_MATURITIES = {"established", "known_workflow", "exploratory"}
_STATES = {"proposed", "ready", "running", "completed", "blocked", "failed"}
_TRANSITIONS = {
    "proposed": {"ready", "blocked", "failed"},
    "ready": {"running", "blocked", "failed"},
    "running": {"completed", "blocked", "failed"},
    "blocked": {"ready", "failed"},
    "failed": {"ready", "blocked"},
    "completed": set(),
}
_TERMINAL = {"blocked", "failed", "completed"}


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _kind(task_type: str) -> str:
    return task_type.rsplit(".", 1)[-1].casefold()


def _strings(value: Any, field: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item.strip() for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    return list(value)


def _normal(value: Any) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _normalized_command(value: Any) -> str:
    """Match the R1 provider's whitespace normalization without case folding."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def _query_sha256(*, product: str, product_version: str, topic: str,
                  command: str, source: Any, anchor: str, task_context: str) -> str:
    canonical = {
        "product": product, "product_version": product_version, "topic": topic,
        "command": command, "source": source, "anchor": anchor,
        "task_context": task_context,
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _scope_covers(granted: Any, requested: Any, project_id: str) -> bool:
    if requested is None:
        return bool(granted is not None)
    if not isinstance(requested, Mapping):
        requested = {"operations": requested if isinstance(requested, list) else [requested]}
    if not isinstance(granted, Mapping):
        return False
    owner = granted.get("project_id", granted.get("project"))
    wanted_owner = requested.get("project_id", requested.get("project", project_id))
    if owner not in {None, project_id, wanted_owner} or wanted_owner != project_id:
        return False
    wanted_operations = requested.get("operations", requested.get("actions", []))
    granted_operations = granted.get("operations", granted.get("actions", []))
    if isinstance(wanted_operations, str):
        wanted_operations = [wanted_operations]
    if isinstance(granted_operations, str):
        granted_operations = [granted_operations]
    return isinstance(wanted_operations, list) and isinstance(granted_operations, list) and set(wanted_operations).issubset(set(granted_operations))


def _provider_capability(value: Any) -> Mapping[str, Any] | None:
    if hasattr(value, "capability"):
        value = value.capability()
    return value if isinstance(value, Mapping) else None


def capability_status_for(workflow_pack: Mapping[str, Any], task_type: str) -> Mapping[str, Any] | None:
    """Return the workflow-declared capability state for a task action.

    Capability declarations are owned by workflow packs.  The task engine only
    consumes their generic shape and never branches on a product or provider.
    """
    statuses = workflow_pack.get("capability_statuses", {})
    if not isinstance(statuses, Mapping):
        return None
    for key in (task_type, _kind(task_type)):
        value = statuses.get(key)
        if isinstance(value, Mapping):
            return value
    return None


def unavailable_capability(status: Mapping[str, Any] | None) -> tuple[str, str] | None:
    """Return a stable stop reason and recovery condition for an unavailable capability."""
    if not isinstance(status, Mapping) or status.get("available") is not False:
        return None
    reason = status.get("reason")
    resume = status.get("resume_condition")
    return (
        reason.strip() if isinstance(reason, str) and reason.strip() else "capability_unavailable",
        resume.strip() if isinstance(resume, str) and resume.strip() else "provide an available capability",
    )


class TaskEngine:
    """Keep task packets and execution accounting in memory only."""

    def __init__(self, project: Mapping[str, Any], workflow_pack: Mapping[str, Any],
                 provider_capabilities: Mapping[str, Any] | None = None,
                 relevant_refs: Mapping[str, Any] | None = None,
                 documentation_result: Mapping[str, Any] | None = None,
                 **kwargs: Any) -> None:
        if not isinstance(project, Mapping) or not isinstance(workflow_pack, Mapping):
            raise ValueError("project and workflow_pack must be mappings")
        self.project = _copy(dict(project))
        self.workflow_pack = _copy(dict(workflow_pack))
        self.providers = dict(provider_capabilities or kwargs.get("providers") or {})
        refs = dict(relevant_refs or {})
        refs.update({key: kwargs[key] for key in ("failure_refs", "decision_refs", "cognition_refs") if key in kwargs})
        self.relevant_refs = {
            "failures": _strings(refs.get("failures", refs.get("failure_refs", [])), "failure_refs"),
            "decisions": _strings(refs.get("decisions", refs.get("decision_refs", [])), "decision_refs"),
            "cognition": _strings(refs.get("cognition", refs.get("cognition_refs", [])), "cognition_refs"),
        }
        # Host-supplied provider evidence, never populated from Agent request data.
        self.documentation_result = _copy(documentation_result)
        self._tasks: dict[str, dict[str, Any]] = {}

    def _provider(self, name: str) -> Any:
        for key, value in self.providers.items():
            if key == name or str(getattr(value, "provider_id", "")).endswith("." + name):
                return value
        return None

    def _capability_assessment(self, task_type: str) -> tuple[bool, str | None, str | None]:
        unavailable = unavailable_capability(capability_status_for(self.workflow_pack, task_type))
        if unavailable is None:
            return True, None, None
        reason, resume = unavailable
        return False, reason, resume

    def _documentation_source(self, request: Mapping[str, Any]) -> Any:
        if self.documentation_result is not None:
            return self.documentation_result
        if request.get("task_context", "production") == "synthetic":
            return request.get("documentation_result")
        return None

    def _documentation_assessment(self, request: Mapping[str, Any], gates: list[str]) -> tuple[bool, str, str]:
        # This validates a result crossing the configured provider boundary;
        # it provides no signature verification or authentication.
        if "documentation" not in gates:
            return True, "NOT_APPLICABLE", "task_does_not_require_gate"
        result = self._documentation_source(request)
        context = request.get("task_context", "production")
        if context not in {"production", "synthetic"}:
            return False, "CANNOT_VERIFY", "task_context_invalid"
        if not isinstance(result, Mapping):
            workflow_gate = self.workflow_pack.get("gate_statuses", {}).get("documentation", {})
            if isinstance(workflow_gate, Mapping) and workflow_gate.get("status") == "CANNOT_VERIFY":
                reason = workflow_gate.get("reason")
                if isinstance(reason, str) and reason.strip():
                    return False, "CANNOT_VERIFY", reason
            return False, "CANNOT_VERIFY", "documentation_result_required"
        status = result.get("status")
        if context == "synthetic":
            expected_status, trust = "SYNTHETIC_VERIFIED", "synthetic"
        else:
            expected_status, trust = "VERIFIED", "official_local"
        if status == "CANNOT_VERIFY":
            reason = result.get("stop_reason")
            return False, "CANNOT_VERIFY", reason if isinstance(reason, str) and reason.strip() else "documentation_not_verified"
        citation = result.get("citation")
        if status != expected_status or not isinstance(citation, Mapping):
            return False, "CANNOT_VERIFY", "documentation_not_verified_for_task_context"
        if citation.get("status", status) != status or citation.get("trust_class") != trust:
            return False, "CANNOT_VERIFY", "documentation_citation_trust_mismatch"
        if result.get("coverage_scope") != "command_name_only":
            return False, "CANNOT_VERIFY", "documentation_coverage_insufficient"
        product = self.project.get("product", "flac3d")
        version = self.project.get("product_version", "unknown")
        source_id = citation.get("source_id")
        body_digest = citation.get("sha256_body")
        query_digest = citation.get("query_sha256")
        if not isinstance(source_id, str) or not _NAMESPACED.fullmatch(source_id):
            return False, "CANNOT_VERIFY", "documentation_source_id_invalid"
        if (not isinstance(body_digest, str) or
                not re.fullmatch(r"[0-9a-f]{64}", body_digest)):
            return False, "CANNOT_VERIFY", "documentation_body_digest_invalid"
        if (not isinstance(query_digest, str) or
                not re.fullmatch(r"[0-9a-f]{64}", query_digest)):
            return False, "CANNOT_VERIFY", "documentation_query_digest_invalid"
        if (not isinstance(citation.get("fetched_at"), str) or not citation.get("fetched_at") or
                not isinstance(citation.get("checked_at"), str) or not citation.get("checked_at")):
            return False, "CANNOT_VERIFY", "documentation_timestamps_required"
        cited_product = citation.get("product")
        cited_product_version = citation.get("product_version")
        cited_document_build = citation.get("document_build")
        if (cited_product != product or version == "unknown"
                or (cited_product_version is not None and cited_product_version != version)
                or (cited_document_build is not None and cited_document_build != version)
                or (cited_product_version is None and cited_document_build is None)):
            return False, "CANNOT_VERIFY", "documentation_product_version_mismatch"
        page = request.get("topic", request.get("page", request.get("documentation_page")))
        command = _normalized_command(request.get("command"))
        cited_page = citation.get("page")
        cited_command = citation.get("command")
        expected_anchor = "command:" + ".".join(command.split()) if command else None
        request_anchor = request.get("anchor")
        if request_anchor is not None and request_anchor != expected_anchor:
            return False, "CANNOT_VERIFY", "documentation_anchor_mismatch"
        if not isinstance(page, str) or cited_page != page:
            return False, "CANNOT_VERIFY", "documentation_page_mismatch"
        if cited_command is not None and _normalized_command(cited_command) != command:
            return False, "CANNOT_VERIFY", "documentation_command_mismatch"
        if citation.get("anchor") != expected_anchor:
            return False, "CANNOT_VERIFY", "documentation_command_mismatch"
        expected_query_digest = _query_sha256(
            product=product, product_version=version, topic=page, command=command,
            source=request.get("source"), anchor=request_anchor or expected_anchor,
            task_context=context,
        )
        if query_digest != expected_query_digest:
            return False, "CANNOT_VERIFY", "documentation_query_digest_mismatch"
        return True, expected_status, "documentation_verified_for_task_context"

    def _documentation_ok(self, request: Mapping[str, Any], task_type: str, gates: list[str]) -> tuple[bool, str | None]:
        ok, _status, reason = self._documentation_assessment(request, gates)
        return ok, None if ok else reason

    def _action(self, packet: Mapping[str, Any], state: str, *, reason: str | None = None) -> dict[str, Any]:
        if state in _TERMINAL:
            return {
                "action_id": None, "executable": False, "input_refs": [], "expected_outputs": [],
                "preconditions": [], "reason": reason or packet.get("stop_reason", f"task_{state}"),
                "resume_condition": packet.get("resume_condition") if state == "blocked" else None,
            }
        if state == "proposed":
            return {"action_id": "task.prepare", "executable": True, "input_refs": packet["required_reads"],
                    "expected_outputs": ["validated task packet"], "preconditions": ["task request is reviewable"]}
        return {
            "action_id": packet["task_type"] + (".run" if state == "ready" else ".in_progress"),
            "executable": state == "ready", "input_refs": packet["required_reads"],
            "expected_outputs": ["structured Run observation"],
            "preconditions": [{"predicate": "execution_budget_available", "value": True},
                              {"predicate": "authorization_scope_covers_action",
                               "value": packet["execution_authorized"] or _kind(packet["task_type"]) not in {"fake_execution", "execution", "fixture_execution"}}],
        }

    def _blocked(self, packet: dict[str, Any], reason: str, resume: str, *, consumes_run: bool = False) -> dict[str, Any]:
        previous = packet.get("state")
        packet["state"] = "blocked"
        packet["stop_reason"] = reason
        packet["resume_condition"] = resume
        packet["stop_conditions"] = [{"condition_id": reason, "kind": "preflight", "status": "active",
                                      "consumes_run": consumes_run, "reason": reason,
                                      "resume_when": resume}]
        packet["next_action"] = self._action(packet, "blocked", reason=reason)
        packet.setdefault("history", []).append({"event": "state_transition", "from": previous,
                                                  "to": "blocked", "reason": reason,
                                                  "consumes_run": consumes_run})
        return packet

    def start(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            raise ValueError("request must be a mapping")
        project_id = request.get("project_id", self.project.get("project_id"))
        if not isinstance(project_id, str) or project_id != self.project.get("project_id"):
            raise ValueError("project_id does not match project")
        workflow_id = request.get("workflow_id", self.workflow_pack.get("workflow_id"))
        if not isinstance(workflow_id, str) or not _NAMESPACED.fullmatch(workflow_id):
            raise ValueError("workflow_id must be namespaced")
        if workflow_id != self.workflow_pack.get("workflow_id"):
            raise ValueError("workflow_id does not match workflow pack")
        task_type = request.get("task_type")
        if not isinstance(task_type, str) or not _NAMESPACED.fullmatch(task_type):
            raise ValueError("task_type must be namespaced")
        maturity = request.get("maturity")
        if maturity not in _MATURITIES:
            raise ValueError("maturity is invalid")
        max_runs = request.get("max_runs", request.get("budget", {}).get("max_runs") if isinstance(request.get("budget"), Mapping) else None)
        if isinstance(max_runs, bool) or not isinstance(max_runs, int) or max_runs < 1:
            raise ValueError("max_runs must be an integer >= 1")
        task_id = request.get("task_id", f"task-{len(self._tasks) + 1}")
        if not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id):
            raise ValueError("task_id is invalid")
        if task_id in self._tasks:
            raise ValueError("task_id already exists")

        refs_input = request.get("refs", {})
        if refs_input is None:
            refs_input = {}
        if not isinstance(refs_input, Mapping):
            raise ValueError("refs must be a mapping")
        refs = {
            "failures": _strings(refs_input.get("failures", self.relevant_refs["failures"]), "failure_refs"),
            "decisions": _strings(refs_input.get("decisions", self.relevant_refs["decisions"]), "decision_refs"),
            "cognition": _strings(refs_input.get("cognition", self.relevant_refs["cognition"]), "cognition_refs"),
            "documentation": _strings(refs_input.get("documentation", request.get("citation_refs", [])), "citation_refs"),
        }
        requested_scope = request.get("authorization_scope", request.get("authorization"))
        if requested_scope is not None and not isinstance(requested_scope, Mapping):
            raise ValueError("authorization_scope must be a mapping")
        project_scope = self.project.get("authorization_scope", self.project.get("authorization"))
        if project_scope is None and isinstance(self.project.get("execution"), Mapping):
            project_scope = self.project["execution"].get("authorization_scope")
        task_context = request.get("task_context", "production")
        if task_context not in {"production", "synthetic"}:
            raise ValueError("task_context is invalid")
        if requested_scope is not None and not _scope_covers(project_scope, requested_scope, project_id):
            raise ValueError("authorization_scope is outside project scope")
        kind = _kind(task_type)
        is_execution = kind in {"fake_execution", "execution", "fixture_execution"}
        execution_provider = self._provider(request.get("provider", self.workflow_pack.get("execution_provider", "disabled")))
        execution_cap = _provider_capability(execution_provider)
        execution_authorized = bool(self.workflow_pack.get("execution_authorized", False))
        if execution_cap and not execution_cap.get("authorization_required", True):
            execution_authorized = True
        workflow_gates = self.workflow_pack.get("verification_gates", self.workflow_pack.get("required_gates", []))
        if isinstance(workflow_gates, str):
            workflow_gates = [workflow_gates]
        caller_gates = request.get("verification_gates", request.get("needs", []))
        if isinstance(caller_gates, str):
            caller_gates = [caller_gates]
        if not isinstance(workflow_gates, (list, tuple)) or not isinstance(caller_gates, (list, tuple)):
            raise ValueError("verification_gates must be a list")
        gates = list(dict.fromkeys([*(gate for gate in workflow_gates if isinstance(gate, str)),
                                    *(gate for gate in caller_gates if isinstance(gate, str))]))
        documentation_value = self._documentation_source(request)
        documentation_result = _copy(documentation_value) if isinstance(documentation_value, Mapping) else None
        _documentation_ok, documentation_status, documentation_reason = self._documentation_assessment(request, gates)
        gate_statuses = _copy(self.workflow_pack.get("gate_statuses", {}))
        if "documentation" in gates:
            documentation_gate = gate_statuses.setdefault("documentation", {
                "gate_id": "documentation", "applicable": True,
            })
            documentation_gate.update({"applicable": True, "status": documentation_status,
                                       "reason": documentation_reason})
        else:
            documentation_status = "NOT_APPLICABLE"
        packet: dict[str, Any] = {
            "schema_version": 1, "type": "TaskPacket", "task_id": task_id,
            "project_id": project_id, "workflow_id": workflow_id, "task_type": task_type,
            "maturity": maturity, "state": "ready", "required_reads": list(self.workflow_pack.get("required_reads", [])),
            "refs": refs, "relevant_failures": refs["failures"], "relevant_decisions": refs["decisions"],
            "relevant_cognition": refs["cognition"], "relevant_failure_refs": refs["failures"],
            "relevant_decision_refs": refs["decisions"], "relevant_cognition_refs": refs["cognition"],
            "documentation_required": "documentation" in gates,
            "documentation_status": documentation_status,
            "documentation_result": documentation_result,
            "citation_refs": refs["documentation"], "allowed_tools": _strings(
                request.get("allowed_tools", self.workflow_pack.get("allowed_tools", [])), "allowed_tools"),
            "execution_authorized": execution_authorized if is_execution else False,
            "authorization_scope": _copy(requested_scope or project_scope), "routes": list(self.workflow_pack.get("routes", [])),
            "verification_gates": list(gates),
            "gate_statuses": gate_statuses,
            "capability_statuses": _copy(self.workflow_pack.get("capability_statuses", {})),
            "stop_conditions": [], "prohibitions": ["real_engine", "network", "subprocess", "mutation"],
            "writeback_targets": _copy(self.workflow_pack.get("writeback_targets", {})), "max_runs": max_runs,
            "runs_used": 0, "runs_remaining": max_runs, "execution_reservations": [], "operations": {},
            "route_budgets": {},
            "task_context": task_context, "fixture_id": request.get("fixture_id"),
            "input": _copy(request.get("input", {})), "history": [],
        }
        packet["next_action"] = self._action(packet, "ready")
        packet["history"].append({"event": "task_started", "state": "ready"})
        doc_ok, doc_reason = _documentation_ok, None if _documentation_ok else documentation_reason
        capability_ok, capability_reason, capability_resume = self._capability_assessment(task_type)
        if not capability_ok:
            self._blocked(packet, capability_reason or "capability_unavailable",
                          capability_resume or "provide an available capability")
        elif not doc_ok:
            doc_resume = ("documentation_result_required"
                          if doc_reason == "documentation_result_required"
                          else "provide_matching documentation citation")
            self._blocked(packet, doc_reason or "documentation_not_verified", doc_resume)
        elif is_execution and (not execution_cap or not execution_cap.get("available", False)):
            self._blocked(packet, "execution_provider_unavailable", "select an available fake provider")
        self._tasks[task_id] = packet
        return _copy(packet)

    def _get(self, task: Mapping[str, Any] | str) -> dict[str, Any]:
        task_id = task if isinstance(task, str) else task.get("task_id")
        if not isinstance(task_id, str) or task_id not in self._tasks:
            raise ValueError("unknown task")
        return self._tasks[task_id]

    def transition(self, task: Mapping[str, Any] | str, state: str, *, resume: bool = False,
                   reason: str | None = None) -> dict[str, Any]:
        if state not in _STATES:
            raise ValueError("unknown task state")
        packet = self._get(task)
        current = packet["state"]
        if state not in _TRANSITIONS[current]:
            raise ValueError(f"illegal task transition: {current}->{state}")
        if current in {"blocked", "failed"} and state == "ready" and not resume:
            raise ValueError("resume must be explicit")
        packet["state"] = state
        if reason:
            packet["stop_reason"] = reason
        if state == "ready":
            packet.pop("stop_reason", None)
            packet.pop("resume_condition", None)
            packet["stop_conditions"] = []
        packet["next_action"] = self._action(packet, state, reason=reason)
        packet["history"].append({"event": "state_transition", "from": current, "to": state,
                                  "reason": reason, "resume": resume})
        return _copy(packet)

    def reserve_execution(self, task: Mapping[str, Any] | str, operation_id: str,
                          route_budget: Mapping[str, Any] | int | None = None) -> dict[str, Any]:
        packet = self._get(task)
        if not isinstance(operation_id, str) or not operation_id.strip():
            raise ValueError("operation_id must be a non-empty string")
        existing = packet["operations"].get(operation_id)
        if existing and existing.get("status") in {"reserved", "completed", "unknown", "failed"}:
            packet["last_reservation"] = {"operation_id": operation_id, "status": "idempotent",
                                           "dispatch": False, "reason": "operation_already_recorded"}
            return _copy(packet)
        if packet["state"] not in {"ready", "running"}:
            if packet["state"] not in {"completed", "failed"}:
                self._blocked(packet, "task_not_ready_for_execution", "resume task into ready state")
            packet["last_reservation"] = {"operation_id": operation_id, "status": "preflight_blocked",
                                           "dispatch": False, "consumes_run": False}
            return _copy(packet)
        if packet["runs_used"] >= packet["max_runs"]:
            self._blocked(packet, "task_run_budget_exhausted", "start a new task with a new approved budget")
            packet["last_reservation"] = {"operation_id": operation_id, "status": "preflight_blocked",
                                           "dispatch": False, "consumes_run": False}
            return _copy(packet)
        route_id = packet["routes"][0] if packet["routes"] else None
        route_max = None
        if isinstance(route_budget, int):
            route_max = route_budget
        elif isinstance(route_budget, Mapping):
            route_id = route_budget.get("route_id", route_id)
            route_max = route_budget.get("max_runs")
        packet.setdefault("route_budgets", {})
        stored_route_max = packet["route_budgets"].get(route_id)
        if stored_route_max is not None:
            route_max = stored_route_max if route_max is None else min(route_max, stored_route_max)
        if route_max is not None:
            if isinstance(route_max, bool) or not isinstance(route_max, int) or route_max < 1:
                raise ValueError("route max_runs must be an integer >= 1")
            packet["route_budgets"][route_id] = route_max
            route_used = sum(1 for row in packet["execution_reservations"] if row.get("route_id") == route_id)
            if route_used >= route_max:
                self._blocked(packet, "route_run_budget_exhausted", "use another route or obtain a new approved route budget")
                packet["last_reservation"] = {"operation_id": operation_id, "status": "preflight_blocked",
                                               "dispatch": False, "consumes_run": False, "route_id": route_id}
                return _copy(packet)
        packet["runs_used"] += 1
        packet["runs_remaining"] = packet["max_runs"] - packet["runs_used"]
        reservation = {"operation_id": operation_id, "attempt": packet["runs_used"], "route_id": route_id,
                       "status": "reserved", "consumes_run": True}
        packet["execution_reservations"].append(reservation)
        packet["operations"][operation_id] = {"status": "reserved", "reservation": reservation}
        packet["last_reservation"] = {**reservation, "dispatch": True}
        return _copy(packet)

    def execute_fake(self, task: Mapping[str, Any] | str, operation_id: str,
                     route_budget: Mapping[str, Any] | int | None = None) -> dict[str, Any]:
        packet = self._get(task)
        provider = self._provider("fake") or self._provider("execution.fake")
        cap = _provider_capability(provider)
        if not provider or not cap or not cap.get("available", False):
            self._blocked(packet, "fake_execution_provider_unavailable", "provide an available fake execution provider")
            return _copy(packet)
        existing = packet["operations"].get(operation_id)
        if existing and existing.get("status") in {"reserved", "completed", "unknown", "failed"}:
            packet["last_run"] = _copy(existing.get("run"))
            return _copy(packet)
        if packet["state"] == "failed":
            # A deliberately different operation id is an explicit retry.  It
            # re-enters the normal ready path and therefore still pays from
            # the same task budget.
            self.transition(packet, "ready", resume=True)
            packet = self._tasks[packet["task_id"]]
        self.reserve_execution(packet, operation_id, route_budget)
        packet = self._tasks[packet["task_id"]]
        if not packet["last_reservation"].get("dispatch"):
            return _copy(packet)
        if packet["state"] == "ready":
            self.transition(packet, "running")
            packet = self._tasks[packet["task_id"]]
        request = {"operation": "execute", "task_type": packet["task_type"], "task_context": packet["task_context"],
                   "fixture_id": packet.get("fixture_id") or "synthetic.default", "input": packet.get("input", {}),
                   "project_id": packet["project_id"], "workflow_id": packet["workflow_id"]}
        result = provider.execute(request) if hasattr(provider, "execute") else provider.dispatch(request)
        outcome = result.get("status") if isinstance(result, Mapping) else "UNKNOWN"
        run_status = "completed" if outcome == "COMPLETED" else "failed"
        run = {"schema_version": 1, "type": "Run", "run_id": operation_id, "task_id": packet["task_id"],
               "route_id": packet["last_reservation"].get("route_id"), "provider_id": result.get("provider_id") if isinstance(result, Mapping) else None,
               "status": run_status, "outcome": outcome, "fixture_id": result.get("fixture_id") if isinstance(result, Mapping) else None,
               "input_digest": result.get("input_digest") if isinstance(result, Mapping) else None,
               "side_effect": result.get("side_effect", "unknown") if isinstance(result, Mapping) else "unknown",
               "output": _copy(result.get("output")) if isinstance(result, Mapping) else None}
        operation = packet["operations"][operation_id]
        operation_status = "unknown" if str(outcome).casefold() == "unknown" else run_status
        operation.update(status=operation_status, result=_copy(result), run=run)
        packet["last_run"] = _copy(run)
        if outcome == "COMPLETED":
            self.transition(packet, "completed")
        else:
            reason = result.get("stop_reason", "execution_outcome_not_completed") if isinstance(result, Mapping) else "unknown_execution_outcome"
            self.transition(packet, "failed", reason=reason)
        return _copy(packet)


def reserve_execution(task: Mapping[str, Any], operation_id: str,
                      route_budget: Mapping[str, Any] | int | None = None) -> dict[str, Any]:
    """Pure helper for a packet-like mapping without an engine registry."""
    packet = _copy(dict(task))
    packet.setdefault("state", "ready")
    packet.setdefault("max_runs", packet.get("budget", {}).get("max_runs", 1) if isinstance(packet.get("budget"), Mapping) else 1)
    packet.setdefault("runs_used", 0)
    packet.setdefault("runs_remaining", packet["max_runs"] - packet["runs_used"])
    packet.setdefault("routes", [])
    packet.setdefault("execution_reservations", [])
    packet.setdefault("operations", {})
    packet.setdefault("route_budgets", {})
    pseudo = TaskEngine({"project_id": packet.get("project_id")}, {"workflow_id": packet.get("workflow_id", "x.y"), "routes": packet["routes"]})
    pseudo._tasks[packet.get("task_id", "task-1")] = packet
    return pseudo.reserve_execution(packet, operation_id, route_budget)


__all__ = ["TaskEngine", "reserve_execution"]
