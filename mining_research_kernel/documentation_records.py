"""Persist one explicitly requested, read-only documentation observation."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from providers.documentation import load_registration, resolve_documentation
from research_project import load_config
from mining_research_kernel.records import ResearchStore, ResearchStoreError, WriterLockedError
from mining_research_kernel.r2_workflow import (
    _edge_id, _id, _record, _relationship, _sha256_bytes, _task_ids,
)
from mining_research_kernel.task_engine import TaskEngine
from workflows.research import build_research_workflow_pack


WORKFLOW_ID = "mining_research_kernel.workflow.research"
TASK_TYPE = "mining_research_kernel.task.evidence_review"
_PRODUCER = {"role": "host", "model": "documentation_records"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _registration_summary(registration: Any, page: Any) -> dict[str, Any]:
    return {
        "source_id": registration.source_id,
        "product": registration.product,
        "document_family": registration.document_family,
        "document_build": registration.document_build,
        "trust_class": registration.trust_class,
        "page": page,
        "registered_page_sha256": registration.pages.get(page),
    }


def _replay(store: ResearchStore, task_id: str, request_sha256: str) -> dict[str, Any] | None:
    task = store.latest_record(task_id, "TaskState")
    if task is None:
        return None
    packet = task.get("packet", {})
    result = task.get("operation_results", {}).get("documentation_query")
    if not isinstance(result, dict):
        raise ValueError(f"task_id already exists for a different task: {task_id}")
    if result.get("request_sha256") != request_sha256:
        raise ValueError(f"task_id already records a different documentation query: {task_id}")
    decision_id = result.get("decision_id")
    decision = store.latest_record(decision_id, "Decision") if isinstance(decision_id, str) else None
    return {
        "documentation_result": copy.deepcopy(packet.get("documentation_result")),
        "task_id": task_id,
        "decision_id": decision_id,
        "replayed": True,
        "query_performed": False,
        "task_packet": copy.deepcopy(packet),
        "decision": decision,
    }


def record_documentation_query(
    project_root: str | Path,
    *,
    task_id: str,
    question: str,
    registration: str | Path,
    page: str,
    command: str,
    product: str,
    product_version: str,
    anchor: str | None = None,
    task_context: str = "production",
) -> dict[str, Any]:
    """Verify and persist a single provider-owned documentation query result.

    ``registration`` is a host-selected registration file. The provider reads
    it and the referenced page; callers cannot supply verification results.
    Repeating a task ID with the same query returns its stored observation
    without reopening the documentation page.
    """
    selected_root = Path(project_root).expanduser()
    task_id = _id(task_id, "task_id")
    ids = _task_ids(task_id)
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")

    try:
        config = load_config(selected_root)
    except Exception as exc:
        raise ValueError(f"research records are not enabled for this project: {exc}") from exc
    root = selected_root.resolve()
    store = ResearchStore(root)

    # Loading the host-selected registration is safe before the writer lock;
    # the immutable summary binds retries without persisting host paths.
    source = load_registration(registration)
    source_summary = _registration_summary(source, page)
    request_value = {
        "task_id": task_id,
        "question": question.strip(),
        "registration": source_summary,
        "page": page,
        "command": command,
        "product": product,
        "product_version": product_version,
        "anchor": anchor,
        "task_context": task_context,
    }
    request_sha256 = _sha256_bytes(_canonical_bytes(request_value))
    operation_id = "documentation-query." + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]

    # The project writer is deliberately non-blocking. Briefly retry lock
    # contention so simultaneous identical calls converge on the committed
    # result; after acquiring it, a different request for the same task fails.
    deadline = time.monotonic() + 5.0
    while True:
        try:
            writer = store.writer(operation_id)
            writer.__enter__()
            break
        except WriterLockedError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
    try:
        prior = _replay(store, task_id, request_sha256)
        if prior is not None:
            return prior

        request = {
            "project_id": store.project_id,
            "task_id": task_id,
            "workflow_id": WORKFLOW_ID,
            "task_type": TASK_TYPE,
            "maturity": "known_workflow",
            "max_runs": 1,
            "route_id": ids["route"],
            "routes": [ids["route"]],
            "allowed_tools": ["evidence.read_only"],
            "verification_gates": [],
            "task_context": task_context,
            "input": {"question": question.strip(), "page": page, "command": command,
                      "product": product, "product_version": product_version,
                      "anchor": anchor},
        }
        pack = build_research_workflow_pack(config, request, {})
        provider_result = resolve_documentation(
            {"provider": "local"}, registration=source,
        ).verify_syntax(
            page, command, product=product, product_version=product_version,
            anchor=anchor, task_context=task_context,
        )
        result = copy.deepcopy(provider_result)

        snapshot = {
            "schema_version": 1,
            "kind": "documentation_query_observation",
            "request": request_value,
            "registration_summary": source_summary,
            "documentation_result": result,
            "coverage": {
                "coverage_scope": result.get("coverage_scope"),
                "uncovered": copy.deepcopy(result.get("uncovered", [])),
                "source_page_read": result.get("citation", {}).get("sha256_body") is not None,
            },
        }
        snapshot_hash = _sha256_bytes(_canonical_bytes(snapshot))
        route_id = ids["route"]
        source_refs = [f"task:{task_id}", f"route:{route_id}"]
        locator = {
            "path": f"record:{ids['asset']}#payload",
            "path_kind": "record_embedded",
            "record_id": ids["asset"],
            "field": "payload",
            "citation": {
                "source_id": source.source_id,
                "document_build": source.document_build,
                "page": page,
                "anchor": anchor,
            },
            "caller_label": f"documentation-query:{task_id}",
            "source_id": source.source_id,
            "page": page,
            "anchor": anchor,
            "embedded_payload": "payload",
        }
        question_record = _record(
            "ResearchQuestion", ids["question"], store.project_id, source_refs,
            statement=question.strip(), status="active",
        )
        claim_record = _record(
            "Claim", ids["claim"], store.project_id, source_refs,
            statement=f"Documentation query observation for {command!r} on {page}.",
            status="proposed",
        )
        route = _record(
            "Route", route_id, store.project_id, source_refs,
            status="completed" if result.get("status") in {"VERIFIED", "SYNTHETIC_VERIFIED"} else "cannot_verify",
            route_id=route_id, question_id=ids["question"],
            research_question_id=ids["question"], hypothesis_id=None,
            claim_id=ids["claim"], task_id=task_id, parent_route_id=None,
            supersedes_route_id=None, workflow_id=WORKFLOW_ID,
            method_id="mining_research_kernel.method.research.evidence_review",
            inputs=[copy.deepcopy(request_value)],
            expected_evidence=["bounded documentation query observation"],
            assigned_role="host", budget=1, runs_used=0,
            stop_conditions=[], verification_gates=[], outputs=[ids["evidence"]],
            reservations=[], write_set=["research/records"],
        )
        asset = _record(
            "Asset", ids["asset"], store.project_id, source_refs,
            asset_kind="documentation_query_snapshot", locator=locator,
            content_sha256=snapshot_hash, authority="derived", status="observed",
            payload=snapshot,
        )
        evidence = _record(
            "Evidence", ids["evidence"], store.project_id, source_refs,
            evidence_kind="documentation_query_observation", asset_ref=ids["asset"],
            locator=locator, status="observed",
        )

        judgment_status = ("PROVISIONAL_WITH_GAPS"
                           if result.get("status") in {"VERIFIED", "SYNTHETIC_VERIFIED"}
                           else "INSUFFICIENT")
        gaps = copy.deepcopy(result.get("uncovered", []))
        if judgment_status == "INSUFFICIENT":
            gaps.insert(0, result.get("stop_reason", "documentation_query_cannot_verify"))
        if not gaps:
            gaps = ["query coverage is limited to the provider's documented syntax scope"]
        uncovered_label = ",".join(str(item) for item in result.get("uncovered", [])) or "none reported"
        coverage_label = (f"{result.get('coverage_scope', 'unknown coverage')}; "
                          f"uncovered={uncovered_label}")
        requested_version = request_value["product_version"]
        status_label = str(result.get("status", "CANNOT_VERIFY"))
        summary = (
            f"Command {command!r}, requested version {requested_version}: "
            f"{status_label}; coverage={coverage_label}. "
            + ("Broader applicability remains open. " if judgment_status == "PROVISIONAL_WITH_GAPS"
               else f"Provider stop reason: {result.get('stop_reason', 'unknown reason')}. ")
            + "Current project, model, and engineering applicability remain unverified."
        )
        assessment = {
            "scope": "documentation_syntax_query_only",
            "request": copy.deepcopy(request_value),
            "registration_summary": source_summary,
            "documentation_result": result,
            "coverage": copy.deepcopy(snapshot["coverage"]),
            "snapshot_sha256": snapshot_hash,
        }
        judgment = {
            "status": judgment_status,
            "summary": summary,
            "gaps": gaps,
            "next_action": {
                "action": "Consider reviewing the recorded source and uncovered scope",
                "executable": False,
                "requires_user_choice": True,
            },
        }
        decision_id = "decision.documentation." + hashlib.sha256(
            (task_id + "|" + request_sha256).encode("utf-8")
        ).hexdigest()[:24]
        decision = _record(
            "Decision", decision_id, store.project_id, source_refs,
            status=judgment_status.lower(), statement=summary,
            scope={"project_id": store.project_id, "task_id": task_id,
                   "route_id": route_id, "kind": assessment["scope"]},
            assessment=assessment, judgment=judgment,
        )

        packet = TaskEngine(config, pack).start(request)
        packet.update({
            "state": "completed",
            "documentation_required": False,
            "documentation_status": result.get("status", "CANNOT_VERIFY"),
            "documentation_result": result,
            "asset_refs": [ids["asset"]],
            "evidence_refs": [ids["evidence"]],
            "citation_refs": [ids["evidence"]],
            "review_status": "recorded",
            "review_record_ref": decision_id,
            "research_judgment_status": judgment_status,
            "completion_scope": "documentation_query_observation_recorded",
            "material_reads": [{
                "asset_id": ids["asset"], "evidence_refs": [ids["evidence"]],
                "locator": locator, "registration_status": "registered",
                "locator_status": "embedded_snapshot",
                "content_status": "snapshot_hash_verified",
                "reading_status": "READ_WITH_LIMITS",
                "verification_status": ("PARTIALLY_VERIFIED" if judgment_status == "PROVISIONAL_WITH_GAPS"
                                         else "NOT_VERIFIED"),
                "asset_kind": "documentation_query_snapshot", "authority": "derived",
                "asset_status": "observed", "content_sha256": snapshot_hash,
            }],
            "material_gaps": [{"asset_id": ids["asset"],
                               "reason": "query result has bounded coverage",
                               "next_action": "review uncovered scope before broader conclusions"}],
            "next_action": {"action_id": None, "executable": False, "input_refs": [],
                            "expected_outputs": [], "preconditions": [],
                            "reason": "documentation_query_recorded",
                            "resume_condition": "start a new task with a new task_id to reread documentation"},
        })
        packet.setdefault("history", []).append({
            "event": "documentation_query_recorded", "from": "ready",
            "to": "completed", "decision_id": decision_id,
            "documentation_status": result.get("status"),
        })
        operation_result = {
            "status": "recorded", "request_sha256": request_sha256,
            "decision_id": decision_id, "asset_id": ids["asset"],
            "evidence_id": ids["evidence"], "documentation_result": result,
        }
        task_record = _record(
            "TaskState", task_id, store.project_id, source_refs,
            task_id=task_id, state="completed", packet=packet,
            operation_results={"documentation_query": operation_result},
        )
        relationships = [
            _relationship(_edge_id(task_id, "route-addresses"), "route_addresses_question",
                          route, question_record, store.project_id, source_refs),
            _relationship(_edge_id(task_id, "route-targets-claim"), "route_targets_claim",
                          route, claim_record, store.project_id, source_refs),
            _relationship(_edge_id(task_id, "route-reads-asset"), "route_reads_asset",
                          route, asset, store.project_id, source_refs),
            _relationship(_edge_id(task_id, "route-reads-evidence"), "route_reads_evidence",
                          route, evidence, store.project_id, source_refs),
            _relationship(_edge_id(task_id, "evidence-derived-asset"), "evidence_derived_from_asset",
                          evidence, asset, store.project_id, source_refs),
            _relationship(_edge_id(task_id, "decision-records-evidence"), "decision_records_evidence",
                          decision, evidence, store.project_id, source_refs),
            _relationship(_edge_id(task_id, "decision-closes-route"), "decision_closes_route",
                          decision, route, store.project_id, source_refs),
        ]
        transaction = store.commit(
            operation_id, dict(_PRODUCER),
            [question_record, claim_record, route, asset, evidence, decision, task_record],
            relationships, lock_held=True,
        )
        return {
            "documentation_result": result,
            "task_id": task_id,
            "decision_id": decision_id,
            "replayed": False,
            "query_performed": True,
            "task_packet": packet,
            "decision": decision,
            "transaction": transaction,
        }
    finally:
        writer.__exit__(None, None, None)


__all__ = ["record_documentation_query"]
