"""Combined review of explicitly selected literature and documentation records."""
from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import (
    _embedded_material_hash, _id, _sha256_json, task_record_evidence_review, task_start,
)
from mining_research_kernel.zotero_reading import validate_capture


_CITATION = re.compile(r"\[evidence:([^\]]+)\]")
_HEADINGS = ("Summary", "Findings", "Gaps", "Next")
_MAX_ASSETS = 20
_MAX_EXCERPT_CHARS = 2000


def _payload_record(store: ResearchStore, asset_id: str, evidence_ids: list[str]):
    asset = store.latest_record(asset_id, "Asset")
    if asset is None:
        raise ValueError(f"unknown asset_ref: {asset_id}")
    if asset.get("asset_kind") not in {"zotero_reading_capture", "documentation_query_snapshot"}:
        raise ValueError(f"unsupported source Asset kind: {asset_id}")
    if _embedded_material_hash(asset) != asset.get("content_sha256"):
        raise ValueError(f"embedded payload hash mismatch: {asset_id}")
    selected = []
    for evidence_id in evidence_ids:
        evidence = store.latest_record(evidence_id, "Evidence")
        if evidence is None or evidence.get("asset_ref") != asset_id:
            raise ValueError(f"Evidence is not bound to selected Asset: {evidence_id}")
        selected.append(evidence)
    if not selected:
        raise ValueError(f"asset requires explicit Evidence refs: {asset_id}")
    payload = asset["payload"]
    kind = asset["asset_kind"]
    if kind == "zotero_reading_capture":
        if payload.get("kind") != "zotero_reading_record" or not isinstance(payload.get("request"), Mapping):
            raise ValueError(f"invalid Zotero capture payload: {asset_id}")
        capture = payload["request"].get("capture")
        if not isinstance(capture, Mapping):
            raise ValueError(f"missing captured source: {asset_id}")
        try:
            capture = validate_capture(dict(capture))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid Zotero capture payload: {asset_id}: {exc}") from exc
        if capture.get("origin") == "synthetic" and payload["request"].get("task_context") != "synthetic":
            raise ValueError(f"synthetic Zotero source is mislabeled: {asset_id}")
    else:
        if payload.get("kind") != "documentation_query_observation" or not isinstance(payload.get("documentation_result"), Mapping):
            raise ValueError(f"invalid documentation snapshot payload: {asset_id}")
        result = payload["documentation_result"]
        citation = result.get("citation", {})
        if (not isinstance(citation, Mapping) or not isinstance(payload.get("request"), Mapping)
                or not isinstance(payload.get("coverage"), Mapping)
                or not isinstance(payload.get("registration_summary"), Mapping)
                or not isinstance(result.get("status"), str)):
            raise ValueError(f"invalid documentation query observation payload: {asset_id}")
        if citation.get("trust_class") == "synthetic" and payload.get("request", {}).get("task_context") != "synthetic":
            raise ValueError(f"synthetic documentation source is mislabeled: {asset_id}")
        status, scope = result.get("status"), result.get("coverage_scope")
        if status not in {"VERIFIED", "SYNTHETIC_VERIFIED", "READ_WITH_LIMITS", "DISCOVERY_ONLY",
                          "CANNOT_READ", "CANNOT_VERIFY"}:
            raise ValueError(f"invalid documentation query status: {asset_id}")
        if not isinstance(scope, str) or not scope:
            raise ValueError(f"invalid documentation coverage scope: {asset_id}")
        passages = result.get("passages", [])
        if not isinstance(passages, list) or any(not isinstance(p, Mapping) or not isinstance(p.get("text"), str)
                                                 or not isinstance(p.get("locator"), str) for p in passages):
            raise ValueError(f"invalid saved documentation passages: {asset_id}")
        uncovered = result.get("uncovered", [])
        if not isinstance(uncovered, list) or not all(isinstance(item, str) and item.strip() for item in uncovered):
            raise ValueError(f"invalid uncovered documentation scope: {asset_id}")
    return asset, selected, payload


def _evidence_for_asset(store: ResearchStore, asset_id: str, expected_kind: str) -> list[str]:
    latest = {}
    for transaction in store.list_transactions():
        for record in transaction.get("records", []):
            if record.get("type") == "Evidence":
                latest[record["id"]] = record
    return sorted(record["id"] for record in latest.values()
                  if record.get("asset_ref") == asset_id and record.get("evidence_kind") == expected_kind)


def _decisions_for_sources(store: ResearchStore, asset_ids: set[str], evidence_ids: set[str]) -> list[str]:
    refs = {*(f"asset:{item}" for item in asset_ids), *(f"evidence:{item}" for item in evidence_ids)}
    latest = {}
    for transaction in store.list_transactions():
        for record in transaction.get("records", []):
            if record.get("type") == "Decision": latest[record["id"]] = record
    found = {record["id"] for record in latest.values()
             if refs.intersection(record.get("source_refs", []))}
    for asset_id in asset_ids:
        asset = store.latest_record(asset_id, "Asset")
        origin_task = asset.get("payload", {}).get("request", {}).get("task_id") if asset else None
        task = store.latest_record(origin_task, "TaskState") if isinstance(origin_task, str) else None
        decision_id = task.get("packet", {}).get("review_record_ref") if task else None
        if isinstance(decision_id, str) and store.latest_record(decision_id, "Decision") is not None:
            found.add(decision_id)
    return sorted(found)


def _overview(asset, evidence, payload):
    kind = asset["asset_kind"]
    if kind == "zotero_reading_capture":
        capture = payload["request"]["capture"]
        pages = capture.get("pages", [])
        read_pages = [p for p in pages if p.get("status") == "read"]
        failed = [p for p in pages if p.get("status") != "read"]
        excerpts = []
        for page in read_pages:
            excerpt = page.get("excerpt", "")
            excerpts.append({"attachment_key": page.get("attachment_key"), "start_page": page.get("start_page"),
                             "end_page": page.get("end_page"), "excerpt": excerpt[:_MAX_EXCERPT_CHARS],
                             "excerpt_truncated": len(excerpt) > _MAX_EXCERPT_CHARS})
        return {
            "asset_ref": asset["id"], "asset_revision": asset["revision"], "asset_kind": kind,
            "evidence_refs": [e["id"] for e in evidence], "content_sha256": asset["content_sha256"],
            "identity": {"title": capture["item"].get("title"), "item_key": capture["item"].get("key"),
                         "doi": capture["item"].get("doi"), "item_type": capture["item"].get("item_type"),
                         "instance_id": capture.get("instance_id"), "library_id": capture.get("library_id"),
                         "item_version": capture["item"].get("version"), "captured_at": capture.get("captured_at"),
                         "origin": capture.get("origin")},
            "coverage": {"read_page_ranges": [{k: p.get(k) for k in ("attachment_key", "start_page", "end_page")}
                                                    for p in read_pages],
                         "failed_page_ranges": [{k: p.get(k) for k in ("attachment_key", "start_page", "end_page", "status")}
                                                    for p in failed],
                         "metadata_status": capture.get("metadata_status"), "diagnostics": copy.deepcopy(capture.get("diagnostics", []))},
            "saved_excerpts": excerpts,
            "saved_findings": copy.deepcopy(payload.get("request", {}).get("findings", [])),
            "provenance": copy.deepcopy(payload.get("provenance", {})),
            "truncation_flags": {"saved_excerpts": any(item["excerpt_truncated"] for item in excerpts),
                                 "identity": False, "coverage": False, "saved_findings": False},
            "expansion": {"record_ids": [asset["id"], *[e["id"] for e in evidence]],
                          "task_id": payload.get("request", {}).get("task_id")},
            "limits": ["historical caller supplied capture; source not revalidated",
                       "page observations apply only to saved capture ranges", "scientific and numeric claims NOT_VERIFIED"],
        }
    result = payload["documentation_result"]
    citation = result.get("citation", {})
    saved_passages = result.get("passages", [])
    return {
        "asset_ref": asset["id"], "asset_revision": asset["revision"], "asset_kind": kind,
        "evidence_refs": [e["id"] for e in evidence], "content_sha256": asset["content_sha256"],
        "identity": {k: citation.get(k) for k in ("source_id", "product", "document_family", "document_build", "page", "anchor", "trust_class")},
        "provenance": {"registration_summary": copy.deepcopy(payload.get("registration_summary", {})),
                       "citation": copy.deepcopy(citation), "source_query_performed_at_capture": True,
                       "source_query_performed_this_call": False,
                       "source_freshness": "saved query observation; no fresh check during review"},
        "expansion": {"record_ids": [asset["id"], *[e["id"] for e in evidence]],
                      "task_id": payload.get("request", {}).get("task_id"),
                      "query": {k: payload.get("request", {}).get(k) for k in ("page", "command", "product", "product_version", "anchor")}},
        "coverage": copy.deepcopy(payload.get("coverage", {})), "saved_passages": copy.deepcopy(saved_passages),
        "query": copy.deepcopy(payload.get("request", {})),
        "query_result": {"status": result.get("status"), "coverage_scope": result.get("coverage_scope"),
                         "uncovered": copy.deepcopy(result.get("uncovered", [])), "stop_reason": result.get("stop_reason")},
        "limits": ["saved query observation only; not verification of a paper, model, or engineering claim",
                   "source page is not fresh; query coverage remains bounded"],
        "truncation_flags": {"identity": False, "coverage": False, "query": False, "query_result": False},
    }


def start_source_review(project_root, *, task_id: str, question: str, asset_refs: list[str], task_context="production",
                        review_mode="combined_sources", dimensions=None) -> dict:
    task_id, question = _id(task_id, "task_id"), question.strip() if isinstance(question, str) else ""
    if not question:
        raise ValueError("question must be a non-empty combined review question")
    if task_context not in {"production", "synthetic"}:
        raise ValueError("task_context must be production or synthetic")
    if review_mode not in {"combined_sources", "literature_comparison"}:
        raise ValueError("unsupported review_mode")
    if dimensions is None:
        dimensions = ["materials", "conditions", "methods", "parameters", "results", "applicability"]
    if (not isinstance(dimensions, list) or not dimensions
            or not all(isinstance(item, str) and item.strip() for item in dimensions)
            or len(set(dimensions)) != len(dimensions)):
        raise ValueError("dimensions must be a non-empty unique list of strings")
    if review_mode == "literature_comparison" and (
            len(dimensions) > 12 or any(len(item) > 80 for item in dimensions) or len(question) > 2000):
        raise ValueError("literature comparison question or dimensions exceed bounded limits")
    if (not isinstance(asset_refs, list) or not asset_refs
            or not all(isinstance(item, str) and item.strip() for item in asset_refs)
            or len(set(asset_refs)) != len(asset_refs)):
        raise ValueError("asset_refs must be a non-empty unique list")
    if len(asset_refs) > _MAX_ASSETS:
        raise ValueError(f"source review accepts at most {_MAX_ASSETS} selected Assets")
    store = ResearchStore(project_root)
    assets, evidence_refs, overviews = [], [], []
    for aid in asset_refs:
        aid = _id(aid, "asset_ref")
        asset = store.latest_record(aid, "Asset")
        if asset is None:
            raise ValueError(f"unknown asset_ref: {aid}")
        if asset.get("asset_kind") == "zotero_reading_capture":
            evs = _evidence_for_asset(store, aid, "zotero_reading_observation")
        elif asset.get("asset_kind") == "documentation_query_snapshot":
            evs = _evidence_for_asset(store, aid, "documentation_query_observation")
        else:
            raise ValueError(f"unsupported source Asset kind: {aid}")
        current, selected, payload = _payload_record(store, aid, evs)
        if current.get("payload", {}).get("request", {}).get("task_context") == "synthetic" and task_context != "synthetic":
            raise ValueError("synthetic source records require synthetic task_context")
        if current.get("asset_kind") == "documentation_query_snapshot":
            c = payload.get("documentation_result", {}).get("citation", {})
            if c.get("trust_class") == "synthetic" and task_context != "synthetic":
                raise ValueError("synthetic source records require synthetic task_context")
        assets.append(current); evidence_refs.extend(e["id"] for e in selected)
        overviews.append(_overview(current, selected, payload))
    if review_mode == "literature_comparison" and len(evidence_refs) != len(set(evidence_refs)):
        raise ValueError("literature comparison Evidence IDs must be unique")
    kinds = {a["asset_kind"] for a in assets}
    if review_mode == "combined_sources" and not {"zotero_reading_capture", "documentation_query_snapshot"}.issubset(kinds):
        raise ValueError("source review requires at least one Zotero capture and one documentation query snapshot")
    if review_mode == "literature_comparison":
        papers = [o["identity"] for o in overviews if o["asset_kind"] == "zotero_reading_capture"]
        identities = {(p.get("instance_id"), p.get("library_id"), p.get("item_key")) for p in papers}
        if len(papers) < 2 or len(identities) != len(papers):
            raise ValueError("literature comparison requires at least two distinct paper identities")
        if any(not o.get("coverage", {}).get("read_page_ranges")
               for o in overviews if o["asset_kind"] == "zotero_reading_capture"):
            raise ValueError("each selected paper must have successfully read page coverage")
    bindings = [{"asset_ref": a["id"], "revision": a["revision"], "sha256": a["content_sha256"],
                 "evidence_refs": o["evidence_refs"],
                 "evidence_revisions": {eid: store.latest_record(eid, "Evidence")["revision"]
                                        for eid in o["evidence_refs"]}}
                for a, o in zip(assets, overviews)]
    prior_decisions = _decisions_for_sources(store, {a["id"] for a in assets}, set(evidence_refs))
    fingerprint_value = {"question": question, "context": task_context, "bindings": bindings}
    if review_mode == "literature_comparison":
        fingerprint_value.update({"review_mode": review_mode, "dimensions": dimensions})
    fingerprint = _sha256_json(fingerprint_value)
    prior = store.latest_record(task_id, "TaskState")
    replayed = prior is not None
    if prior:
        packet = prior.get("packet", {})
        stored_input = packet.get("input", {})
        if stored_input.get("source_bindings") != bindings:
            raise ValueError("source Asset or Evidence revision or hash changed since source review start")
        if stored_input.get("source_review_fingerprint") != fingerprint:
            raise ValueError(f"task_id already exists with different source review inputs: {task_id}")
    else:
        stored_input = {"source_review_fingerprint": fingerprint, "source_bindings": bindings}
        if review_mode == "literature_comparison":
            stored_input.update({"review_mode": review_mode, "dimensions": list(dimensions),
                                 "review_question": question})
        packet = task_start(project_root, {
            "task_id": task_id, "task_context": task_context,
            "workflow_id": "research",
            "task_type": "mining_research_kernel.task.evidence_review",
            "question_statement": question,
            "claim_statement": f"Evidence synthesis addressing: {question}",
            "asset_refs": [a["id"] for a in assets], "evidence_refs": evidence_refs,
            "refs": {"decisions": prior_decisions},
            "input": stored_input,
        })
    review_template = ("## Summary\n<nonempty text>\n\n## Findings\n- <interpretation> [evidence:<id>]\n\n"
                       "## Gaps\n- <limits text>\n\n## Next\n<suggestion; user retains finish/next choice>\n")
    return {"task_packet": packet, "sources": overviews, "review_template": review_template,
            "review_mode": review_mode, "dimensions": list(dimensions), "replayed": replayed}


def _parse_note(note: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(note, str):
        raise ValueError("note must be Markdown text")
    lines = note.splitlines()
    positions = [(i, line[3:]) for i, line in enumerate(lines) if line.startswith("## ")]
    if [h for _, h in positions] != list(_HEADINGS):
        raise ValueError("note must contain each required heading exactly once and in order")
    sections = {h: "\n".join(lines[i+1:(positions[n+1][0] if n+1 < len(positions) else len(lines))]).strip()
                for n, (i, h) in enumerate(positions)}
    for h in ("Summary", "Gaps", "Next"):
        if not sections[h]: raise ValueError(f"{h} section must be non-empty")
    if any(ref not in allowed for ref in _CITATION.findall(note)):
        raise ValueError("note cites unknown or unselected Evidence")
    refs = []
    for line in sections["Findings"].splitlines():
        if line.strip() and not line.lstrip().startswith("-"):
            raise ValueError("Findings must contain only bullet lines")
        if line.strip():
            found = _CITATION.findall(line)
            if not found: raise ValueError("each finding requires at least one exact evidence citation")
            if any(ref not in allowed for ref in found): raise ValueError("finding cites unknown or unselected Evidence")
            refs.extend(found)
    return {"sections": sections, "evidence_refs": list(dict.fromkeys(refs))}


def record_source_review(project_root, *, task_id: str, operation_id: str, note: str,
                         judgment_status="PROVISIONAL_WITH_GAPS") -> dict:
    task_id, operation_id = _id(task_id, "task_id"), _id(operation_id, "operation_id")
    if judgment_status not in {"PROVISIONAL_WITH_GAPS", "INSUFFICIENT"}:
        raise ValueError("judgment_status must be PROVISIONAL_WITH_GAPS or INSUFFICIENT")
    store = ResearchStore(project_root)
    state = store.latest_record(task_id, "TaskState")
    if state is None: raise ValueError(f"unknown task: {task_id}")
    packet = state.get("packet", {})
    bindings = packet.get("input", {}).get("source_bindings")
    if packet.get("input", {}).get("review_mode") == "literature_comparison":
        raise ValueError("literature comparison tasks require literature-review with structured page citations")
    if packet.get("task_type", "").rsplit(".", 1)[-1] != "evidence_review" or not isinstance(bindings, list):
        raise ValueError("task is not a source review task")
    source_checks = _sources_for_task(store, packet)
    refs = set(packet.get("evidence_refs", []))
    refs.difference_update(evidence_id for source in source_checks
                           if not source.get("citation_evidence_allowed", True)
                           for evidence_id in source.get("evidence_refs", []))
    parsed = _parse_note(note, refs)
    effective_status = judgment_status
    if not parsed["evidence_refs"] and effective_status == "PROVISIONAL_WITH_GAPS":
        effective_status = "INSUFFICIENT"
    prior_operation = state.get("operation_results", {}).get(operation_id)
    if isinstance(prior_operation, Mapping) and prior_operation.get("status") == "recorded":
        decision = store.latest_record(prior_operation.get("decision_id"), "Decision")
        assessment = decision.get("assessment", {}) if decision else {}
        if assessment.get("note") != note or decision.get("judgment", {}).get("status") != effective_status:
            raise ValueError("operation_id was already used with a different note or judgment status")
        return {"task_packet": packet, "review_record_ref": prior_operation.get("decision_id"),
                "operation_id": operation_id, "operation_result": copy.deepcopy(prior_operation)}
    must_gaps = []
    for item in packet.get("material_gaps", []):
        must_gaps.append(str(item.get("reason", "material limitation")))
    for source in source_checks:
        must_gaps.extend(source["mandatory_gaps"])
    assessment = {"scope": "material_reading_and_evidence_synthesis_only",
                  "judgment": {"status": effective_status, "summary": parsed["sections"]["Summary"],
                               "gaps": list(dict.fromkeys([parsed["sections"]["Gaps"], *must_gaps])),
                               "next_action": {"action": parsed["sections"]["Next"], "executable": False,
                                               "requires_user_choice": True}},
                  "note": note, "parsed_note": parsed, "source_bindings": bindings,
                  "material_reads": [{"asset_id": item["asset_id"], "evidence_refs": item["evidence_refs"],
                                      "observed_sha256": item["content_sha256"],
                                      "reading_status": next((source.get("reading_status", "READ_WITH_LIMITS")
                                                              for source in source_checks
                                                              if source["asset_id"] == item["asset_id"]),
                                                             "READ_WITH_LIMITS"),
                                      "verification_status": "NOT_VERIFIED", "locator": item["locator"],
                                      "summary": "Reviewed saved source observation within its recorded coverage.",
                                      "numeric_check_status": "NOT_APPLICABLE", "scientific_validation_status": "NOT_VERIFIED",
                                      "gaps": list(dict.fromkeys(["original source was not freshly revalidated", *must_gaps]))}
                                     for item in packet.get("material_reads", [])],
                  "material_gaps": [{"asset_id": item["asset_id"], "reason": str(item.get("reason", "source limitation")),
                                     "next_action": "preserve this source scope limitation in subsequent interpretation"}
                                    for item in packet.get("material_gaps", [])]}
    result = task_record_evidence_review(project_root, task_id, operation_id, assessment)
    return {"task_packet": result, "review_record_ref": result.get("review_record_ref"), "operation_id": operation_id}


def _sources_for_task(store: ResearchStore, packet: Mapping[str, Any]) -> list[dict[str, Any]]:
    results = []
    bindings = packet.get("input", {}).get("source_bindings", [])
    if not isinstance(bindings, list) or not bindings:
        raise ValueError("source review packet has no source bindings")
    bound_assets, bound_evidence, kinds = set(), set(), set()
    for binding in bindings:
        if not isinstance(binding, Mapping):
            raise ValueError("source review packet contains an invalid source binding")
        if (not isinstance(binding.get("asset_ref"), str)
                or not isinstance(binding.get("evidence_refs"), list)
                or not all(isinstance(item, str) for item in binding["evidence_refs"])):
            raise ValueError("source review packet contains invalid Asset/Evidence allowlists")
        bound_assets.add(binding.get("asset_ref"))
        bound_evidence.update(binding.get("evidence_refs", []))
        asset = store.latest_record(binding["asset_ref"], "Asset")
        if (asset is None or asset.get("revision") != binding.get("revision")
                or asset.get("content_sha256") != binding.get("sha256")
                or _embedded_material_hash(asset) != binding.get("sha256")):
            raise ValueError(f"source Asset revision or payload changed: {binding.get('asset_ref')}")
        selected_evidence = binding.get("evidence_refs")
        if not isinstance(selected_evidence, list):
            raise ValueError("source review packet has invalid Evidence bindings")
        checked_asset, _, payload = _payload_record(store, asset["id"], selected_evidence)
        revisions = binding.get("evidence_revisions")
        if (not isinstance(revisions, Mapping) or set(revisions) != set(selected_evidence)
                or any(store.latest_record(eid, "Evidence")["revision"] != revisions[eid]
                       for eid in selected_evidence)):
            raise ValueError("source Evidence revision changed or was not bound at review start")
        if checked_asset["asset_kind"] not in {"zotero_reading_capture", "documentation_query_snapshot"}:
            raise ValueError("source review packet includes an unsupported source kind")
        kinds.add(checked_asset["asset_kind"])
        if packet.get("task_context") != "synthetic":
            if checked_asset["asset_kind"] == "zotero_reading_capture" and payload.get("request", {}).get("capture", {}).get("origin") == "synthetic":
                raise ValueError("synthetic source records require synthetic task_context")
            if checked_asset["asset_kind"] == "documentation_query_snapshot" and payload.get("documentation_result", {}).get("citation", {}).get("trust_class") == "synthetic":
                raise ValueError("synthetic source records require synthetic task_context")
        payload = asset.get("payload", {}) if asset else {}
        gaps = []
        if asset and asset.get("asset_kind") == "zotero_reading_capture":
            capture = payload.get("request", {}).get("capture", {})
            provenance = payload.get("provenance", {})
            uncertain_versions = provenance.get("uncertain_version_fields", []) if isinstance(provenance, Mapping) else []
            if uncertain_versions:
                gaps.append("source version unknown or zero: " + ", ".join(str(item) for item in uncertain_versions))
            if capture.get("origin") == "synthetic": gaps.append("synthetic source; production evidence not established")
            if any(p.get("status") != "read" for p in capture.get("pages", [])): gaps.append("failed page ranges are unavailable and provide no support")
            if not any(p.get("status") == "read" for p in capture.get("pages", [])): gaps.append("no successfully captured page content")
            gaps.append("page findings are limited to saved capture coverage; original source not freshly reread")
        elif asset:
            result = payload.get("documentation_result", {})
            request = payload.get("request", {})
            status, coverage_scope = result.get("status"), result.get("coverage_scope")
            command = request.get("command") if isinstance(request, Mapping) else None
            gaps.append(f"documentation query status={status}; coverage_scope={coverage_scope}; command={command!r}")
            if status in {"CANNOT_READ", "CANNOT_VERIFY"}: gaps.append("documentation query was unverified or failed")
            if status == "READ_WITH_LIMITS": gaps.append("documentation passages were read with stated limits")
            if status == "DISCOVERY_ONLY": gaps.append("discovery result is not passage reading and cannot support cited text claims")
            if result.get("status") == "SYNTHETIC_VERIFIED": gaps.append("synthetic documentation query does not establish production applicability")
            trust = result.get("citation", {}).get("trust_class")
            if trust == "community_mcp":
                gaps.append("community MCP documentation is derived material and does not independently prove official source or version")
            if trust == "official_local":
                gaps.append("official local documentation applies only to the recorded product and document build; other versions are not inferred")
            gaps.extend(result.get("uncovered", []))
            gaps.append("documentation query status applies only to saved query coverage, not paper or engineering verification")
        reading_status, citation_evidence_allowed = "READ_WITH_LIMITS", True
        if asset and asset.get("asset_kind") == "documentation_query_snapshot":
            doc_result = payload.get("documentation_result", {})
            if doc_result.get("status") == "DISCOVERY_ONLY" or doc_result.get("coverage_scope") == "discovery_only":
                reading_status, citation_evidence_allowed = "READ_INSUFFICIENT", False
            elif doc_result.get("status") in {"CANNOT_READ", "CANNOT_VERIFY"}:
                reading_status = "READ_INSUFFICIENT"
        results.append({"asset_id": asset["id"], "evidence_refs": list(selected_evidence),
                        "content_sha256": asset["content_sha256"],
                        "locator": {"asset_revision": asset["revision"], "asset_kind": asset["asset_kind"]},
                        "reading_status": reading_status,
                        "citation_evidence_allowed": citation_evidence_allowed,
                        "mandatory_gaps": gaps})
    mode = packet.get("input", {}).get("review_mode", "combined_sources")
    if mode == "combined_sources" and not {"zotero_reading_capture", "documentation_query_snapshot"}.issubset(kinds):
        raise ValueError("source review task must bind both required source kinds")
    if mode == "literature_comparison":
        papers = [store.latest_record(aid, "Asset") for aid in bound_assets]
        papers = [a for a in papers if a and a.get("asset_kind") == "zotero_reading_capture"]
        identities = {(a["payload"]["request"]["capture"].get("instance_id"),
                       a["payload"]["request"]["capture"].get("library_id"),
                       a["payload"]["request"]["capture"].get("item", {}).get("key")) for a in papers}
        if len(papers) < 2 or len(identities) != len(papers):
            raise ValueError("literature comparison requires at least two distinct paper identities")
    if bound_assets != set(packet.get("asset_refs", [])) or bound_evidence != set(packet.get("evidence_refs", [])):
        raise ValueError("source review task Asset/Evidence allowlist does not match its source bindings")
    return results
