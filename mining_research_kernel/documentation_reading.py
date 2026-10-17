"""Durable, bounded documentation passage observations."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from mining_research_kernel.documentation_records import _registration_summary
from mining_research_kernel.records import ResearchStore, WriterLockedError
from mining_research_kernel.r2_workflow import (
    _edge_id,
    _id,
    _record,
    _relationship,
    _sha256_bytes,
    _task_ids,
)
from mining_research_kernel.task_engine import TaskEngine
from providers.documentation import load_registration as load_local_registration
from providers.documentation import read_local_documentation
from providers.itasca import query_itasca
from research_project import load_config
from workflows.research import build_research_workflow_pack

WORKFLOW_ID = "mining_research_kernel.workflow.research"
TASK_TYPE = "mining_research_kernel.task.evidence_review"
_PRODUCER = {"role": "host", "model": "documentation_reading"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def _read_registration(provider: str, registration: Any, page: str | None) -> tuple[Any, dict[str, Any]]:
    if provider == "local":
        source = load_local_registration(registration)
        return source, _registration_summary(source, page)
    from providers.itasca import load_registration

    profile = load_registration(registration)
    summary = {
        "kind": "itasca_stdio",
        "instance_fingerprint": _sha256_bytes(_canonical_bytes(profile)),
    }
    return profile, summary


def _acquire_writer(store: ResearchStore, operation_id: str):
    deadline = time.monotonic() + 5.0
    while True:
        try:
            writer = store.writer(operation_id)
            writer.__enter__()
            return writer
        except WriterLockedError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)


def _replay(store: ResearchStore, task_id: str, request_hash: str) -> dict[str, Any] | None:
    task = store.latest_record(task_id, "TaskState")
    if task is None:
        return None
    operation = task.get("operation_results", {}).get("documentation_reading")
    if not isinstance(operation, dict):
        raise ValueError(f"task_id already exists for a different task: {task_id}")
    if operation.get("request_sha256") != request_hash:
        raise ValueError(f"task_id already records a different documentation reading: {task_id}")
    return {
        "task_packet": copy.deepcopy(task.get("packet")),
        "documentation_result": copy.deepcopy(operation.get("documentation_result")),
        "reading_texts": [],
        "query_performed": False,
        "source_read_performed": False,
        "replayed": True,
        "decision_id": operation.get("decision_id"),
    }


def _task_request(store: ResearchStore, task_id: str, question: str, request: dict[str, Any],
                  ids: dict[str, str], task_context: str) -> dict[str, Any]:
    return {
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
        "input": {
            "question": question,
            "provider": request["provider"],
            "page": request["page"],
            "product": request["product"],
            "product_version": request["product_version"],
            "operation": request["operation"],
            "software": request["software"],
            "version": request["version"],
            "command": request["command"],
            "anchor": request["anchor"],
        },
    }


def record_documentation_reading(
    project_root: str | Path,
    *,
    task_id: str,
    question: str,
    registration: Any,
    provider: str = "local",
    page: str | None = None,
    product: str | None = None,
    product_version: str | None = None,
    anchor: str | None = None,
    operation: str | None = None,
    software: str | None = None,
    version: str | None = None,
    query: str | None = None,
    command: str | None = None,
    topic: str | None = None,
    limit: int = 10,
    max_reading_chars: int = 12000,
    task_context: str = "production",
) -> dict[str, Any]:
    """Read documentation, save a bounded snapshot, and replay without rereading."""
    selected_root = Path(project_root).expanduser()
    task_id = _id(task_id, "task_id")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    if provider not in {"local", "itasca"}:
        raise ValueError("provider must be local or itasca")
    if task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")

    config = load_config(selected_root)
    store = ResearchStore(selected_root.resolve())
    ids = _task_ids(task_id)
    source, registration_summary = _read_registration(provider, registration, page)
    request = {
        "task_id": task_id,
        "question": question.strip(),
        "provider": provider,
        "registration_summary": registration_summary,
        "page": page,
        "product": product,
        "product_version": product_version,
        "anchor": anchor,
        "operation": operation,
        "software": software,
        "version": version,
        "query": query,
        "command": command,
        "topic": topic,
        "limit": limit,
        "max_reading_chars": max_reading_chars,
        "task_context": task_context,
    }
    request_hash = _sha256_bytes(_canonical_bytes(request))
    operation_id = "documentation-reading." + hashlib.sha256(task_id.encode()).hexdigest()[:32]
    writer = _acquire_writer(store, operation_id)
    try:
        replay = _replay(store, task_id, request_hash)
        if replay is not None:
            return replay

        if provider == "local":
            result = read_local_documentation(
                source,
                page=page,
                product=product,
                product_version=product_version,
                anchor=anchor,
                max_reading_chars=max_reading_chars,
                task_context=task_context,
            )
        else:
            result = query_itasca(
                source,
                operation=operation,
                software=software,
                version=version,
                query=query,
                command=command,
                topic=topic,
                limit=limit,
                max_reading_chars=max_reading_chars,
            )

        reading_texts = result.pop("reading_texts", [])
        query_performed = bool(result.pop("_query_performed", False))
        result["uncovered"] = list(result.get("uncovered", []))
        # Defense in depth: transient source text never enters the ledger and
        # total stored excerpt text remains bounded across every provider.
        saved_remaining = 2000
        saved_passages = []
        for passage in result.get("passages", []):
            excerpt = str(passage.get("text", ""))[:saved_remaining]
            if not excerpt:
                continue
            saved_remaining -= len(excerpt)
            saved_passages.append({**passage, "text": excerpt,
                                   "truncated": bool(passage.get("truncated")) or len(excerpt) < len(passage.get("text", "")),
                                   "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest()})
        result["passages"] = saved_passages

        reading_succeeded = result.get("status") == "READ_WITH_LIMITS" and bool(saved_passages)
        citation = result.get("citation", {})
        route_id = ids["route"]
        source_refs = [f"task:{task_id}", f"route:{route_id}"]
        locator = {
            "path": f"record:{ids['asset']}#payload",
            "path_kind": "record_embedded",
            "record_id": ids["asset"],
            "field": "payload",
            "citation": {key: citation.get(key) for key in (
                "source_id", "product", "document_build", "page", "anchor",
                "trust_class", "sha256_body",
            )},
            "caller_label": f"documentation-reading:{task_id}",
            "source_id": citation.get("source_id"),
            "page": citation.get("page"),
            "anchor": citation.get("anchor"),
            "embedded_payload": "payload",
        }
        coverage = {
            "coverage_scope": result.get("coverage_scope"),
            "uncovered": copy.deepcopy(result["uncovered"]),
            "source_page_read": reading_succeeded,
            "passages_saved": len(saved_passages),
        }
        payload = {
            "schema_version": 1,
            "kind": "documentation_query_observation",
            "request": request,
            "registration_summary": registration_summary,
            "documentation_result": result,
            "coverage": coverage,
        }
        payload_hash = _sha256_bytes(_canonical_bytes(payload))

        question_record = _record(
            "ResearchQuestion", ids["question"], store.project_id, source_refs,
            statement=question.strip(), status="active",
        )
        claim_record = _record(
            "Claim", ids["claim"], store.project_id, source_refs,
            statement=f"Documentation reading observation for {question.strip()}.",
            status="proposed",
        )
        route = _record(
            "Route", route_id, store.project_id, source_refs,
            status="completed" if reading_succeeded else "cannot_verify",
            route_id=route_id, question_id=ids["question"],
            research_question_id=ids["question"], hypothesis_id=None,
            claim_id=ids["claim"], task_id=task_id, parent_route_id=None,
            supersedes_route_id=None, workflow_id=WORKFLOW_ID,
            method_id="mining_research_kernel.method.research.evidence_review",
            inputs=[request], expected_evidence=["bounded documentation passage"],
            assigned_role="host", budget=1, runs_used=0, stop_conditions=[],
            verification_gates=[], outputs=[ids["evidence"]], reservations=[],
            write_set=["research/records"],
        )
        asset = _record(
            "Asset", ids["asset"], store.project_id, source_refs,
            asset_kind="documentation_query_snapshot", locator=locator,
            content_sha256=payload_hash, authority="derived", status="observed",
            payload=payload,
        )
        evidence = _record(
            "Evidence", ids["evidence"], store.project_id, source_refs,
            evidence_kind="documentation_query_observation", asset_ref=ids["asset"],
            locator=locator, status="observed",
        )

        insufficient_applicability = result.get("applicability_status") == "INSUFFICIENT"
        judgment_status = ("PROVISIONAL_WITH_GAPS"
                           if reading_succeeded and not insufficient_applicability
                           else "INSUFFICIENT")
        gaps = copy.deepcopy(result["uncovered"])
        if judgment_status == "INSUFFICIENT":
            gaps.insert(0, result.get("stop_reason") or "documentation_read_failed")
        statement = (
            f"Documentation reading {result.get('status')}; "
            f"coverage={result.get('coverage_scope')}; applicability remains open."
        )
        decision_id = "decision.documentation." + hashlib.sha256(
            (task_id + "|" + request_hash).encode()
        ).hexdigest()[:24]
        assessment = {
            "scope": "documentation_passage_reading_only",
            "request": request,
            "registration_summary": registration_summary,
            "documentation_result": result,
            "coverage": coverage,
            "snapshot_sha256": payload_hash,
        }
        decision = _record(
            "Decision", decision_id, store.project_id, source_refs,
            status=judgment_status.lower(), statement=statement,
            scope={"project_id": store.project_id, "task_id": task_id,
                   "route_id": route_id, "kind": assessment["scope"]},
            assessment=assessment,
            judgment={
                "status": judgment_status,
                "summary": statement,
                "gaps": gaps,
                "next_action": {
                    "action": "Review bounded source passages and applicability",
                    "executable": False,
                    "requires_user_choice": True,
                },
            },
        )

        task_request = _task_request(store, task_id, question.strip(), request, ids, task_context)
        pack = build_research_workflow_pack(config, task_request, {})
        packet = TaskEngine(config, pack).start(task_request)
        packet.update({
            "state": "completed",
            "documentation_required": False,
            "documentation_status": "CANNOT_VERIFY",
            "documentation_result": result,
            "asset_refs": [ids["asset"]],
            "evidence_refs": [ids["evidence"]],
            "citation_refs": [ids["evidence"]],
            "review_status": "recorded",
            "review_record_ref": decision_id,
            "research_judgment_status": judgment_status,
            "completion_scope": "documentation_reading_observation_recorded",
            "material_reads": [{
                "asset_id": ids["asset"],
                "evidence_refs": [ids["evidence"]],
                "locator": locator,
                "registration_status": "registered",
                "locator_status": "embedded_snapshot",
                "content_status": "snapshot_hash_verified",
                "reading_status": "READ_WITH_LIMITS" if reading_succeeded else "READ_INSUFFICIENT",
                "verification_status": "NOT_VERIFIED",
                "asset_kind": "documentation_query_snapshot",
                "authority": "derived",
                "asset_status": "observed",
                "content_sha256": payload_hash,
            }],
            "material_gaps": [{
                "asset_id": ids["asset"],
                "reason": "bounded documentation coverage",
                "next_action": "review uncovered scope before broader conclusions",
            }],
            "next_action": {
                "action_id": None, "executable": False, "input_refs": [],
                "expected_outputs": [], "preconditions": [],
                "reason": "documentation_reading_recorded",
                "resume_condition": "start a new task with a new task_id to reread documentation",
            },
        })
        packet.setdefault("history", []).append({
            "event": "documentation_reading_recorded",
            "from": "ready",
            "to": "completed",
            "decision_id": decision_id,
            "documentation_status": result.get("status"),
        })

        operation_result = {
            "status": "recorded",
            "request_sha256": request_hash,
            "decision_id": decision_id,
            "asset_id": ids["asset"],
            "evidence_id": ids["evidence"],
            "documentation_result": result,
        }
        task_record = _record(
            "TaskState", task_id, store.project_id, source_refs,
            task_id=task_id, state="completed", packet=packet,
            operation_results={"documentation_reading": operation_result},
        )
        relationship_specs = [
            ("route-addresses", "route_addresses_question", route, question_record),
            ("route-claim", "route_targets_claim", route, claim_record),
            ("route-asset", "route_reads_asset", route, asset),
            ("route-evidence", "route_reads_evidence", route, evidence),
            ("evidence-asset", "evidence_derived_from_asset", evidence, asset),
            ("decision-evidence", "decision_records_evidence", decision, evidence),
            ("decision-route", "decision_closes_route", decision, route),
        ]
        relationships = [
            _relationship(_edge_id(task_id, suffix), kind, source_record,
                          target_record, store.project_id, source_refs)
            for suffix, kind, source_record, target_record in relationship_specs
        ]
        store.commit(
            operation_id, dict(_PRODUCER),
            [question_record, claim_record, route, asset, evidence, decision, task_record],
            relationships, lock_held=True,
        )
        return {
            "task_packet": packet,
            "documentation_result": result,
            "reading_texts": reading_texts,
            "query_performed": query_performed,
            "source_read_performed": reading_succeeded,
            "replayed": False,
            "decision_id": decision_id,
        }
    finally:
        writer.__exit__(None, None, None)


__all__ = ["record_documentation_reading"]
