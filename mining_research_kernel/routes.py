"""Small, persistent multi-route lifecycle for the v0.1.0 kernel.

Routes are ordinary ResearchStore records.  This service only coordinates
bounded state transitions and deterministic comparison metadata; it never
judges whether a route's scientific result is true.
"""
from __future__ import annotations

import copy
import hashlib
import os
import re
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.config import load_route_policy
from mining_research_kernel.records import ResearchStore, ResearchStoreError


_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
_ABS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
_STATUSES = {"proposed", "active", "blocked", "completed", "failed", "cannot_verify", "accepted", "rejected", "superseded"}
_OUTCOMES = {"completed", "failed", "cannot_verify"}


class RouteLifecycleError(ResearchStoreError):
    """Raised when a requested route transition cannot be performed."""


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value.strip()):
        raise RouteLifecycleError(f"{field} must match the project record ID format")
    return value.strip()


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RouteLifecycleError(f"{field} must be a non-empty string")
    return value.strip()


def _relative_ref(value: Any, field: str) -> str:
    value = _nonempty(value, field)
    if value.startswith(("/", "\\")) or _ABS_DRIVE.match(value) or ":\\" in value or ":/" in value:
        raise RouteLifecycleError(f"{field} must be a project-relative reference")
    if ".." in Path(value.replace("\\", "/")).parts:
        raise RouteLifecycleError(f"{field} contains an unsafe parent traversal")
    return value.replace("\\", "/")


def _list_of_refs(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise RouteLifecycleError(f"{field} must be a {'non-empty ' if not allow_empty else ''}list")
    return sorted({_relative_ref(item, field) for item in value})


def _list_of_values(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise RouteLifecycleError(f"{field} must be a list")
    def check(item: Any) -> None:
        if isinstance(item, Mapping):
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif isinstance(item, str):
            if item.startswith(("/", "\\")) or _ABS_DRIVE.match(item) or ".." in Path(item.replace("\\", "/")).parts:
                raise RouteLifecycleError(f"{field} contains an unsafe path reference")
    check(value)
    return copy.deepcopy(value)


def _digest(value: Any) -> str:
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class RouteLifecycle:
    """Coordinate bounded route transitions under the ResearchStore writer."""

    def __init__(self, project_root: str | os.PathLike[str], *, producer_role: str = "planning_agent",
                 model: str = "r3.routes"):
        self.root = Path(project_root).expanduser().resolve()
        self.store = ResearchStore(self.root)
        policy = load_route_policy(self.root)
        configured = policy.get("max_active_routes", 3) if isinstance(policy, dict) else 3
        if not isinstance(configured, int) or isinstance(configured, bool) or not 1 <= configured <= 3:
            raise RouteLifecycleError("route_policy.max_active_routes must be an integer from 1 to 3")
        self.max_active_routes = configured
        self.producer = {"role": _nonempty(producer_role, "producer_role"), "model": _nonempty(model, "model")}

    def _latest(self) -> dict[str, dict[str, Any]]:
        return self.store._latest_record_map(self.store._read_transactions())

    def _routes(self) -> dict[str, dict[str, Any]]:
        return {rid: record for rid, record in self._latest().items() if record.get("type") == "Route"}

    def _task_budget(self, task_id: str | None, latest: dict[str, dict[str, Any]] | None = None) -> int | None:
        if task_id is None:
            return None
        records = latest if latest is not None else self._latest()
        task = records.get(task_id)
        if task is None or task.get("type") != "TaskState":
            raise RouteLifecycleError(f"TaskState is not present: {task_id}")
        packet = task.get("packet")
        value = packet.get("max_runs") if isinstance(packet, Mapping) else None
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise RouteLifecycleError(f"TaskState max_runs is invalid: {task_id}")
        return value

    def _task_runs_used(self, task_id: str, routes: dict[str, dict[str, Any]],
                        latest: dict[str, dict[str, Any]] | None = None) -> int:
        records = latest if latest is not None else self._latest()
        task = records[task_id]
        packet = task.get("packet", {})
        baseline = packet.get("runs_used", 0) if isinstance(packet, Mapping) else 0
        if isinstance(baseline, bool) or not isinstance(baseline, int) or baseline < 0:
            raise RouteLifecycleError(f"TaskState runs_used is invalid: {task_id}")
        route_runs = sum(int(route.get("runs_used", 0)) for route in routes.values()
                        if route.get("task_id") == task_id)
        return baseline + route_runs

    def _find_operation(self, operation_id: str) -> dict[str, Any] | None:
        operation_id = _id(operation_id, "operation_id")
        return next((tx for tx in self.store._read_transactions() if tx["operation_id"] == operation_id), None)

    def _idempotent(self, operation_id: str, *, route_id: str | None = None) -> dict[str, Any] | None:
        tx = self._find_operation(operation_id)
        if tx is None:
            return None
        if route_id is not None and not any(record.get("id") == route_id for record in tx["records"]):
            raise RouteLifecycleError(f"operation_id already belongs to another route operation: {operation_id}")
        return {"operation_id": operation_id, "idempotent": True,
                "records": copy.deepcopy(tx["records"]), "relationships": copy.deepcopy(tx["relationships"])}

    def _commit_locked(self, operation_id: str, records: list[dict[str, Any]],
                       relationships: list[dict[str, Any]] | None = None,
                       expected: dict[str, int] | None = None) -> dict[str, Any]:
        return self.store.commit(operation_id, self.producer, records, relationships or [],
                                 expected_revisions=expected, lock_held=True)

    def _record(self, route_id: str, *, revision: int, status: str, question_id: str,
                hypothesis_id: str | None, workflow_id: str, method_id: str, budget: int,
                write_set: list[str], parent_route_id: str | None = None,
                supersedes_route_id: str | None = None, runs_used: int = 0,
                reservations: list[dict[str, Any]] | None = None,
                stop_conditions: list[Any] | None = None, outputs: list[Any] | None = None,
                stop_reason: str | None = None, source_refs: list[str] | None = None,
                task_id: str | None = None, claim_id: str | None = None,
                inputs: list[Any] | None = None, expected_evidence: list[Any] | None = None,
                assigned_role: str = "planning_agent",
                verification_gates: list[Any] | None = None) -> dict[str, Any]:
        if status not in _STATUSES:
            raise RouteLifecycleError(f"unsupported route status: {status}")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
            raise RouteLifecycleError("budget must be an integer >= 1")
        if runs_used < 0 or runs_used > budget:
            raise RouteLifecycleError("runs_used must be within the route budget")
        record = {
            "schema_version": 1, "type": "Route", "id": route_id, "route_id": route_id,
            "revision": revision, "project_id": self.store.project_id,
            "scope": {"project_id": self.store.project_id, "research_question_id": question_id},
            "source_refs": source_refs or [f"route:{route_id}"],
            "status": status, "question_id": question_id, "research_question_id": question_id,
            "hypothesis_id": hypothesis_id,
            "workflow_id": workflow_id, "method_id": method_id, "budget": budget,
            "runs_used": runs_used, "write_set": sorted(write_set),
            "parent_route_id": parent_route_id, "supersedes_route_id": supersedes_route_id,
            "stop_conditions": copy.deepcopy(stop_conditions or []),
            "outputs": copy.deepcopy(outputs or []), "reservations": copy.deepcopy(reservations or []),
            "stop_reason": stop_reason, "inputs": copy.deepcopy(inputs or []),
            "expected_evidence": copy.deepcopy(expected_evidence or []),
            "assigned_role": _nonempty(assigned_role, "assigned_role"),
            "verification_gates": copy.deepcopy(verification_gates or []),
        }
        if task_id is not None:
            record["task_id"] = task_id
        if claim_id is not None:
            record["claim_id"] = claim_id
        return record

    def propose(self, route: Mapping[str, Any], operation_id: str) -> dict[str, Any]:
        operation_id = _id(operation_id, "operation_id")
        route = dict(route)
        route_id = _id(route.get("route_id", route.get("id")), "route_id")
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=route_id)
            if old is not None:
                return old
            current = self._latest()
            question_id = _id(route.get("question_id", route.get("research_question_id")), "question_id")
            question = current.get(question_id)
            if question is None or question.get("type") != "ResearchQuestion":
                raise RouteLifecycleError(f"ResearchQuestion is not present: {question_id}")
            parent = route.get("parent_route_id")
            supersedes = route.get("supersedes_route_id")
            existing_routes = self._routes()
            if parent is not None:
                parent = _id(parent, "parent_route_id")
                if parent not in existing_routes:
                    raise RouteLifecycleError(f"parent route is not present: {parent}")
                if existing_routes[parent].get("question_id") != question_id:
                    raise RouteLifecycleError("parent route must address the same ResearchQuestion")
            if supersedes is not None:
                supersedes = _id(supersedes, "supersedes_route_id")
                if supersedes not in existing_routes:
                    raise RouteLifecycleError(f"superseded route is not present: {supersedes}")
                if existing_routes[supersedes].get("question_id") != question_id:
                    raise RouteLifecycleError("superseded route must address the same ResearchQuestion")
            write_set = _list_of_refs(route.get("write_set"), "write_set", allow_empty=False)
            hypothesis_id = route.get("hypothesis_id")
            if hypothesis_id is not None:
                hypothesis_id = _id(hypothesis_id, "hypothesis_id")
            task_id = route.get("task_id")
            if task_id is not None:
                task_id = _id(task_id, "task_id")
                self._task_budget(task_id, current)
            claim_id = route.get("claim_id")
            claim = None
            if claim_id is not None:
                claim_id = _id(claim_id, "claim_id")
                claim = current.get(claim_id)
                if claim is None or claim.get("type") != "Claim":
                    raise RouteLifecycleError(f"Claim is not present: {claim_id}")
            budget = route.get("budget", route.get("max_runs"))
            if not isinstance(budget, int) or isinstance(budget, bool) or budget < 1:
                raise RouteLifecycleError("budget/max_runs must be an integer >= 1")
            source_refs = route.get("source_refs", [f"route:{route_id}"])
            if not isinstance(source_refs, list):
                raise RouteLifecycleError("source_refs must be a list")
            record = self._record(
                route_id, revision=1, status="proposed", question_id=question_id,
                hypothesis_id=hypothesis_id,
                workflow_id=_nonempty(route.get("workflow_id"), "workflow_id"),
                method_id=_nonempty(route.get("method_id"), "method_id"), budget=budget,
                write_set=write_set, parent_route_id=parent, supersedes_route_id=supersedes,
                stop_conditions=_list_of_values(route.get("stop_conditions", []), "stop_conditions"),
                inputs=_list_of_values(route.get("inputs", []), "inputs"),
                expected_evidence=_list_of_values(route.get("expected_evidence", []), "expected_evidence"),
                assigned_role=route.get("assigned_role", self.producer["role"]),
                verification_gates=_list_of_values(route.get("verification_gates", []), "verification_gates"),
                task_id=task_id, claim_id=claim_id,
                source_refs=[_relative_ref(item, "source_refs") for item in source_refs],
            )
            relationships = [{
                "schema_version": 1, "relationship_id": f"edge.{_digest([operation_id, route_id, question_id])[:32]}",
                "revision": 1, "project_id": self.store.project_id, "relation": "route_addresses_question",
                "from_id": route_id, "from_revision": 1, "to_id": question_id,
                "to_revision": question["revision"], "source_refs": [f"route:{route_id}"],
            }]
            if claim is not None:
                relationships.append({
                    "schema_version": 1, "relationship_id": f"edge.{_digest([operation_id, route_id, claim_id, 'claim'])[:32]}",
                    "revision": 1, "project_id": self.store.project_id, "relation": "route_targets_claim",
                    "from_id": route_id, "from_revision": 1, "to_id": claim_id,
                    "to_revision": claim["revision"], "source_refs": [f"route:{route_id}"],
                })
            if parent is not None:
                parent_record = existing_routes[parent]
                relationships.append({
                    "schema_version": 1, "relationship_id": f"edge.{_digest([operation_id, route_id, parent])[:32]}",
                    "revision": 1, "project_id": self.store.project_id, "relation": "route_child_of_route",
                    "from_id": route_id, "from_revision": 1, "to_id": parent,
                    "to_revision": parent_record["revision"], "source_refs": [f"route:{route_id}"],
                })
            if supersedes is not None:
                old_record = existing_routes[supersedes]
                relationships.append({
                    "schema_version": 1, "relationship_id": f"edge.{_digest([operation_id, route_id, supersedes, 'supersedes'])[:32]}",
                    "revision": 1, "project_id": self.store.project_id, "relation": "route_supersedes_route",
                    "from_id": route_id, "from_revision": 1, "to_id": supersedes,
                    "to_revision": old_record["revision"], "source_refs": [f"route:{route_id}"],
                })
            tx = self._commit_locked(operation_id, [record], relationships)
            return {"operation_id": operation_id, "route": copy.deepcopy(record), "transaction": tx}

    def inspect(self, route_id: str) -> dict[str, Any]:
        route_id = _id(route_id, "route_id")
        route = self._routes().get(route_id)
        if route is None:
            raise RouteLifecycleError(f"route is not present: {route_id}")
        routes = self._routes()
        active = sorted(r["id"] for r in routes.values()
                        if r.get("question_id") == route["question_id"] and r.get("status") == "active")
        return {"route": copy.deepcopy(route), "question_id": route["question_id"],
                "active_route_ids": active, "max_active_routes": self.max_active_routes}

    def reserve(self, route_id: str, operation_id: str) -> dict[str, Any]:
        route_id, operation_id = _id(route_id, "route_id"), _id(operation_id, "operation_id")
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=route_id)
            if old is not None:
                return old
            route = self._routes().get(route_id)
            if route is None:
                raise RouteLifecycleError(f"route is not present: {route_id}")
            if route["status"] not in {"proposed", "active"}:
                raise RouteLifecycleError(f"route cannot be reserved from status {route['status']}")
            reservations = copy.deepcopy(route.get("reservations", []))
            if any(item.get("status") == "reserved" for item in reservations):
                raise RouteLifecycleError("route already has an active reservation")
            reason = None
            routes = self._routes()
            active = [item for item in routes.values()
                      if item.get("question_id") == route["question_id"] and item.get("status") == "active"]
            if route["status"] != "active" and len(active) >= self.max_active_routes:
                reason = "max_active_routes_reached"
            elif int(route.get("runs_used", 0)) >= int(route["budget"]):
                reason = "route_budget_exhausted"
            elif route.get("task_id") is not None and self._task_runs_used(route["task_id"], routes) >= self._task_budget(route["task_id"], self._latest()):
                reason = "task_budget_exhausted"
            else:
                current_set = set(route.get("write_set", []))
                for other in active:
                    for reservation in other.get("reservations", []):
                        if reservation.get("status") == "reserved" and current_set.intersection(reservation.get("write_set", [])):
                            reason = f"write_set_conflict:{other['id']}"
                            break
                    if reason:
                        break
            if reason:
                blocked = self._record(
                    route_id, revision=route["revision"] + 1, status="blocked",
                    question_id=route["question_id"], hypothesis_id=route.get("hypothesis_id"),
                    workflow_id=route["workflow_id"], method_id=route["method_id"], budget=route["budget"],
                    write_set=route["write_set"], parent_route_id=route.get("parent_route_id"),
                    supersedes_route_id=route.get("supersedes_route_id"), runs_used=route.get("runs_used", 0),
                    reservations=reservations, stop_conditions=route.get("stop_conditions", []),
                    outputs=route.get("outputs", []), stop_reason=reason, source_refs=route["source_refs"],
                    task_id=route.get("task_id"), claim_id=route.get("claim_id"),
                    inputs=route.get("inputs", []), expected_evidence=route.get("expected_evidence", []),
                    assigned_role=route.get("assigned_role", self.producer["role"]),
                    verification_gates=route.get("verification_gates", []),
                )
                tx = self._commit_locked(operation_id, [blocked], expected={route_id: route["revision"]})
                return {"operation_id": operation_id, "status": "blocked", "reason": reason,
                        "route": copy.deepcopy(blocked), "transaction": tx}
            reservation = {"operation_id": operation_id, "status": "reserved",
                           "run_number": int(route.get("runs_used", 0)) + 1,
                           "write_set": sorted(route["write_set"])}
            reservations.append(reservation)
            updated = self._record(
                route_id, revision=route["revision"] + 1, status="active", question_id=route["question_id"],
                hypothesis_id=route.get("hypothesis_id"), workflow_id=route["workflow_id"],
                method_id=route["method_id"], budget=route["budget"], write_set=route["write_set"],
                parent_route_id=route.get("parent_route_id"), supersedes_route_id=route.get("supersedes_route_id"),
                runs_used=int(route.get("runs_used", 0)) + 1, reservations=reservations,
                stop_conditions=route.get("stop_conditions", []), outputs=route.get("outputs", []),
                stop_reason=None, source_refs=route["source_refs"], task_id=route.get("task_id"),
                claim_id=route.get("claim_id"), inputs=route.get("inputs", []),
                expected_evidence=route.get("expected_evidence", []),
                assigned_role=route.get("assigned_role", self.producer["role"]),
                verification_gates=route.get("verification_gates", []),
            )
            tx = self._commit_locked(operation_id, [updated], expected={route_id: route["revision"]})
            return {"operation_id": operation_id, "status": "reserved", "route": copy.deepcopy(updated), "transaction": tx}

    def finish(self, route_id: str, reservation_id: str, outcome: str, operation_id: str,
               *, outputs: list[Any] | None = None, stop_reason: str | None = None) -> dict[str, Any]:
        route_id, reservation_id, operation_id = (_id(route_id, "route_id"), _id(reservation_id, "reservation_id"),
                                                   _id(operation_id, "operation_id"))
        outcome = _nonempty(outcome, "outcome").casefold()
        outputs = _list_of_values(outputs or [], "outputs")
        if outcome not in _OUTCOMES:
            raise RouteLifecycleError("outcome must be completed, failed, or cannot_verify")
        if outcome != "completed":
            stop_reason = _nonempty(stop_reason, "stop_reason")
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=route_id)
            if old is not None:
                return old
            route = self._routes().get(route_id)
            if route is None:
                raise RouteLifecycleError(f"route is not present: {route_id}")
            reservations = copy.deepcopy(route.get("reservations", []))
            selected = next((item for item in reservations if item.get("operation_id") == reservation_id), None)
            if selected is None or selected.get("status") != "reserved":
                raise RouteLifecycleError("reservation is not active or cannot be recovered")
            selected.update({"status": outcome, "finish_operation_id": operation_id})
            selected["outputs"] = copy.deepcopy(outputs)
            selected["stop_reason"] = stop_reason
            new_outputs = copy.deepcopy(route.get("outputs", []))
            new_outputs.extend(copy.deepcopy(outputs))
            status = {"completed": "completed", "failed": "failed", "cannot_verify": "cannot_verify"}[outcome]
            updated = self._record(
                route_id, revision=route["revision"] + 1, status=status, question_id=route["question_id"],
                hypothesis_id=route.get("hypothesis_id"), workflow_id=route["workflow_id"],
                method_id=route["method_id"], budget=route["budget"], write_set=route["write_set"],
                parent_route_id=route.get("parent_route_id"), supersedes_route_id=route.get("supersedes_route_id"),
                runs_used=route.get("runs_used", 0), reservations=reservations,
                stop_conditions=route.get("stop_conditions", []), outputs=new_outputs,
                stop_reason=stop_reason, source_refs=route["source_refs"], task_id=route.get("task_id"),
                claim_id=route.get("claim_id"), inputs=route.get("inputs", []),
                expected_evidence=route.get("expected_evidence", []),
                assigned_role=route.get("assigned_role", self.producer["role"]),
                verification_gates=route.get("verification_gates", []),
            )
            tx = self._commit_locked(operation_id, [updated], expected={route_id: route["revision"]})
            return {"operation_id": operation_id, "status": status, "route": copy.deepcopy(updated), "transaction": tx}

    def reopen(self, route_id: str, operation_id: str) -> dict[str, Any]:
        route_id, operation_id = _id(route_id, "route_id"), _id(operation_id, "operation_id")
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=route_id)
            if old is not None:
                return old
            route = self._routes().get(route_id)
            if route is None:
                raise RouteLifecycleError(f"route is not present: {route_id}")
            if route["status"] not in {"blocked", "failed", "cannot_verify"}:
                raise RouteLifecycleError(f"route cannot be reopened from status {route['status']}")
            updated = self._record(
                route_id, revision=route["revision"] + 1, status="proposed", question_id=route["question_id"],
                hypothesis_id=route.get("hypothesis_id"), workflow_id=route["workflow_id"],
                method_id=route["method_id"], budget=route["budget"], write_set=route["write_set"],
                parent_route_id=route.get("parent_route_id"), supersedes_route_id=route.get("supersedes_route_id"),
                runs_used=route.get("runs_used", 0), reservations=route.get("reservations", []),
                stop_conditions=route.get("stop_conditions", []), outputs=route.get("outputs", []),
                stop_reason=None, source_refs=route["source_refs"], task_id=route.get("task_id"),
                claim_id=route.get("claim_id"), inputs=route.get("inputs", []),
                expected_evidence=route.get("expected_evidence", []),
                assigned_role=route.get("assigned_role", self.producer["role"]),
                verification_gates=route.get("verification_gates", []),
            )
            tx = self._commit_locked(operation_id, [updated], expected={route_id: route["revision"]})
            return {"operation_id": operation_id, "status": "proposed", "route": copy.deepcopy(updated), "transaction": tx}

    def reject(self, route_id: str, operation_id: str, reason: str) -> dict[str, Any]:
        """Close a route proposal without treating it as a scientific result."""
        route_id, operation_id = _id(route_id, "route_id"), _id(operation_id, "operation_id")
        reason = _nonempty(reason, "reason")
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=route_id)
            if old is not None:
                return old
            route = self._routes().get(route_id)
            if route is None:
                raise RouteLifecycleError(f"route is not present: {route_id}")
            if route["status"] not in {"proposed", "blocked", "failed", "cannot_verify"}:
                raise RouteLifecycleError(f"route cannot be rejected from status {route['status']}")
            if any(item.get("status") == "reserved" for item in route.get("reservations", [])):
                raise RouteLifecycleError("cannot reject a route with an active reservation")
            updated = self._record(
                route_id, revision=route["revision"] + 1, status="rejected", question_id=route["question_id"],
                hypothesis_id=route.get("hypothesis_id"), workflow_id=route["workflow_id"],
                method_id=route["method_id"], budget=route["budget"], write_set=route.get("write_set", ["route"]),
                parent_route_id=route.get("parent_route_id"), supersedes_route_id=route.get("supersedes_route_id"),
                runs_used=route.get("runs_used", 0), reservations=route.get("reservations", []),
                stop_conditions=route.get("stop_conditions", []), outputs=route.get("outputs", []),
                stop_reason=reason, source_refs=route["source_refs"], task_id=route.get("task_id"),
                claim_id=route.get("claim_id"), inputs=route.get("inputs", []),
                expected_evidence=route.get("expected_evidence", []),
                assigned_role=route.get("assigned_role", self.producer["role"]),
                verification_gates=route.get("verification_gates", []),
            )
            tx = self._commit_locked(operation_id, [updated], expected={route_id: route["revision"]})
            return {"operation_id": operation_id, "status": "rejected", "route": copy.deepcopy(updated), "transaction": tx}

    def supersede(self, route_id: str, superseded_route_id: str, operation_id: str) -> dict[str, Any]:
        route_id, superseded_route_id, operation_id = (_id(route_id, "route_id"), _id(superseded_route_id, "superseded_route_id"),
                                                        _id(operation_id, "operation_id"))
        if route_id == superseded_route_id:
            raise RouteLifecycleError("a route cannot supersede itself")
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=route_id)
            if old is not None:
                return old
            routes = self._routes()
            current, previous = routes.get(route_id), routes.get(superseded_route_id)
            if current is None or previous is None:
                raise RouteLifecycleError("both route and superseded_route must be present")
            if current.get("question_id") != previous.get("question_id"):
                raise RouteLifecycleError("replacement and superseded route must address the same ResearchQuestion")
            if previous.get("status") == "superseded":
                raise RouteLifecycleError("superseded route is already superseded")
            if any(item.get("status") == "reserved" for item in previous.get("reservations", [])):
                raise RouteLifecycleError("cannot supersede a route with an active reservation")
            replacement = self._record(
                route_id, revision=current["revision"] + 1, status=current["status"], question_id=current["question_id"],
                hypothesis_id=current.get("hypothesis_id"), workflow_id=current["workflow_id"], method_id=current["method_id"],
                budget=current["budget"], write_set=current["write_set"], parent_route_id=current.get("parent_route_id"),
                supersedes_route_id=superseded_route_id, runs_used=current.get("runs_used", 0),
                reservations=current.get("reservations", []), stop_conditions=current.get("stop_conditions", []),
                outputs=current.get("outputs", []), stop_reason=current.get("stop_reason"), source_refs=current["source_refs"],
                task_id=current.get("task_id"), claim_id=current.get("claim_id"),
                inputs=current.get("inputs", []), expected_evidence=current.get("expected_evidence", []),
                assigned_role=current.get("assigned_role", self.producer["role"]),
                verification_gates=current.get("verification_gates", []),
            )
            retired = self._record(
                superseded_route_id, revision=previous["revision"] + 1, status="superseded", question_id=previous["question_id"],
                hypothesis_id=previous.get("hypothesis_id"), workflow_id=previous["workflow_id"], method_id=previous["method_id"],
                budget=previous["budget"], write_set=previous["write_set"], parent_route_id=previous.get("parent_route_id"),
                supersedes_route_id=previous.get("supersedes_route_id"), runs_used=previous.get("runs_used", 0),
                reservations=previous.get("reservations", []), stop_conditions=previous.get("stop_conditions", []),
                outputs=previous.get("outputs", []), stop_reason="superseded", source_refs=previous["source_refs"],
                task_id=previous.get("task_id"), claim_id=previous.get("claim_id"),
                inputs=previous.get("inputs", []), expected_evidence=previous.get("expected_evidence", []),
                assigned_role=previous.get("assigned_role", self.producer["role"]),
                verification_gates=previous.get("verification_gates", []),
            )
            edge = {"schema_version": 1, "relationship_id": f"edge.{_digest([operation_id, route_id, superseded_route_id])[:32]}",
                    "revision": 1, "project_id": self.store.project_id, "relation": "route_supersedes_route",
                    "from_id": route_id, "from_revision": replacement["revision"], "to_id": superseded_route_id,
                    "to_revision": retired["revision"], "source_refs": [f"route:{route_id}"]}
            tx = self._commit_locked(operation_id, [replacement, retired], [edge],
                                     expected={route_id: current["revision"], superseded_route_id: previous["revision"]})
            return {"operation_id": operation_id, "status": "superseded", "route": replacement,
                    "superseded_route": retired, "transaction": tx}

    def compare(self, question_id: str, comparison_id: str, operation_id: str,
                route_ids: list[str] | None = None, *, stop_reason: str | None = None) -> dict[str, Any]:
        question_id, comparison_id, operation_id = (_id(question_id, "question_id"), _id(comparison_id, "comparison_id"),
                                                     _id(operation_id, "operation_id"))
        with self.store.writer(operation_id):
            old = self._idempotent(operation_id, route_id=comparison_id)
            if old is not None:
                return old
            routes = self._routes()
            if route_ids is not None and not isinstance(route_ids, list):
                raise RouteLifecycleError("route_ids must be a list")
            selected = sorted({_id(item, "route_id") for item in (route_ids or [])})
            if not selected:
                selected = sorted(rid for rid, route in routes.items() if route.get("question_id") == question_id)
            if not selected:
                raise RouteLifecycleError("comparison requires at least one route")
            chosen = []
            for rid in selected:
                route = routes.get(rid)
                if route is None or route.get("question_id") != question_id:
                    raise RouteLifecycleError(f"route does not belong to question {question_id}: {rid}")
                chosen.append(route)
            claim_ids = sorted({route.get("claim_id") for route in chosen if route.get("claim_id") is not None})
            if len(claim_ids) > 1:
                raise RouteLifecycleError("comparison routes must target one Claim or no Claim")
            entries = [{"route_id": route["id"], "status": route["status"],
                        "runs_used": route.get("runs_used", 0), "budget": route["budget"],
                        "outputs": copy.deepcopy(route.get("outputs", [])),
                        "stop_reason": route.get("stop_reason"), "claim_id": route.get("claim_id"),
                        "write_set": sorted(route.get("write_set", []))} for route in chosen]
            comparison = {"schema_version": 1, "type": "RouteComparison", "id": comparison_id,
                          "revision": 1, "project_id": self.store.project_id,
                          "scope": {"project_id": self.store.project_id, "research_question_id": question_id},
                          "source_refs": [f"comparison:{comparison_id}"], "question_id": question_id,
                          "route_ids": selected, "entries": entries, "status": "archived",
                          "stop_reason": stop_reason, "claim_id": claim_ids[0] if claim_ids else None}
            relationships = [{"schema_version": 1,
                              "relationship_id": f"edge.{_digest([comparison_id, rid])[:32]}",
                              "revision": 1, "project_id": self.store.project_id,
                              "relation": "route_in_comparison", "from_id": comparison_id,
                              "from_revision": 1, "to_id": rid, "to_revision": routes[rid]["revision"],
                              "source_refs": [f"comparison:{comparison_id}"]} for rid in selected]
            tx = self._commit_locked(operation_id, [comparison], relationships,
                                     expected={route["id"]: route["revision"] for route in chosen})
            return {"operation_id": operation_id, "comparison": comparison, "transaction": tx}


__all__ = ["RouteLifecycle", "RouteLifecycleError"]
