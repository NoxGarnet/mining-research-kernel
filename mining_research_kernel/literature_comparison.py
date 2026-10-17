"""Structured, bounded comparison of explicitly selected paper readings."""
from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import _id, task_record_evidence_review
from mining_research_kernel.source_review import _sources_for_task, start_source_review


DEFAULT_DIMENSIONS = ["materials", "conditions", "methods", "parameters", "results", "applicability"]
_MAX_SOURCES = 20
_MAX_DIMENSIONS = 12
_MAX_TEXT = 2000
_MAX_NEXT = 1000
_MAX_COLLECTION = 120


def start_literature_comparison(project_root, *, task_id: str, question: str, asset_refs: list[str],
                                dimensions=None, task_context="production") -> dict:
    """Start an explicit source-bound paper comparison; documentation Assets are optional."""
    dimensions = DEFAULT_DIMENSIONS if dimensions is None else dimensions
    if (not _bounded_text(question, "question") or not isinstance(dimensions, list)
            or not 1 <= len(dimensions) <= _MAX_DIMENSIONS
            or any(not _bounded_text(item, "dimension", limit=80) for item in dimensions)
            or len(set(dimensions)) != len(dimensions)):
        raise ValueError("question and 1..12 unique bounded dimensions are required")
    started = start_source_review(project_root, task_id=task_id, question=question, asset_refs=asset_refs,
                                  task_context=task_context, review_mode="literature_comparison",
                                  dimensions=dimensions)
    question = started["task_packet"]["input"]["review_question"]
    sources = []
    summary_cells = []
    for source in started["sources"]:
        aid = source["asset_ref"]
        cells = {}
        for dimension in dimensions:
            cells[dimension] = {"status": "not_reported_in_read_scope", "value": None,
                                "interpretation": "Not reported in the currently saved read scope.",
                                "citations": []}
        sources.append({"asset_ref": aid, "dimensions": cells})
        summary_cells.append({"asset_ref": aid, "dimension": dimensions[0]})
    started["comparison_template"] = {
        "schema_version": 1,
        "question": question,
        "summary": "No comparison interpretation has been entered yet.",
        "summary_cells": summary_cells,
        "next": "Suggest a specific next reading or research step for the user to choose.",
        "sources": sources,
        "differences": [],
        "limitations": ["Comparison is limited to the saved reading coverage.",
                        "Scientific and numeric claims have not been semantically verified."],
    }
    return started


def _bounded_text(value: Any, field: str, *, limit: int = _MAX_TEXT) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= limit


def _page_is_covered(capture: Mapping, attachment_key: str, start: int, end: int) -> bool:
    return any(page.get("attachment_key") == attachment_key and page.get("status") == "read"
               and page.get("start_page", 0) <= start
               and page.get("end_page", 0) >= end for page in capture.get("pages", [])
               if isinstance(page, Mapping))


def _validate_comparison(store: ResearchStore, packet: Mapping, comparison: Any) -> dict:
    root_fields = {"schema_version", "question", "summary", "summary_cells", "next", "sources",
                   "differences", "limitations"}
    if (not isinstance(comparison, Mapping) or type(comparison.get("schema_version")) is not int
            or comparison.get("schema_version") != 1 or set(comparison) != root_fields):
        raise ValueError("comparison must be a schema_version 1 object")
    question = packet.get("input", {}).get("review_question")
    if comparison.get("question") != question:
        raise ValueError("comparison question must exactly match the started task question")
    bindings = packet.get("input", {}).get("source_bindings", [])
    bound = {item["asset_ref"]: set(item["evidence_refs"]) for item in bindings}
    all_evidence = [evidence for ids in bound.values() for evidence in ids]
    if len(all_evidence) != len(set(all_evidence)):
        raise ValueError("selected Evidence IDs must be unique across sources")
    dimensions = packet.get("input", {}).get("dimensions", [])
    rows = comparison.get("sources")
    if (not isinstance(rows, list) or len(rows) != len(bound) or len(rows) > _MAX_SOURCES
            or any(not isinstance(row, Mapping) or set(row) != {"asset_ref", "dimensions"} for row in rows)
            or [row["asset_ref"] for row in rows] != list(bound)):
        raise ValueError("comparison sources must exactly match the selected Asset set")
    assets = {}
    for aid in bound:
        asset = store.latest_record(aid, "Asset")
        if asset is None:
            raise ValueError(f"unknown selected Asset: {aid}")
        assets[aid] = asset
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError("comparison source row must be an object")
        aid = row.get("asset_ref")
        asset = assets[aid]
        cells = row.get("dimensions")
        if not isinstance(cells, Mapping) or set(cells) != set(dimensions):
            raise ValueError("each source must provide exactly one cell for every requested dimension")
        paper = asset.get("asset_kind") == "zotero_reading_capture"
        capture = asset.get("payload", {}).get("request", {}).get("capture", {})
        for dimension, cell in cells.items():
            if (not isinstance(cell, Mapping) or set(cell) != {"status", "value", "interpretation", "citations"}
                    or cell.get("status") not in {"reported", "not_reported_in_read_scope"}):
                raise ValueError(f"invalid comparison cell status for {dimension}")
            if not _bounded_text(cell.get("interpretation"), f"{dimension}.interpretation"):
                raise ValueError(f"each {dimension} cell requires a bounded interpretation (max {_MAX_TEXT} chars)")
            citations = cell.get("citations")
            if not isinstance(citations, list) or len(citations) > 20:
                raise ValueError(f"{dimension} citations must be a list")
            if cell["status"] == "not_reported_in_read_scope":
                if cell.get("value") is not None or citations:
                    raise ValueError("not_reported_in_read_scope cells cannot assert a value or cite fabricated support")
                continue
            if not _bounded_text(cell.get("value"), f"{dimension}.value") or not citations:
                raise ValueError(f"assertive {dimension} cells require a value and exact citations")
            seen_citations = set()
            for citation in citations:
                expected_citation_fields = {"evidence_id", "attachment_key", "page_range"} if paper else {
                    "evidence_id", "locator"}
                if (not isinstance(citation, Mapping) or set(citation) != expected_citation_fields
                        or not isinstance(citation.get("evidence_id"), str)
                        or citation.get("evidence_id") not in bound[aid]):
                    raise ValueError("citation Evidence must be bound to the cited Asset")
                if paper:
                    if not isinstance(citation.get("attachment_key"), str) or not citation["attachment_key"].strip():
                        raise ValueError("paper citation requires an attachment_key")
                    page_range = citation.get("page_range")
                    if (not isinstance(page_range, Mapping) or type(page_range.get("start_page")) is not int
                            or set(page_range) != {"start_page", "end_page"}
                            or type(page_range.get("end_page")) is not int or page_range["start_page"] < 1
                            or page_range["end_page"] < page_range["start_page"]):
                        raise ValueError("paper citation requires a valid page_range")
                    if not _page_is_covered(capture, citation["attachment_key"],
                                            page_range["start_page"], page_range["end_page"]):
                        raise ValueError("paper citation attachment and page range are outside actual saved read coverage")
                    citation_key = (citation["evidence_id"], citation["attachment_key"],
                                    page_range["start_page"], page_range["end_page"])
                else:
                    result = asset.get("payload", {}).get("documentation_result", {})
                    if (result.get("status") not in {"VERIFIED", "SYNTHETIC_VERIFIED", "READ_WITH_LIMITS"}
                            or result.get("coverage_scope") not in {
                                "documentation_passage_reading_only", "mcp_documentation_reading_only"}):
                        raise ValueError("documentation citation requires a readable saved result")
                    passages = result.get("passages", [])
                    if not isinstance(citation.get("locator"), str) or not any(
                            item.get("locator") == citation["locator"] for item in passages
                            if isinstance(item, Mapping)):
                        raise ValueError("documentation citation locator must match a saved readable passage")
                    citation_key = (citation["evidence_id"], citation["locator"])
                if citation_key in seen_citations:
                    raise ValueError("citation entries must be unique within a cell")
                seen_citations.add(citation_key)

    def validate_cell_refs(refs, *, dimension=None, require_reported=False):
        if not isinstance(refs, list) or not refs or len(refs) > _MAX_SOURCES:
            raise ValueError("summary_cells and compared_cells must be non-empty bounded lists")
        seen = set()
        for ref in refs:
            if (not isinstance(ref, Mapping) or set(ref) != {"asset_ref", "dimension"}
                    or not isinstance(ref["asset_ref"], str) or not isinstance(ref["dimension"], str)
                    or ref["asset_ref"] not in bound or ref["dimension"] not in dimensions
                    or (dimension is not None and ref["dimension"] != dimension)
                    or ref["asset_ref"] in seen):
                raise ValueError("cell references must identify distinct selected source cells")
            seen.add(ref["asset_ref"])
            source_row = next(row for row in rows if row["asset_ref"] == ref["asset_ref"])
            if require_reported and source_row["dimensions"][ref["dimension"]]["status"] != "reported":
                raise ValueError("difference compared_cells must point to reported cells")

    validate_cell_refs(comparison.get("summary_cells"))
    differences = comparison.get("differences")
    if not isinstance(differences, list) or len(differences) > _MAX_COLLECTION:
        raise ValueError("differences must be a bounded list")
    for diff in differences:
        refs = diff.get("compared_cells") if isinstance(diff, Mapping) else None
        if (not isinstance(diff, Mapping) or set(diff) != {"dimension", "explanation", "transferability", "compared_cells"}
                or not isinstance(diff.get("dimension"), str)
                or diff.get("dimension") not in dimensions
                or not _bounded_text(diff.get("explanation"), "difference.explanation")
                or not _bounded_text(diff.get("transferability"), "difference.transferability")
                or not isinstance(refs, list) or len(refs) < 2 or len(refs) > _MAX_SOURCES):
            raise ValueError("each difference needs bounded text and references to compared source cells")
        validate_cell_refs(refs, dimension=diff["dimension"], require_reported=True)
    if (not _bounded_text(comparison.get("summary"), "summary")
            or not _bounded_text(comparison.get("next"), "next", limit=_MAX_NEXT)):
        raise ValueError("comparison requires bounded summary and next text")
    if not isinstance(comparison.get("limitations"), list) or len(comparison["limitations"]) > 20 or not all(
            _bounded_text(item, "limitation") for item in comparison["limitations"]):
        raise ValueError("limitations must be a list of non-empty strings")
    return copy.deepcopy(dict(comparison))


def record_literature_comparison(project_root, *, task_id: str, operation_id: str,
                                 comparison: dict, judgment_status="PROVISIONAL_WITH_GAPS") -> dict:
    task_id, operation_id = _id(task_id, "task_id"), _id(operation_id, "operation_id")
    if judgment_status not in {"PROVISIONAL_WITH_GAPS", "INSUFFICIENT"}:
        raise ValueError("judgment_status must be PROVISIONAL_WITH_GAPS or INSUFFICIENT")
    store = ResearchStore(project_root)
    state = store.latest_record(task_id, "TaskState")
    if state is None:
        raise ValueError(f"unknown task: {task_id}")
    packet = state.get("packet", {})
    if (packet.get("task_type", "").rsplit(".", 1)[-1] != "evidence_review"
            or packet.get("input", {}).get("review_mode") != "literature_comparison"):
        raise ValueError("task is not a literature comparison")
    checked = _sources_for_task(store, packet)
    value = _validate_comparison(store, packet, comparison)
    status = judgment_status
    if not any(cell.get("status") == "reported" for row in value["sources"]
               for cell in row["dimensions"].values()) and status == "PROVISIONAL_WITH_GAPS":
        status = "INSUFFICIENT"
    prior_operation = state.get("operation_results", {}).get(operation_id)
    if isinstance(prior_operation, Mapping) and prior_operation.get("status") == "recorded":
        decision = store.latest_record(prior_operation.get("decision_id"), "Decision")
        assessment = decision.get("assessment", {}) if decision else {}
        if (assessment.get("literature_comparison") != value
                or decision.get("judgment", {}).get("status") != status):
            raise ValueError("operation_id was already used with a different comparison or judgment status")
        return {"task_packet": packet, "review_record_ref": prior_operation.get("decision_id"),
                "operation_id": operation_id, "operation_result": copy.deepcopy(prior_operation)}
    gaps = list(value["limitations"])
    gaps.extend(gap for source in checked for gap in source["mandatory_gaps"])
    assessment = {"scope": "material_reading_and_evidence_synthesis_only",
                  "judgment": {"status": status, "summary": value["summary"],
                               "gaps": list(dict.fromkeys(gaps)),
                               "next_action": {"action": value["next"],
                                               "executable": False, "requires_user_choice": True}},
                  "literature_comparison": value,
                  "source_bindings": packet["input"]["source_bindings"],
                  "semantic_claim_verification": "NOT_PERFORMED",
                  "material_reads": [{"asset_id": item["asset_id"], "evidence_refs": item["evidence_refs"],
                                      "observed_sha256": item["content_sha256"],
                                      "reading_status": item.get("reading_status", "READ_WITH_LIMITS"),
                                      "verification_status": "NOT_VERIFIED", "locator": item["locator"],
                                      "summary": "Compared saved observations within recorded reading coverage.",
                                      "numeric_check_status": "NOT_APPLICABLE", "scientific_validation_status": "NOT_VERIFIED",
                                      "gaps": list(item["mandatory_gaps"])} for item in checked],
                  "material_gaps": [{"asset_id": item["asset_id"], "reason": item["reason"],
                                     "next_action": "Keep the source scope limitation attached to interpretation."}
                                    for item in packet.get("material_gaps", [])]}
    result = task_record_evidence_review(project_root, task_id, operation_id, assessment)
    return {"task_packet": result, "review_record_ref": result.get("review_record_ref"),
            "operation_id": operation_id}
