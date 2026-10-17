"""Persist caller-supplied Zotero reading observations as durable records."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from research_project import load_config
from mining_research_kernel.records import ResearchStore, WriterLockedError
from mining_research_kernel.r2_workflow import (
    _edge_id, _id, _record, _relationship, _sha256_bytes, _task_ids,
)
from mining_research_kernel.task_engine import TaskEngine
from mining_research_kernel.zotero_reading import validate_capture
from workflows.research import build_research_workflow_pack


WORKFLOW_ID = "mining_research_kernel.workflow.research"
TASK_TYPE = "mining_research_kernel.task.evidence_review"
_PRODUCER = {"role": "host", "model": "zotero_records"}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _validated_capture(value: Any, task_context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("capture must be an object")
    candidate = copy.deepcopy(value)
    try:
        checked = validate_capture(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid Zotero reading capture: {exc}") from exc
    candidate = checked
    origin = candidate.get("origin")
    if origin == "synthetic" and task_context != "synthetic":
        raise ValueError("synthetic Zotero captures require synthetic task_context")
    return candidate


def _validated_findings(value: Any, capture: Mapping[str, Any]) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("findings must be a list")
    pages = capture.get("pages", [])
    normalized: list[dict[str, Any]] = []
    for index, finding in enumerate(value):
        field = f"findings[{index}]"
        if not isinstance(finding, Mapping) or set(finding) != {"statement", "citation"}:
            raise ValueError(f"{field} must contain exactly statement and citation")
        statement = finding.get("statement")
        citation = finding.get("citation")
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError(f"{field}.statement must be a non-empty string")
        if not isinstance(citation, Mapping) or set(citation) != {
            "attachment_key", "start_page", "end_page",
        }:
            raise ValueError(f"{field}.citation must identify an attachment and page range")
        attachment_key = citation.get("attachment_key")
        start, end = citation.get("start_page"), citation.get("end_page")
        if (not isinstance(attachment_key, str) or isinstance(start, bool)
                or not isinstance(start, int) or isinstance(end, bool) or not isinstance(end, int)
                or start < 1 or end < start):
            raise ValueError(f"{field}.citation has an invalid attachment or page range")
        covered = any(
            isinstance(page, Mapping)
            and page.get("attachment_key") == attachment_key
            and page.get("status") == "read"
            and isinstance(page.get("start_page"), int)
            and isinstance(page.get("end_page"), int)
            and page["start_page"] <= start and end <= page["end_page"]
            for page in pages
        )
        if not covered:
            raise ValueError(f"{field}.citation is not covered by a read capture page")
        normalized.append({
            "statement": statement.strip(),
            "citation": {"attachment_key": attachment_key,
                         "start_page": start, "end_page": end},
            "interpretation_status": "agent_interpretation_unverified",
        })
    return normalized


def _replay(store: ResearchStore, task_id: str, request_sha256: str) -> dict[str, Any] | None:
    task = store.latest_record(task_id, "TaskState")
    if task is None:
        return None
    packet = task.get("packet", {})
    result = task.get("operation_results", {}).get("zotero_reading")
    if not isinstance(result, dict):
        raise ValueError(f"task_id already exists for a different task: {task_id}")
    if result.get("request_sha256") != request_sha256:
        raise ValueError(f"task_id already records a different Zotero reading request: {task_id}")
    decision_id = result.get("decision_id")
    decision = store.latest_record(decision_id, "Decision") if isinstance(decision_id, str) else None
    return {
        "task_id": task_id,
        "decision_id": decision_id,
        "decision": decision,
        "task_packet": copy.deepcopy(packet),
        "replayed": True,
        "query_performed": False,
        "transaction": None,
        "capture_summary": copy.deepcopy(packet.get("input", {}).get("source_observation")),
    }


def record_zotero_reading(
    project_root: str | Path,
    *,
    task_id: str,
    question: str,
    capture: dict,
    findings: list | None = None,
    task_context: str = "production",
) -> dict[str, Any]:
    """Store a frozen Zotero capture and optional page-bounded interpretations.

    Capture data is treated as a caller-supplied historical observation. This
    function never contacts Zotero or treats the capture as verified support.
    """
    selected_root = Path(project_root).expanduser()
    task_id = _id(task_id, "task_id")
    ids = _task_ids(task_id)
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be a non-empty string")
    question = question.strip()
    if task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")
    frozen_capture = _validated_capture(capture, task_context)
    recorded_findings = _validated_findings(findings, frozen_capture)

    try:
        config = load_config(selected_root)
    except Exception as exc:
        raise ValueError(f"research records are not enabled for this project: {exc}") from exc
    root = selected_root.resolve()
    store = ResearchStore(root)
    request_value = {
        "task_id": task_id,
        "question": question,
        "capture": frozen_capture,
        "findings": recorded_findings,
        "task_context": task_context,
    }
    request_sha256 = _sha256_bytes(_canonical_bytes(request_value))
    operation_id = "zotero-reading." + hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]

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
            "input": {"question": question},
        }
        pack = build_research_workflow_pack(config, request, {})
        pages = frozen_capture["pages"]
        read_pages = [page for page in pages if page["status"] == "read"]
        failed_pages = [page for page in pages if page["status"] == "unavailable"]
        all_pages_read = bool(pages) and len(read_pages) == len(pages)
        metadata_read = frozen_capture["metadata_status"] == "read"
        if not read_pages:
            reading_status = "METADATA_ONLY" if metadata_read else "NO_READABLE_CONTENT"
            judgment_status = "INSUFFICIENT"
        elif all_pages_read and metadata_read and not recorded_findings:
            reading_status = "READ_WITHOUT_FINDINGS"
            judgment_status = "PROVISIONAL_WITH_GAPS"
        elif all_pages_read and metadata_read:
            reading_status = "READ_WITH_FINDINGS"
            judgment_status = "PROVISIONAL_WITH_GAPS"
        else:
            reading_status = "PARTIAL_READ"
            judgment_status = "PROVISIONAL_WITH_GAPS"

        gaps: list[str] = []
        if frozen_capture["metadata_status"] == "unavailable":
            gaps.append("metadata unavailable in supplied capture")
        if failed_pages:
            gaps.append(f"{len(failed_pages)} captured page range(s) unavailable")
        if not read_pages:
            gaps.append("capture contains no successfully read page range")
        gaps.extend(str(item.get("code", "capture_diagnostic")) for item in frozen_capture.get("diagnostics", []))
        gaps.extend([
            "capture is caller-supplied historical observation; source was not revalidated",
            "findings are Agent interpretations and do not establish evidence support",
            "scientific and numeric conclusions remain NOT_VERIFIED",
        ])

        snapshot = {
            "schema_version": 1,
            "kind": "zotero_reading_record",
            "request": request_value,
            "provenance": {
                "capture_supplied_by_caller": True,
                "source_revalidated": False,
                "query_performed": False,
                "source_captured_at": frozen_capture["captured_at"],
                "uncertain_version_fields": [
                    field for field, version in [
                        ("item.version", frozen_capture["item"]["version"]),
                        *((f"pages[{index}].attachment_version", page["attachment_version"])
                          for index, page in enumerate(pages)),
                    ] if version in {None, 0}
                ],
            },
        }
        snapshot_hash = _sha256_bytes(_canonical_bytes(snapshot))
        source_refs = [f"task:{task_id}", f"zotero-instance:{frozen_capture['instance_id']}"]
        locator = {
            "path": f"record:{ids['asset']}#payload",
            "path_kind": "record_embedded",
            "record_id": ids["asset"],
            "field": "payload",
            "citation": {"instance_id": frozen_capture["instance_id"],
                         "library_id": frozen_capture["library_id"],
                         "item_key": frozen_capture["item"]["key"],
                         "item_version": frozen_capture["item"]["version"],
                         "captured_at": frozen_capture["captured_at"],
                         "page_ranges": [{key: page[key] for key in (
                             "attachment_key", "attachment_version", "start_page", "end_page", "status")}
                             for page in pages]},
            "caller_label": f"zotero-reading:{task_id}",
            "embedded_payload": "payload",
        }
        question_record = _record(
            "ResearchQuestion", ids["question"], store.project_id, source_refs,
            statement=question, status="active",
        )
        claim_record = _record(
            "Claim", ids["claim"], store.project_id, source_refs,
            statement=f"Reading observation for Zotero item {frozen_capture['item']['key']}.",
            status="proposed",
        )
        route = _record(
            "Route", ids["route"], store.project_id, source_refs,
            status="completed", route_id=ids["route"], question_id=ids["question"],
            research_question_id=ids["question"], hypothesis_id=None,
            claim_id=ids["claim"], task_id=task_id, parent_route_id=None,
            supersedes_route_id=None, workflow_id=WORKFLOW_ID,
            method_id="mining_research_kernel.method.research.evidence_review",
            inputs=[{"question": question}],
            expected_evidence=["bounded caller-supplied Zotero reading capture"],
            assigned_role="host", budget=1, runs_used=0, stop_conditions=[],
            verification_gates=[], outputs=[ids["evidence"]], reservations=[],
            write_set=["research/records"],
        )
        asset = _record(
            "Asset", ids["asset"], store.project_id, source_refs,
            asset_kind="zotero_reading_capture", locator=locator,
            content_sha256=snapshot_hash, authority="derived", status="observed",
            payload=snapshot,
        )
        evidence = _record(
            "Evidence", ids["evidence"], store.project_id, source_refs,
            evidence_kind="zotero_reading_observation", asset_ref=ids["asset"],
            locator=locator, status="observed",
        )
        summary = {
            "instance_id": frozen_capture["instance_id"],
            "library_id": frozen_capture["library_id"],
            "item_key": frozen_capture["item"]["key"],
            "item_version": frozen_capture["item"]["version"],
            "captured_at": frozen_capture["captured_at"],
            "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "metadata_status": frozen_capture["metadata_status"],
            "page_range_count": len(pages),
            "read_page_range_count": len(read_pages),
            "unavailable_page_range_count": len(failed_pages),
            "finding_count": len(recorded_findings),
            "reading_status": reading_status,
            "source_revalidated": False,
            "query_performed": False,
            "scientific_numeric_status": "NOT_VERIFIED",
            "snapshot_sha256": snapshot_hash,
        }
        summary_text = (
            f"Zotero reading capture recorded for item {frozen_capture['item']['key']}: "
            f"{reading_status}; {len(read_pages)}/{len(pages)} page ranges read; "
            "scientific and numeric conclusions NOT_VERIFIED."
        )
        assessment = {"scope": "zotero_reading_capture_only", "capture_summary": summary,
                      "findings": recorded_findings, "snapshot_sha256": snapshot_hash}
        judgment = {
            "status": judgment_status,
            "summary": summary_text,
            "gaps": gaps,
            "next_action": {"action": "Review the recorded capture and its limits",
                            "executable": False, "requires_user_choice": True},
        }
        decision_id = "decision.zotero." + hashlib.sha256(
            (task_id + "|" + request_sha256).encode("utf-8")).hexdigest()[:24]
        decision = _record(
            "Decision", decision_id, store.project_id, source_refs,
            status=judgment_status.lower(), statement=summary_text,
            scope={"project_id": store.project_id, "task_id": task_id,
                   "route_id": ids["route"], "kind": assessment["scope"]},
            assessment=assessment, judgment=judgment,
        )
        packet = TaskEngine(config, pack).start(request)
        packet.update({
            "state": "completed",
            "asset_refs": [ids["asset"]],
            "evidence_refs": [ids["evidence"]],
            "citation_refs": [ids["evidence"]],
            "review_status": "recorded",
            "review_record_ref": decision_id,
            "research_judgment_status": judgment_status,
            "completion_scope": "zotero_reading_capture_recorded",
            "input": {"question": question, "source_observation": summary},
            "material_reads": [{
                "asset_id": ids["asset"], "evidence_refs": [ids["evidence"]],
                "locator": locator, "registration_status": "caller_supplied",
                "locator_status": "embedded_snapshot",
                "content_status": "snapshot_hash_verified",
                "reading_status": "READ_WITH_LIMITS" if read_pages else "READ_INSUFFICIENT",
                "verification_status": "NOT_VERIFIED",
                "asset_kind": "zotero_reading_capture", "authority": "derived",
                "asset_status": "observed", "content_sha256": snapshot_hash,
            }],
            "material_gaps": [{"asset_id": ids["asset"], "reason": gap,
                                "next_action": "review the historical capture and obtain a new observation if needed"}
                               for gap in gaps],
            "next_action": {"action_id": None, "executable": False, "input_refs": [],
                            "expected_outputs": [], "preconditions": [],
                            "reason": "zotero_reading_capture_recorded",
                            "resume_condition": "start a scoped follow-up task using the recorded Asset or Evidence"},
        })
        packet.setdefault("history", []).append({
            "event": "zotero_reading_capture_recorded", "from": "ready", "to": "completed",
            "decision_id": decision_id, "reading_status": reading_status,
        })
        task_record = _record(
            "TaskState", task_id, store.project_id, source_refs,
            task_id=task_id, state="completed", packet=packet,
            operation_results={"zotero_reading": {
                "status": "recorded", "request_sha256": request_sha256,
                "decision_id": decision_id, "asset_id": ids["asset"],
                "evidence_id": ids["evidence"],
            }},
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
            "task_id": task_id,
            "decision_id": decision_id,
            "task_packet": packet,
            "decision": decision,
            "transaction": transaction,
            "replayed": False,
            "query_performed": False,
            "capture_summary": summary,
        }
    finally:
        writer.__exit__(None, None, None)


__all__ = ["record_zotero_reading"]
