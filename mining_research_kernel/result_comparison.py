"""Persistent observations and bounded arithmetic comparisons of exported CSVs."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.result_csv import difference, read_result_csv
from mining_research_kernel.r2_workflow import (
    _edge_id, _id, _record, _relationship, _sha256_bytes, _task_ids,
)
from mining_research_kernel.on_demand import _decision_bound_to_task_state
from research_project import load_config
from mining_research_kernel.task_engine import TaskEngine
from workflows.research import build_research_workflow_pack

_PRODUCER = {"role": "host", "model": "result_comparison"}
_DEFAULT_ACTION = "User chooses any further analysis."


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _base(task_id: str, task_packet: dict[str, Any], replayed: bool, **fields: Any) -> dict[str, Any]:
    return {"task_packet": copy.deepcopy(task_packet), "replayed": replayed,
            "run_created": False, "verification_created": False, **fields}


def _state(store: ResearchStore, task_id: str) -> dict[str, Any] | None:
    return store.latest_record(task_id, "TaskState")


def _operation(state: Mapping[str, Any], mode: str) -> dict[str, Any] | None:
    results = state.get("operation_results", {})
    value = results.get(mode) if isinstance(results, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else None


def _metadata(value: Any) -> tuple[dict[str, Any], list[str]]:
    if not isinstance(value, dict):
        raise ValueError("metadata must be an object")
    allowed = {"case_id", "quantity", "unit", "column_meanings", "point_basis", "conditions", "origin"}
    unknown = set(value) - allowed
    if unknown:
        raise ValueError("unknown metadata keys: " + ", ".join(sorted(str(key) for key in unknown)))
    case_id = value.get("case_id")
    if not isinstance(case_id, str) or not case_id.strip() or len(case_id) > 200:
        raise ValueError("metadata.case_id must be a non-empty bounded string")
    normalized: dict[str, Any] = {"case_id": case_id.strip()}
    gaps: list[str] = []
    for key in ("quantity", "unit", "point_basis"):
        item = value.get(key)
        if item is not None and (not isinstance(item, str) or len(item) > 200):
            raise ValueError(f"metadata.{key} must be a bounded string or null")
        normalized[key] = item.strip() if isinstance(item, str) and item.strip() else None
        if key in {"quantity", "unit"} and normalized[key] is None:
            gaps.append(f"metadata_{key}_unknown")
    meanings = value.get("column_meanings", {})
    if meanings is None:
        meanings = {}
    if not isinstance(meanings, dict) or set(meanings) - {"point_id", "value"}:
        raise ValueError("metadata.column_meanings must contain only point_id/value string-or-null entries")
    normalized["column_meanings"] = {}
    for key in ("point_id", "value"):
        item = meanings.get(key)
        if item is not None and (not isinstance(item, str) or len(item) > 200):
            raise ValueError(f"metadata.column_meanings.{key} must be a bounded string or null")
        normalized["column_meanings"][key] = item.strip() if isinstance(item, str) and item.strip() else None
        if normalized["column_meanings"][key] is None:
            gaps.append(f"column_meaning_{key}_unknown")
    conditions = value.get("conditions", {})
    if conditions is None:
        conditions = {}
    if not isinstance(conditions, dict) or len(conditions) > 50:
        raise ValueError("metadata.conditions must be an object with at most 50 entries")
    normalized_conditions = {}
    for key, item in conditions.items():
        if not isinstance(key, str) or not key.strip() or len(key) > 100:
            raise ValueError("condition keys must be bounded non-empty strings")
        if item is not None and (not isinstance(item, str) or len(item) > 500):
            raise ValueError("condition values must be bounded strings or null")
        clean_key = key.strip()
        if clean_key in normalized_conditions:
            raise ValueError("condition keys collide after whitespace normalization")
        normalized_conditions[clean_key] = item.strip() if isinstance(item, str) and item.strip() else None
    normalized["conditions"] = normalized_conditions
    if not normalized["point_basis"]:
        gaps.append("point_basis_unknown")
    if not normalized_conditions:
        gaps.append("conditions_unknown")
    for key, item in normalized_conditions.items():
        if item is None:
            gaps.append(f"condition_value_unknown:{key}")
    origin = value.get("origin", "provided_export")
    if not isinstance(origin, str) or origin not in {"provided_export", "synthetic"}:
        raise ValueError("metadata.origin must be provided_export or synthetic")
    normalized["origin"] = origin
    return normalized, gaps


def _locator(root: Path, source: Path) -> tuple[dict[str, Any], str]:
    resolved = source.resolve()
    try:
        relative = resolved.relative_to(root.resolve()).as_posix()
        return {"path": relative, "path_kind": "project_relative"}, relative
    except ValueError:
        label = source.name[:180] or "external.csv"
        path_digest = hashlib.sha256(os.path.normcase(str(resolved)).encode()).hexdigest()
        return {"path": f"caller:{label}", "path_kind": "caller_label", "identity_sha256": path_digest}, label


def _resolve_source(root: Path, source_path: str | os.PathLike[str]) -> Path:
    raw = Path(source_path).expanduser()
    if raw.is_absolute():
        return raw.resolve()
    if ".." in raw.parts:
        raise ValueError("relative csv_path must not contain '..'")
    resolved = (root / raw).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("relative csv_path resolves outside project_root") from exc
    return resolved


def _commit_review_task(root: Path, *, task_id: str, question: str, task_context: str,
                        mode: str, input_data: dict[str, Any], assets: list[dict[str, Any]],
                        evidences: list[dict[str, Any]], assessment: dict[str, Any],
                        operation_result: dict[str, Any], new_records: list[dict[str, Any]] | None = None,
                        expected_revisions: dict[str, int] | None = None) -> dict[str, Any]:
    """Build and commit one fully linked evidence-review snapshot atomically."""
    store = ResearchStore(root)
    ids = _task_ids(task_id)
    source_refs = list(dict.fromkeys([f"task:{task_id}",
        *[f"asset:{a['id']}" for a in assets], *[f"evidence:{e['id']}" for e in evidences]]))
    task_request = {"project_id": store.project_id, "task_id": task_id,
        "workflow_id": "mining_research_kernel.workflow.research",
        "task_type": "mining_research_kernel.task.evidence_review", "maturity": "known_workflow",
        "max_runs": 1, "route_id": ids["route"], "routes": [ids["route"]],
        "allowed_tools": ["evidence.read_only"], "verification_gates": [],
        "task_context": task_context, "question_statement": question,
        "claim_statement": f"Recorded {mode.replace('_', ' ')} observation for existing exported data.",
        "input": {"question": question, "review_mode": mode, **copy.deepcopy(input_data)},
        "asset_refs": [a["id"] for a in assets], "evidence_refs": [e["id"] for e in evidences]}
    config = load_config(root)
    packet = TaskEngine(config, build_research_workflow_pack(config, task_request, {})).start(task_request)
    decision_id = "decision.resultcsv." + hashlib.sha256((task_id + "|" + mode).encode()).hexdigest()[:24]
    judgment = copy.deepcopy(assessment["judgment"])
    packet.update({"state": "completed", "asset_refs": [a["id"] for a in assets],
        "evidence_refs": [e["id"] for e in evidences], "citation_refs": [e["id"] for e in evidences],
        "review_status": "recorded", "review_record_ref": decision_id,
        "research_judgment_status": judgment["status"], "completion_scope": mode,
        "material_reads": [{"asset_id": asset["id"], "evidence_refs": [ev["id"] for ev in evidences if ev.get("asset_ref") == asset["id"]],
            "locator": copy.deepcopy(asset["locator"]), "registration_status": "registered",
            "locator_status": "embedded_snapshot", "content_status": "snapshot_hash_verified",
            "reading_status": "READ_WITH_LIMITS", "verification_status": "NOT_VERIFIED",
            "asset_kind": asset["asset_kind"], "authority": asset["authority"],
            "asset_status": asset["status"], "content_sha256": asset["content_sha256"]}
            for asset in assets],
        "material_gaps": copy.deepcopy(assessment.get("material_gaps", [])),
        "next_action": {"action_id": None, "executable": False, "input_refs": [],
            "expected_outputs": [], "preconditions": [], "reason": mode + "_recorded",
            "resume_condition": "start a new task with a new task_id for a new capture or comparison"}})
    packet.setdefault("history", []).append({"event": mode + "_recorded", "from": "ready",
        "to": "completed", "decision_id": decision_id})
    question_record = _record("ResearchQuestion", ids["question"], store.project_id, source_refs,
        statement=question, status="active")
    claim_record = _record("Claim", ids["claim"], store.project_id, source_refs,
        statement=task_request["claim_statement"], status="proposed")
    route = _record("Route", ids["route"], store.project_id, source_refs,
        status="completed", route_id=ids["route"], question_id=ids["question"],
        research_question_id=ids["question"], hypothesis_id=None, claim_id=ids["claim"],
        task_id=task_id, parent_route_id=None, supersedes_route_id=None,
        workflow_id=task_request["workflow_id"], method_id="mining_research_kernel.method.research.evidence_review",
        inputs=[input_data], expected_evidence=["captured result CSV evidence"], assigned_role="host",
        budget=1, runs_used=0, stop_conditions=[], verification_gates=[],
        outputs=[e["id"] for e in evidences], reservations=[], write_set=["research/records"])
    decision = _record("Decision", decision_id, store.project_id,
        list(dict.fromkeys([*source_refs, f"decision:{decision_id}"])),
        status=judgment["status"].lower(), statement=judgment["summary"],
        scope={"project_id": store.project_id, "task_id": task_id, "route_id": ids["route"], "kind": mode},
        assessment=copy.deepcopy(assessment), judgment=judgment,
        material_read_count=len(assets))
    results = {mode: copy.deepcopy(operation_result)}
    task_state = _record("TaskState", task_id, store.project_id,
        list(dict.fromkeys([*source_refs, f"decision:{decision_id}"])), task_id=task_id,
        state="completed", packet=packet, operation_results=results)
    records = [*(new_records or []), question_record, claim_record, route, decision, task_state]
    relationships = [
        _relationship(_edge_id(task_id, "route-addresses"), "route_addresses_question", route, question_record, store.project_id, source_refs),
        _relationship(_edge_id(task_id, "route-claim"), "route_targets_claim", route, claim_record, store.project_id, source_refs),
    ]
    record_by_id = {r["id"]: r for r in [*assets, *evidences, *records]}
    for index, asset in enumerate(assets):
        relationships.append(_relationship(_edge_id(task_id, f"route-asset-{index}"), "route_reads_asset", route, asset, store.project_id, source_refs))
    for index, evidence in enumerate(evidences):
        relationships.append(_relationship(_edge_id(task_id, f"route-evidence-{index}"), "route_reads_evidence", route, evidence, store.project_id, source_refs))
        relationships.append(_relationship(_edge_id(task_id, f"decision-evidence-{index}"), "decision_records_evidence", decision, evidence, store.project_id, source_refs))
        asset = record_by_id[evidence["asset_ref"]]
        if asset.get("revision") == 1 and asset.get("id") in {r["id"] for r in (new_records or [])}:
            relationships.append(_relationship(_edge_id(task_id, f"evidence-asset-{index}"), "evidence_derived_from_asset", evidence, asset, store.project_id, source_refs))
    relationships.append(_relationship(_edge_id(task_id, "decision-route"), "decision_closes_route", decision, route, store.project_id, source_refs))
    store.commit("result-csv." + hashlib.sha256(task_id.encode()).hexdigest()[:32], _PRODUCER,
        records, relationships, expected_revisions=expected_revisions or {})
    return {"task_packet": packet, "decision_id": decision_id}


def _find_capture(store: ResearchStore, asset_ref: str) -> tuple[dict[str, Any], dict[str, Any]]:
    asset = store.latest_record(asset_ref, "Asset")
    evidence_id = asset.get("payload", {}).get("evidence_id") if asset else None
    evidence = store.latest_record(evidence_id, "Evidence") if isinstance(evidence_id, str) else None
    if asset is None or evidence is None or asset.get("asset_kind") != "result_csv_capture":
        raise ValueError(f"unknown result CSV capture asset: {asset_ref}")
    payload = asset.get("payload")
    if not isinstance(payload, dict) or payload.get("kind") != "result_csv_observation":
        raise ValueError(f"invalid result CSV capture payload: {asset_ref}")
    snapshot_hash = _sha256_bytes(_canonical(payload))
    relation_bound = any(
        relation.get("relation") == "evidence_derived_from_asset"
        and relation.get("from_id") == evidence.get("id")
        and relation.get("from_revision") == evidence.get("revision")
        and relation.get("to_id") == asset.get("id")
        and relation.get("to_revision") == asset.get("revision")
        for transaction in store.list_transactions()
        for relation in transaction.get("relationships", [])
    )
    if (snapshot_hash != asset.get("content_sha256") or evidence.get("asset_ref") != asset_ref
            or not relation_bound):
        raise ValueError(f"capture asset/evidence hash or binding mismatch: {asset_ref}")
    return asset, evidence


def import_result_csv(project_root: str | os.PathLike[str], *, task_id: str, question: str,
                      csv_path: str | os.PathLike[str], metadata: dict[str, Any],
                      encoding: str = "utf-8-sig", task_context: str = "production") -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    task_id = _id(task_id, "task_id")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("question must be a non-empty string of at most 2000 characters")
    if not isinstance(task_context, str) or task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")
    if not isinstance(csv_path, (str, os.PathLike)) or not str(csv_path).strip() or len(str(csv_path)) > 4096:
        raise ValueError("csv_path must be a non-empty bounded string or Path")
    if not isinstance(encoding, str) or not encoding.strip() or len(encoding) > 100:
        raise ValueError("encoding must be a non-empty bounded string")
    meta, metadata_gaps = _metadata(metadata)
    if (task_context == "synthetic") != (meta["origin"] == "synthetic"):
        raise ValueError("synthetic metadata and task_context must be used together")
    mode = "result_csv_import"
    store = ResearchStore(root)
    request_core = {"task_id": task_id, "question": question.strip(), "metadata": meta,
                    "encoding": encoding, "task_context": task_context}
    # Compare the path identity without opening the source on replay.
    source_path = _resolve_source(root, csv_path)
    locator, source_label = _locator(root, source_path)
    request_hash = _sha256_bytes(_canonical({**request_core, "locator": locator}))
    prior = _state(store, task_id)
    if prior is not None:
        recorded = _operation(prior, mode)
        if not recorded or recorded.get("request_sha256") != request_hash:
            raise ValueError(f"task_id already exists for a different request: {task_id}")
        capture = copy.deepcopy(recorded["capture"])
        return _base(task_id, prior["packet"], True, capture=capture,
                     asset_refs=copy.deepcopy(recorded["asset_refs"]),
                     evidence_refs=copy.deepcopy(recorded["evidence_refs"]),
                     capture_asset_ref=recorded["capture_asset_ref"], source_label=source_label)
    parsed = read_result_csv(source_path, encoding=encoding)
    if meta["origin"] == "synthetic" and task_context != "synthetic":
        raise ValueError("synthetic data cannot be imported as production")
    raw_hash = parsed["sha256"]
    # Pin the original bytes through a derived, immutable row snapshot. No source bytes are copied.
    payload = {"schema_version": 1, "kind": "result_csv_observation", "capture_task_id": task_id,
               "source_sha256": raw_hash,
               "source_locator": locator, "source_label": source_label, "format": parsed["format"],
               "encoding": parsed["encoding"], "columns": parsed["columns"], "row_count": parsed["row_count"],
               "rows": parsed["rows"], "diagnostics": parsed["diagnostics"], "limits": parsed["limits"],
               "metadata": meta, "metadata_gaps": metadata_gaps,
               "conditions_are_caller_assertions": True}
    snapshot_hash = _sha256_bytes(_canonical(payload))
    _task_ids(task_id)
    suffix = hashlib.sha256(task_id.encode()).hexdigest()[:24]
    asset_id, evidence_id = f"capture.{suffix}", f"evidence.capture.{suffix}"
    payload["evidence_id"] = evidence_id
    snapshot_hash = _sha256_bytes(_canonical(payload))
    refs = [f"task:{task_id}", f"asset:{asset_id}", f"evidence:{evidence_id}"]
    asset_locator = {"path": f"record:{asset_id}#payload", "path_kind": "record_embedded",
                     "record_id": asset_id, "field": "payload", "embedded_payload": "payload",
                     "source_locator": locator, "caller_label": source_label}
    asset = _record("Asset", asset_id, store.project_id, refs, asset_kind="result_csv_capture",
                    locator=asset_locator, content_sha256=snapshot_hash, authority="derived",
                    status="observed", payload=payload)
    evidence = _record("Evidence", evidence_id, store.project_id, refs,
                       evidence_kind="result_csv_observation", asset_ref=asset_id,
                       locator=asset_locator, status="observed")
    quality_gaps = [f"csv_{item['code']}" for item in parsed["diagnostics"]]
    valid_rows = [row for row in parsed["rows"] if row["status"] == "VALID"]
    capture_status = "PROVISIONAL_WITH_GAPS" if valid_rows else "INSUFFICIENT"
    capture_gaps = list(dict.fromkeys(metadata_gaps + quality_gaps + ["solver_not_run", "engineering_causality_not_verified"]))
    assessment = {"scope": "material_reading_and_evidence_synthesis_only",
                  "material_reads": [{"asset_id": asset_id, "evidence_refs": [evidence_id],
                    "observed_sha256": snapshot_hash, "reading_status": "READ_WITH_LIMITS",
                    "verification_status": "NOT_VERIFIED", "locator": asset_locator,
                    "summary": "Read-only capture of an existing exported CSV; solver provenance and engineering meaning are unverified.",
                    "numeric_check_status": "PARTIAL", "scientific_validation_status": "NOT_VERIFIED",
                    "gaps": capture_gaps}],
                  "material_gaps": [{"asset_id": asset_id, "reason": "export provenance and engineering interpretation unverified",
                    "next_action": "User chooses any further analysis."}],
                  "judgment": {"status": capture_status, "summary": "CSV observations captured; no solver was run and no engineering causality was verified.",
                    "gaps": capture_gaps,
                    "next_action": {"action": _DEFAULT_ACTION, "executable": False, "requires_user_choice": True}}}
    capture = {"source_sha256": raw_hash, "snapshot_sha256": snapshot_hash, "source_locator": locator,
               "source_label": source_label, "metadata": meta, "metadata_gaps": metadata_gaps,
               "columns": parsed["columns"], "row_count": parsed["row_count"], "rows": parsed["rows"],
               "diagnostics": parsed["diagnostics"], "quality_gaps": quality_gaps, "limits": parsed["limits"],
               "judgment": copy.deepcopy(assessment["judgment"])}
    operation_result = {"request_sha256": request_hash, "capture": capture,
                     "asset_refs": [asset_id], "capture_asset_ref": asset_id,
                     "evidence_refs": [evidence_id]}
    _commit_review_task(root, task_id=task_id, question=question.strip(), task_context=task_context,
        mode=mode, input_data={"metadata": meta, "source_sha256": raw_hash}, assets=[asset],
        evidences=[evidence], assessment=assessment, operation_result=operation_result,
        new_records=[asset, evidence])
    final_state = _state(store, task_id)
    return _base(task_id, final_state["packet"], False, capture=capture,
                 asset_refs=[asset_id], capture_asset_ref=asset_id,
                 evidence_refs=[evidence_id], source_label=source_label)


def compare_results(project_root: str | os.PathLike[str], *, task_id: str, question: str,
                    baseline_asset_ref: str, candidate_asset_ref: str, point_ids: list[str],
                    comparability_note: str = "", related_task_ids: list[str] | None = None,
                    next_action: str = _DEFAULT_ACTION, task_context: str = "production") -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    task_id = _id(task_id, "task_id")
    if not isinstance(question, str) or not question.strip() or len(question) > 2000:
        raise ValueError("question must be a non-empty string of at most 2000 characters")
    if not isinstance(task_context, str) or task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")
    if not isinstance(point_ids, list) or not 1 <= len(point_ids) <= 100:
        raise ValueError("point_ids must contain 1 to 100 selected points")
    if any(not isinstance(point, str) or not point.strip() or len(point) > 200 for point in point_ids):
        raise ValueError("point_ids must be bounded non-empty strings")
    if len(set(point_ids)) != len(point_ids):
        raise ValueError("point_ids must be unique")
    if not isinstance(related_task_ids, (list, type(None))):
        raise ValueError("related_task_ids must be a list or null")
    related_task_ids = related_task_ids or []
    if any(not isinstance(item, str) or not item.strip() for item in related_task_ids):
        raise ValueError("related_task_ids must contain non-empty task ID strings")
    related_task_ids = [_id(item, "related_task_id") for item in related_task_ids]
    if len(set(related_task_ids)) != len(related_task_ids) or len(related_task_ids) > 20:
        raise ValueError("related_task_ids must be unique and at most 20")
    if not isinstance(comparability_note, str) or len(comparability_note) > 2000:
        raise ValueError("comparability_note must be a string of at most 2000 characters")
    if not isinstance(next_action, str) or not next_action.strip() or len(next_action) > 1000:
        raise ValueError("next_action must be a non-empty bounded string")
    if baseline_asset_ref == candidate_asset_ref:
        raise ValueError("baseline and candidate must reference distinct capture Assets")
    store = ResearchStore(root)
    request = {"task_id": task_id, "question": question.strip(),
        "baseline_asset_ref": baseline_asset_ref, "candidate_asset_ref": candidate_asset_ref,
        "point_ids": point_ids, "comparability_note": comparability_note,
        "related_task_ids": related_task_ids, "next_action": next_action,
        "task_context": task_context}
    request_hash = _sha256_bytes(_canonical(request))
    prior = _state(store, task_id)
    if prior is not None:
        recorded = _operation(prior, "result_csv_comparison")
        if not recorded or recorded.get("request_sha256") != request_hash:
            raise ValueError(f"task_id already exists for a different comparison: {task_id}")
        return _base(task_id, prior["packet"], True, **copy.deepcopy(recorded["result"]))

    baseline, baseline_evidence = _find_capture(store, baseline_asset_ref)
    candidate, candidate_evidence = _find_capture(store, candidate_asset_ref)
    for asset in (baseline, candidate):
        origin = asset["payload"].get("metadata", {}).get("origin")
        if (origin == "synthetic") != (task_context == "synthetic"):
            raise ValueError("synthetic captures cannot enter a production comparison")

    related_snapshots = []
    pins: dict[str, int] = {baseline["id"]: baseline["revision"],
                           candidate["id"]: candidate["revision"],
                           baseline_evidence["id"]: baseline_evidence["revision"],
                           candidate_evidence["id"]: candidate_evidence["revision"]}
    for related_id in related_task_ids:
        related = store.latest_record(_id(related_id, "related_task_id"), "TaskState")
        if related is None:
            raise ValueError(f"unknown related task: {related_id}")
        related_context = related.get("packet", {}).get("task_context", "production")
        if task_context == "production" and related_context == "synthetic":
            raise ValueError("synthetic related tasks cannot enter a production comparison")
        decision = _decision_bound_to_task_state(store, related)
        if decision is None:
            raise ValueError(f"related task has no Decision bound to its current revision: {related_id}")
        pins[related["id"]] = related["revision"]
        pins[decision["id"]] = decision["revision"]
        packet_input = related.get("packet", {}).get("input", {})
        script_review = packet_input.get("script_review", {}) if isinstance(packet_input, Mapping) else {}
        script_snapshot = script_review.get("script_snapshot", {}) if isinstance(script_review, Mapping) else {}
        document_sources = script_review.get("documentation_sources", []) if isinstance(script_review, Mapping) else []
        source_context = {}
        if isinstance(script_snapshot, Mapping):
            source_context["script"] = {key: copy.deepcopy(script_snapshot.get(key)) for key in
                ("source", "start_line", "end_line", "script_sha256", "encoding") if key in script_snapshot}
        if isinstance(document_sources, list):
            source_context["documentation"] = []
            for doc in document_sources:
                citation = doc.get("citation", {}) if isinstance(doc, Mapping) else {}
                if isinstance(citation, Mapping):
                    source_context["documentation"].append({key: copy.deepcopy(citation.get(key)) for key in
                        ("source_id", "product", "page", "anchor", "document_build", "sha256_body", "trust_class") if key in citation})
        assessment = decision.get("assessment", {})
        doc_result = assessment.get("documentation_result", {}) if isinstance(assessment, Mapping) else {}
        citation = doc_result.get("citation", {}) if isinstance(doc_result, Mapping) else {}
        if isinstance(citation, Mapping) and citation:
            source_context["documentation"] = [{key: copy.deepcopy(citation.get(key)) for key in
                ("source_id", "product", "page", "anchor", "document_build", "sha256_body", "trust_class") if key in citation}]
        summary = {"task_id": related["id"], "task_revision": related["revision"],
                   "task_context": related_context,
                   "task_type": related.get("packet", {}).get("task_type"),
                   "decision_id": decision["id"], "decision_revision": decision["revision"],
                   "judgment": copy.deepcopy(decision.get("judgment", {})),
                   "source_context": source_context}
        related_snapshots.append(summary)
    bpayload, cpayload = baseline["payload"], candidate["payload"]
    bmeta, cmeta = bpayload["metadata"], cpayload["metadata"]
    gaps: list[str] = []
    metadata_compatible = True
    for key in ("quantity", "unit"):
        if not bmeta.get(key) or not cmeta.get(key):
            metadata_compatible = False
            gaps.append(f"{key}_unknown")
        elif bmeta[key] != cmeta[key]:
            metadata_compatible = False
            gaps.append(f"{key}_mismatch")
    if bmeta.get("point_basis") != cmeta.get("point_basis") or not bmeta.get("point_basis") or not cmeta.get("point_basis"):
        gaps.append("point_basis_unknown_or_different")
    condition_keys = set(bmeta.get("conditions", {})) | set(cmeta.get("conditions", {}))
    condition_differences = [key for key in sorted(condition_keys)
        if bmeta.get("conditions", {}).get(key) != cmeta.get("conditions", {}).get(key)]
    if condition_differences:
        gaps.extend("condition_unknown_or_different:" + key for key in condition_differences)
    gaps.extend(f"condition_value_unknown:{key}" for key in condition_keys
        if bmeta.get("conditions", {}).get(key) is None or cmeta.get("conditions", {}).get(key) is None)
    for capture in (bpayload, cpayload):
        gaps.extend(capture.get("metadata_gaps", []))
        gaps.extend(f"csv_{diagnostic.get('code', 'diagnostic')}" for diagnostic in capture.get("diagnostics", []))
    if bmeta.get("case_id") == cmeta.get("case_id"):
        gaps.append("same_case_id")
    brows = {}
    crows = {}
    for row in bpayload.get("rows", []):
        brows.setdefault(row["point_id"], []).append(row)
    for row in cpayload.get("rows", []):
        crows.setdefault(row["point_id"], []).append(row)
    points = []
    for point_id in point_ids:
        br = brows.get(point_id, [])
        cr = crows.get(point_id, [])
        item: dict[str, Any] = {"point_id": point_id,
            "baseline": {"source_sha256": bpayload["source_sha256"], "rows": copy.deepcopy(br)},
            "candidate": {"source_sha256": cpayload["source_sha256"], "rows": copy.deepcopy(cr)},
            "delta": None}
        if not br or not cr:
            item.update(status="INSUFFICIENT", reason="point_missing_from_baseline" if not br else "point_missing_from_candidate")
        elif len(br) != 1 or len(cr) != 1 or br[0]["status"] == "DUPLICATE" or cr[0]["status"] == "DUPLICATE":
            item.update(status="INSUFFICIENT", reason="duplicate_point_id")
        elif br[0]["status"] != "VALID" or cr[0]["status"] != "VALID":
            item.update(status="INSUFFICIENT", reason="baseline_" + br[0]["status"].lower() if br[0]["status"] != "VALID" else "candidate_" + cr[0]["status"].lower())
        elif not metadata_compatible:
            item.update(status="INSUFFICIENT", reason="quantity_or_unit_not_known_and_identical")
        else:
            item.update(status="ARITHMETIC_DELTA_ONLY", baseline_value=br[0]["value_text"],
                        candidate_value=cr[0]["value_text"],
                        delta=difference(cr[0]["value_text"], br[0]["value_text"]))
        points.append(item)
    computable = sum(1 for item in points if item["delta"] is not None)
    result_status = "INSUFFICIENT" if not computable else "PROVISIONAL_WITH_GAPS"
    judgment = {"status": result_status,
        "summary": f"Computed candidate-minus-baseline arithmetic deltas for {computable} selected points; engineering comparability remains unverified.",
        "gaps": list(dict.fromkeys(gaps + ([] if computable == len(points) else ["one_or_more_selected_points_insufficient"]) + ["solver_not_run", "engineering_causality_not_verified"])),
        "next_action": {"action": next_action, "executable": False, "requires_user_choice": True}}
    comparison = {"status": result_status, "baseline_asset_ref": baseline_asset_ref,
        "candidate_asset_ref": candidate_asset_ref, "point_ids": list(point_ids), "points": points,
        "comparability_note": comparability_note,
        "metadata": {"baseline": copy.deepcopy(bmeta), "candidate": copy.deepcopy(cmeta)},
        "conditions_are_caller_assertions": True,
        "statement": "Existing exported data only; no solver was run and no engineering causality or physical comparability is verified."}
    related_context = {"snapshots": related_snapshots,
        "meaning": "User-associated historical context only; it does not establish that a script produced either CSV."}
    sources = [{"asset_ref": baseline["id"], "evidence_ref": baseline_evidence["id"],
                "asset_revision": baseline["revision"], "evidence_revision": baseline_evidence["revision"],
                "source_sha256": bpayload["source_sha256"], "snapshot_sha256": baseline["content_sha256"],
                "source_locator": copy.deepcopy(bpayload["source_locator"]), "source_label": bpayload["source_label"],
                "metadata": copy.deepcopy(bpayload["metadata"]), "columns": copy.deepcopy(bpayload["columns"]),
                "diagnostics": copy.deepcopy(bpayload["diagnostics"]),
                "citation": {"source_label": bpayload["source_label"], "locator": copy.deepcopy(bpayload["source_locator"]),
                             "metadata": copy.deepcopy(bpayload["metadata"]), "columns": copy.deepcopy(bpayload["columns"])}},
               {"asset_ref": candidate["id"], "evidence_ref": candidate_evidence["id"],
                "asset_revision": candidate["revision"], "evidence_revision": candidate_evidence["revision"],
                "source_sha256": cpayload["source_sha256"], "snapshot_sha256": candidate["content_sha256"],
                "source_locator": copy.deepcopy(cpayload["source_locator"]), "source_label": cpayload["source_label"],
                "metadata": copy.deepcopy(cpayload["metadata"]), "columns": copy.deepcopy(cpayload["columns"]),
                "diagnostics": copy.deepcopy(cpayload["diagnostics"]),
                "citation": {"source_label": cpayload["source_label"], "locator": copy.deepcopy(cpayload["source_locator"]),
                             "metadata": copy.deepcopy(cpayload["metadata"]), "columns": copy.deepcopy(cpayload["columns"])}}]

    assessment = {"scope": "material_reading_and_evidence_synthesis_only", "comparison": comparison,
        "related_context": related_context,
        "material_reads": [{"asset_id": src["asset_ref"], "evidence_refs": [src["evidence_ref"]],
            "observed_sha256": store.latest_record(src["asset_ref"], "Asset")["content_sha256"],
            "reading_status": "READ_WITH_LIMITS",
            "verification_status": "NOT_VERIFIED", "locator": store.latest_record(src["asset_ref"], "Asset")["locator"],
            "summary": "Compared persisted read-only CSV capture snapshot.", "numeric_check_status": "PARTIAL",
            "scientific_validation_status": "NOT_VERIFIED", "gaps": judgment["gaps"]} for src in sources],
        "material_gaps": [{"asset_id": src["asset_ref"], "reason": "engineering meaning and source provenance are unverified",
                           "next_action": next_action} for src in sources], "judgment": judgment}
    full = {"comparison": comparison, "sources": sources, "related_context": related_context,
            "judgment": judgment}
    operation_result = {"request_sha256": request_hash, "result": full}
    _commit_review_task(root, task_id=task_id, question=question.strip(), task_context=task_context,
        mode="result_csv_comparison", input_data={"request_sha256": request_hash,
        "related_task_ids": related_task_ids, "baseline_asset_ref": baseline_asset_ref,
        "candidate_asset_ref": candidate_asset_ref, "point_ids": point_ids},
        assets=[baseline, candidate], evidences=[baseline_evidence, candidate_evidence],
        assessment=assessment, operation_result=operation_result, expected_revisions=pins)
    saved = _state(store, task_id)
    return _base(task_id, saved["packet"], False, **full)


def result_comparison_progress(project_root: str | os.PathLike[str], *, task_id: str,
                               source_paths: dict[str, str] | None = None) -> dict[str, Any]:
    root = Path(project_root).expanduser().resolve()
    store = ResearchStore(root)
    state = _state(store, _id(task_id, "task_id"))
    if state is None:
        raise ValueError(f"unknown task: {task_id}")
    if source_paths is not None and (not isinstance(source_paths, dict) or any(
            not isinstance(k, str) or not isinstance(v, str) or not v.strip() or len(v) > 4096
            for k, v in source_paths.items())):
        raise ValueError("source_paths must map capture asset IDs to paths")
    operation = _operation(state, "result_csv_import")
    if operation:
        captures = [operation["capture"]]
        assets = operation["asset_refs"]
        comparisons = []
        kind = "import"
    else:
        operation = _operation(state, "result_csv_comparison")
        if not operation:
            raise ValueError(f"task has no result CSV import or comparison: {task_id}")
        full = operation["result"]
        captures, assets, comparisons, kind = [], [s["asset_ref"] for s in full["sources"]], [full], "comparison"
    known_assets = set(assets)
    if source_paths is not None and set(source_paths) - known_assets:
        raise ValueError("source_paths contains an unknown capture Asset ID")
    checks = {}
    for asset_id in assets:
        if source_paths is None or asset_id not in source_paths:
            status = "not_checked"
        else:
            try:
                path = _resolve_source(root, source_paths[asset_id])
                if not path.is_file():
                    status = "missing"
                else:
                    with path.open("rb") as stream:
                        raw = stream.read(2 * 1024 * 1024 + 1)
                    if len(raw) > 2 * 1024 * 1024:
                        raise OSError("source exceeds 2 MiB check limit")
                    current = hashlib.sha256(raw).hexdigest()
                    if kind == "import":
                        original_hash = captures[0]["source_sha256"]
                    else:
                        original_hash = next(item["source_sha256"] for item in comparisons[0]["sources"] if item["asset_ref"] == asset_id)
                    status = "unchanged" if current == original_hash else "changed"
            except OSError:
                status = "read_error"
        checks[asset_id] = {"status": status, "snapshot_retained": True}
    import_judgment = copy.deepcopy(captures[0].get("judgment", {})) if captures else None
    return _base(task_id, state["packet"], True, kind=kind, captures=copy.deepcopy(captures),
        comparisons=copy.deepcopy(comparisons), sources=copy.deepcopy(assets), source_checks=checks,
        related_context=copy.deepcopy(comparisons[0].get("related_context", {})) if comparisons else {},
        judgment=copy.deepcopy(comparisons[0].get("judgment", {})) if comparisons else import_judgment)


def render_result_comparison_report(project_root: str | os.PathLike[str], *, task_id: str) -> str:
    def md(value: Any) -> str:
        return str(value).replace("|", "\\|").replace("\r", " ").replace("\n", " ")

    progress = result_comparison_progress(project_root, task_id=task_id)
    lines = [f"# Result CSV {progress['kind']} report", "",
             "Existing exported data only. No solver was run; engineering causality and physical comparability are not verified.", ""]
    if progress["kind"] == "import":
        for capture in progress["captures"]:
            lines.extend([f"## Capture {capture['metadata']['case_id']}", "",
                f"- Original source SHA-256: `{capture['source_sha256']}`",
                f"- Snapshot SHA-256: `{capture['snapshot_sha256']}`",
                f"- Source: `{capture['source_label']}`",
                f"- Metadata: `{json.dumps(capture['metadata'], ensure_ascii=False, sort_keys=True)}`",
                f"- Diagnostics: `{json.dumps(capture['diagnostics'], ensure_ascii=False, sort_keys=True)}`", "",
                "| Point | Value | Status | Lines |", "|---|---|---|---|"])
            for row in capture["rows"]:
                lines.append(f"| {md(row['point_id'])} | {md(row['value_text'])} | {md(row['status'])} | {row['start_line']}-{row['end_line']} |")
            lines.extend(["", f"Gaps: {', '.join(capture.get('judgment', {}).get('gaps', [])) or '(none recorded)'}",
                f"Next action: {capture.get('judgment', {}).get('next_action', {}).get('action', _DEFAULT_ACTION)}", ""])
    else:
        full = progress["comparisons"][0]
        comparison = full["comparison"]
        lines.extend([f"## Comparison: {comparison['status']}", "",
            f"- Comparability note: {comparison['comparability_note'] or '(none)'}",
            f"- Metadata: `{json.dumps(comparison['metadata'], ensure_ascii=False, sort_keys=True)}`", "",
            "### Sources", ""])
        for source in full["sources"]:
            lines.extend([f"- `{source['asset_ref']}` Asset revision {source['asset_revision']}, Evidence revision {source['evidence_revision']}",
                f"  Original SHA-256: `{source['source_sha256']}`; snapshot SHA-256: `{source['snapshot_sha256']}`",
                f"  Citation: `{json.dumps(source['citation'], ensure_ascii=False, sort_keys=True)}`",
                f"  Diagnostics: `{json.dumps(source['diagnostics'], ensure_ascii=False, sort_keys=True)}`"])
        lines.extend(["", "### Selected points", "",
            "| Point | Status | Baseline | Candidate | Candidate − baseline | Baseline lines | Candidate lines |",
            "|---|---|---:|---:|---:|---|---|"])
        for point in comparison["points"]:
            b, c = point["baseline"]["rows"], point["candidate"]["rows"]
            bv = point.get("baseline_value", b[0].get("value_text") if len(b) == 1 else "")
            cv = point.get("candidate_value", c[0].get("value_text") if len(c) == 1 else "")
            bline = f"{b[0]['start_line']}-{b[0]['end_line']}" if len(b) == 1 else ""
            cline = f"{c[0]['start_line']}-{c[0]['end_line']}" if len(c) == 1 else ""
            lines.append(f"| {md(point['point_id'])} | {md(point['status'])} ({md(point.get('reason', 'arithmetic only'))}) | {md(bv)} | {md(cv)} | {md(point.get('delta') or '')} | {bline} | {cline} |")
        gaps = progress["judgment"].get("gaps", [])
        lines.extend(["", f"Gaps: {', '.join(gaps) or '(none recorded)'}", "",
            "### Related historical context", "", progress["related_context"].get("meaning", "")])
        for related in progress["related_context"].get("snapshots", []):
            lines.append(f"- Task `{md(related.get('task_id'))}` revision {related.get('task_revision')} ({md(related.get('task_context', 'unknown'))}); Decision `{md(related.get('decision_id'))}` revision {related.get('decision_revision')}")
            related_judgment = related.get("judgment", {})
            if isinstance(related_judgment, Mapping):
                lines.append(f"  - Judgment: {md(related_judgment.get('status', 'unknown'))}: {md(related_judgment.get('summary', ''))}")
                lines.append(f"  - Judgment gaps: {md(', '.join(related_judgment.get('gaps', [])))}")
            for category, items in related.get("source_context", {}).items():
                if isinstance(items, Mapping):
                    lines.append(f"  - {md(category)}: `{json.dumps(items, ensure_ascii=False, sort_keys=True)}`")
                elif isinstance(items, list):
                    for item in items:
                        lines.append(f"  - {md(category)}: `{json.dumps(item, ensure_ascii=False, sort_keys=True)}`")
        lines.extend(["", f"Next action: {progress['judgment'].get('next_action', {}).get('action', _DEFAULT_ACTION)}", ""])
    return "\n".join(lines)


__all__ = ["import_result_csv", "compare_results", "result_comparison_progress", "render_result_comparison_report"]
