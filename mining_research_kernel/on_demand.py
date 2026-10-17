"""Read-only, on-demand recovery views over the persisted research store.

The views are disposable projections.  They do not create records, rebuild
the Research Map, or inspect/re-hash registered source materials.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from mining_research_kernel.records import ResearchStore


DEFAULT_MAX_CHARS = 4000


def _latest_records(store: ResearchStore) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for transaction in store.list_transactions():
        for record in transaction["records"]:
            previous = latest.get(record["id"])
            if previous is None or record["revision"] >= previous["revision"]:
                latest[record["id"]] = copy.deepcopy(record)
    return latest


def _source_refs(record: dict[str, Any]) -> set[str]:
    return {item for item in record.get("source_refs", []) if isinstance(item, str)}


def _judgment(record: dict[str, Any]) -> dict[str, Any]:
    value = record.get("judgment")
    if isinstance(value, dict):
        return value
    assessment = record.get("assessment")
    if isinstance(assessment, dict) and isinstance(assessment.get("judgment"), dict):
        return assessment["judgment"]
    return {}


def _base_decision_ids(record: dict[str, Any]) -> list[str]:
    """Return explicit lineage references without using record order as meaning."""
    result: list[str] = []
    update = record.get("update") if isinstance(record.get("update"), dict) else {}
    scope = record.get("scope") if isinstance(record.get("scope"), dict) else {}
    judgment = _judgment(record)
    inherited = judgment.get("inherited_from") if isinstance(judgment.get("inherited_from"), dict) else {}
    for value in (
        update.get("base_decision_id"),
        scope.get("base_decision_id"),
        inherited.get("decision_id"),
    ):
        if isinstance(value, str) and value and value not in result:
            result.append(value)
    return result


def _preview(value: Any, limit: int = 360) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 24)] + "… [see show expansion]"


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if isinstance(value, str) and value.strip()))


def _record_revision(store: ResearchStore, record_id: str, revision: int,
                    record_type: str | None = None) -> dict[str, Any] | None:
    for transaction in store.list_transactions():
        for record in transaction.get("records", []):
            if (record.get("id") == record_id and record.get("revision") == revision
                    and (record_type is None or record.get("type") == record_type)):
                return copy.deepcopy(record)
    return None


def _decision_bound_to_task_state(store: ResearchStore, task: dict[str, Any]) -> dict[str, Any] | None:
    packet = task.get("packet", {})
    decision_id = packet.get("review_record_ref")
    if not isinstance(decision_id, str):
        return None
    for transaction in store.list_transactions():
        records = transaction.get("records", [])
        has_state = any(record.get("type") == "TaskState" and record.get("id") == task.get("id")
                        and record.get("revision") == task.get("revision") for record in records)
        if has_state:
            decision = next((record for record in records if record.get("type") == "Decision"
                             and record.get("id") == decision_id), None)
            if decision:
                return copy.deepcopy(decision)
    return None


def _continuation_parent(store: ResearchStore, task_id: str, packet: dict[str, Any]) -> dict[str, Any] | None:
    """Validate persisted continuation lineage and return its exact bound parent Decision."""
    continuation = packet.get("input", {}).get("research_continuation")
    if not isinstance(continuation, dict):
        return None
    from mining_research_kernel.research_continuation import research_progress

    progress = research_progress(store.project_root, task_id=task_id)
    if len(progress.get("steps", [])) < 2:
        raise ValueError("research continuation has no validated parent step")
    parent = progress["steps"][-2]
    decision_id = continuation.get("previous_decision_id")
    decision_revision = continuation.get("previous_decision_revision")
    if (parent.get("task_id") != continuation.get("previous_task_id")
            or parent.get("task_revision") != continuation.get("previous_task_revision")
            or parent.get("decision_id") != decision_id
            or parent.get("decision_revision") != decision_revision):
        raise ValueError("research continuation parent does not match its validated lineage")
    record = _record_revision(store, decision_id, decision_revision, "Decision")
    if record is None:
        raise ValueError(f"continuation references unavailable Decision revision: {decision_id}@{decision_revision}")
    return record


def is_research_review_task(packet: dict[str, Any]) -> bool:
    inputs = packet.get("input") if isinstance(packet.get("input"), dict) else {}
    return (packet.get("workflow_id") in {"research", "mining_research_kernel.workflow.research"}
            and inputs.get("review_mode") in {"combined_sources", "literature_comparison", "selected_sources"})


def is_research_review_continuation(packet: dict[str, Any]) -> bool:
    inputs = packet.get("input") if isinstance(packet.get("input"), dict) else {}
    return is_research_review_task(packet) and isinstance(inputs.get("research_continuation"), dict)


def _question_and_routes(
    latest: dict[str, dict[str, Any]], packet: dict[str, Any]
) -> tuple[str, str | None, list[dict[str, Any]]]:
    route_summaries: list[dict[str, Any]] = []
    question = packet.get("question_statement")
    question_id = None
    for route_id in packet.get("routes", []):
        route = latest.get(route_id)
        if not isinstance(route, dict):
            continue
        question_id = route.get("question_id") or route.get("research_question_id") or question_id
        route_summaries.append({
            "id": route_id,
            "revision": route.get("revision"),
            "status": route.get("status"),
            "runs_used": route.get("runs_used"),
            "stop_reason": route.get("stop_reason"),
            "method_id": route.get("method_id"),
        })
    if question_id:
        question_record = latest.get(question_id)
        if isinstance(question_record, dict):
            question = question_record.get("statement") or question
    if not isinstance(question, str) or not question.strip():
        question = "No persisted research question was found for this task."
    return question, question_id, route_summaries


def _decision_records(
    latest: dict[str, dict[str, Any]], task_id: str, packet: dict[str, Any], route_ids: list[str],
    *, exact_decisions: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    decision_ids: list[str] = []
    decision_ids.extend(item for item in packet.get("relevant_decision_refs", []) if isinstance(item, str))
    refs = packet.get("refs", {})
    if isinstance(refs, dict):
        decision_ids.extend(item for item in refs.get("decisions", []) if isinstance(item, str))
    if isinstance(packet.get("review_record_ref"), str):
        decision_ids.append(packet["review_record_ref"])
    related: list[dict[str, Any]] = []
    for record in latest.values():
        if record.get("type") != "Decision":
            continue
        refs_for_record = _source_refs(record)
        if record.get("id") in decision_ids or f"task:{task_id}" in refs_for_record:
            related.append(record)
            decision_ids.append(record["id"])
            continue
        if any(f"route:{route_id}" in refs_for_record for route_id in route_ids):
            related.append(record)
            decision_ids.append(record["id"])
    by_id = {record["id"]: record for record in related}
    for record in exact_decisions or []:
        if record.get("type") == "Decision" and record.get("id") in by_id:
            by_id[record["id"]] = record
    return [by_id[item] for item in dict.fromkeys(decision_ids) if item in by_id]


def _decision_selection(
    records: list[dict[str, Any]], task_id: str, packet: dict[str, Any],
    inherited: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Separate current judgments from explicit history and unresolved branches.

    A TaskState review reference is the primary current pointer.  Other
    decisions become history only when their task scope differs or they are
    an explicit lineage ancestor.  Same-task, non-ancestor branches remain a
    visible conflict instead of being selected by transaction order.
    """
    by_id = {record.get("id"): record for record in records if isinstance(record.get("id"), str)}
    review_ref = packet.get("review_record_ref")
    explicit_refs: list[str] = []
    for value in packet.get("relevant_decision_refs", []):
        if isinstance(value, str) and value not in explicit_refs:
            explicit_refs.append(value)
    refs = packet.get("refs")
    if isinstance(refs, dict):
        for value in refs.get("decisions", []):
            if isinstance(value, str) and value not in explicit_refs:
                explicit_refs.append(value)

    parents = {record_id: set(_base_decision_ids(record)) for record_id, record in by_id.items()}

    def ancestors(record_id: str) -> set[str]:
        found: set[str] = set()
        pending = list(parents.get(record_id, set()))
        while pending:
            parent = pending.pop()
            if parent in found:
                continue
            found.add(parent)
            pending.extend(parents.get(parent, set()) - found)
        return found

    current_ids: list[str] = []
    history_ids: set[str] = set()
    conflict_ids: list[str] = []
    selection_reason = "single_related_decision"

    if isinstance(review_ref, str) and review_ref in by_id:
        current_ids = [review_ref]
        review_ancestors = ancestors(review_ref)
        history_ids.update(review_ancestors)
        for record_id, record in by_id.items():
            if record_id == review_ref or record_id in review_ancestors:
                continue
            refs_for_record = _source_refs(record)
            same_task = f"task:{task_id}" in refs_for_record or (
                isinstance(record.get("scope"), dict) and record["scope"].get("task_id") == task_id
            )
            if same_task:
                conflict_ids.append(record_id)
            else:
                history_ids.add(record_id)
        if conflict_ids:
            current_ids.extend(conflict_ids)
            selection_reason = "review_record_ref_with_same_task_conflict"
        else:
            selection_reason = "review_record_ref_current_history"
    else:
        # Without a current pointer, use explicit lineage to identify a
        # unique leaf.  Multiple unrelated leaves are an unresolved conflict.
        candidates = [record_id for record_id in explicit_refs if record_id in by_id]
        if not candidates:
            candidates = [record_id for record_id in by_id]
        leaves = [
            record_id for record_id in candidates
            if not any(record_id in ancestors(other) for other in candidates if other != record_id)
        ]
        if len(leaves) == 1:
            current_ids = leaves
            history_ids.update(set(candidates) - set(leaves))
            selection_reason = "unique_lineage_leaf"
        else:
            current_ids = leaves or candidates
            selection_reason = "unresolved_current_conflict"
            conflict_ids = list(current_ids)
            history_ids.update(set(candidates) - set(current_ids))

    if inherited and not (isinstance(review_ref, str) and review_ref in by_id):
        inherited_ids = {item.get("id") for item in inherited}
        ancestors_of_inherited = set().union(*(ancestors(item) for item in inherited_ids if item in by_id))
        current_ids = []
        conflicts = []
        for record_id, record in by_id.items():
            if record_id in inherited_ids or record_id in ancestors_of_inherited:
                continue
            refs_for_record = _source_refs(record)
            same_task = f"task:{task_id}" in refs_for_record or (
                isinstance(record.get("scope"), dict) and record["scope"].get("task_id") == task_id
            )
            if same_task:
                conflicts.append(record)
        conflict_ids = [record.get("id") for record in conflicts]
        history_ids.update(record_id for record_id in by_id if record_id not in inherited_ids
                           and record_id not in conflict_ids)
        selection_reason = "pending_continuation_inherits_parent"

    # Preserve explicitly cited records that are not part of the current
    # branch as history; they remain discoverable through citations/show.
    history_ids.update(record_id for record_id in explicit_refs if record_id in by_id and record_id not in current_ids)
    history_ids.difference_update(current_ids)
    current = [by_id[record_id] for record_id in current_ids if record_id in by_id]
    history = [by_id[record_id] for record_id in by_id if record_id in history_ids]
    conflicts = [by_id[record_id] for record_id in conflict_ids if record_id in by_id]
    return {
        "current": current,
        "history": history,
        "conflicts": conflicts,
        "current_ids": [record.get("id") for record in current],
        "history_ids": [record.get("id") for record in history],
        "conflict_ids": [record.get("id") for record in conflicts],
        "inherited": inherited or [],
        "review_record_ref": review_ref if isinstance(review_ref, str) else None,
        "reason": selection_reason,
    }


def _material_versions(
    latest: dict[str, dict[str, Any]], packet: dict[str, Any], decisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    materials: dict[str, dict[str, Any]] = {}
    for material in packet.get("material_reads", []):
        if not isinstance(material, dict) or not isinstance(material.get("asset_id"), str):
            continue
        asset_id = material["asset_id"]
        asset = latest.get(asset_id, {})
        locator = material.get("requested_locator") or material.get("locator") or asset.get("locator") or {}
        reading = material.get("reading") if isinstance(material.get("reading"), dict) else {}
        if reading.get("locator"):
            locator = reading["locator"]
        materials[asset_id] = {
            "asset_id": asset_id,
            "revision": asset.get("revision"),
            "path": locator.get("path") if isinstance(locator, dict) else None,
            "content_sha256": material.get("content_sha256") or asset.get("content_sha256"),
            "content_status": material.get("content_status"),
            "reading_status": material.get("reading_status"),
            "verification_status": material.get("verification_status"),
        }
    for decision in decisions:
        assessment = decision.get("assessment")
        if not isinstance(assessment, dict):
            continue
        for material in assessment.get("material_reads", []):
            if not isinstance(material, dict) or not isinstance(material.get("asset_id"), str):
                continue
            asset_id = material["asset_id"]
            existing = materials.setdefault(asset_id, {"asset_id": asset_id})
            existing.setdefault("revision", latest.get(asset_id, {}).get("revision"))
            existing.setdefault("content_sha256", material.get("observed_sha256"))
            existing.setdefault("path", (material.get("locator") or {}).get("path"))
            existing["historical_reading_status"] = material.get("reading_status")
            existing["historical_verification_status"] = material.get("verification_status")
    return list(materials.values())


def _judgment_summaries(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for decision in decisions:
        judgment = _judgment(decision)
        next_action = judgment.get("next_action") if isinstance(judgment.get("next_action"), dict) else {}
        summaries.append({
            "decision_id": decision.get("id"),
            "revision": decision.get("revision"),
            "status": judgment.get("status") or decision.get("status"),
            "summary": judgment.get("summary") or decision.get("statement"),
            "scope": decision.get("scope"),
            "gaps": judgment.get("gaps", []),
            "next_action": next_action,
        })
    return summaries


def _related_failures(latest: dict[str, dict[str, Any]], task_id: str, route_ids: list[str]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for failure in latest.values():
        if failure.get("type") != "Failure":
            continue
        refs = _source_refs(failure)
        if failure.get("task_id") == task_id or failure.get("route_id") in route_ids:
            related = True
        else:
            related = f"task:{task_id}" in refs or any(f"route:{route_id}" in refs for route_id in route_ids)
        if not related:
            continue
        failures.append({
            "failure_id": failure.get("id"),
            "status": failure.get("status"),
            "severity": failure.get("severity"),
            "observable_failure": failure.get("observable_failure"),
            "resolution_status": failure.get("resolution_status"),
            "applicability": failure.get("applicability"),
        })
    return sorted(failures, key=lambda item: item.get("failure_id") or "")


def _gap_items(packet: dict[str, Any], decisions: list[dict[str, Any]], failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    for gap in packet.get("material_gaps", []):
        if isinstance(gap, dict):
            gaps.append({"source": "material", "text": gap.get("reason"), "next_action": gap.get("next_action")})
    if packet.get("stop_reason"):
        gaps.append({"source": "task", "text": packet.get("stop_reason"), "next_action": packet.get("resume_condition")})
    for capability, status in (packet.get("capability_statuses") or {}).items():
        if isinstance(status, dict) and status.get("available") is False:
            gaps.append({"source": f"capability:{capability}", "text": status.get("reason"), "next_action": status.get("resume_condition")})
    for decision in decisions:
        judgment = _judgment(decision)
        for gap in judgment.get("gaps", []):
            gaps.append({"source": f"decision:{decision.get('id')}", "text": gap})
        assessment = decision.get("assessment") if isinstance(decision.get("assessment"), dict) else {}
        for gap in assessment.get("material_gaps", []):
            if isinstance(gap, dict):
                gaps.append({"source": "assessment", "text": gap.get("reason"), "next_action": gap.get("next_action")})
    for failure in failures:
        if failure.get("resolution_status") == "open":
            gaps.append({"source": f"failure:{failure.get('failure_id')}", "text": failure.get("observable_failure"), "next_action": "resolve or explicitly scope away from this related failure"})
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    for gap in gaps:
        text = gap.get("text")
        if not text:
            continue
        key = (str(text), str(gap.get("next_action")))
        current = merged.setdefault(key, {
            "sources": [],
            "text": text,
            "next_action": gap.get("next_action"),
        })
        source = gap.get("source")
        if source and source not in current["sources"]:
            current["sources"].append(source)
    return list(merged.values())


def _actions(packet: dict[str, Any], decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    packet_action = packet.get("next_action")
    if isinstance(packet_action, dict):
        actions.append({
            "source": "task",
            "action_id": packet_action.get("action_id"),
            "executable": packet_action.get("executable"),
            "reason": packet_action.get("reason"),
            "resume_condition": packet_action.get("resume_condition"),
            "expected_outputs": packet_action.get("expected_outputs", []),
        })
    for decision in decisions:
        judgment = _judgment(decision)
        action = judgment.get("next_action")
        if isinstance(action, dict) and action:
            actions.append({"source": f"decision:{decision.get('id')}", **copy.deepcopy(action)})
    return actions


def _commands(project_root: Path, task_id: str, decision_ids: list[str],
              decisions: list[dict[str, Any]] | None = None) -> list[str]:
    # The project root is already present in the CLI invocation.  Keeping the
    # placeholder here prevents repeated long private paths from consuming the
    # default recovery budget; callers substitute the displayed project root.
    commands = [
        f'python mining_kernel.py show --project-root "<project-root>" --record-id {task_id} --section packet',
    ]
    if decision_ids:
        by_id = {item.get("id"): item for item in decisions or []}
        decision = by_id.get(decision_ids[0], {})
        commands.append(
            f'python mining_kernel.py show --project-root "<project-root>" --record-id {decision_ids[0]} '
            f'--revision {decision.get("revision")} --section judgment'
        )
    return commands


def _serialized_size(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, indent=2))


def _compact_action(action: dict[str, Any], limit: int = 520) -> dict[str, Any]:
    result = {"source": action.get("source")}
    for key in ("action_id", "action", "method", "executable", "reason", "resume_condition", "expected_outputs"):
        if key in action and action.get(key) not in (None, [], ""):
            if key == "method":
                result[key] = _preview(action[key], 180)
                if len(str(action[key])) > 180:
                    result["method_full_available"] = True
            else:
                result[key] = action[key]
    for key in ("statement", "stop_if"):
        if key in action and action.get(key):
            result[key] = _preview(action[key], limit)
            if len(str(action[key])) > limit:
                result[f"{key}_full_available"] = True
    return result


def _overflow_view(
    full: dict[str, Any],
    task_id: str,
    question: str,
    version_scope: dict[str, Any],
    judgments: list[dict[str, Any]],
    attempts: dict[str, Any],
    gaps: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    citations: dict[str, Any],
    commands: list[str],
    selection: dict[str, Any],
    max_chars: int,
) -> dict[str, Any]:
    # The final budget object is part of the serialized payload.  Reserve a
    # small fixed margin while choosing reductions so a view that fits before
    # budget fields are attached cannot become an error afterwards.
    fit_limit = max(1000, max_chars - 220)
    compact_judgments = []
    for item in judgments:
        summary = item.get("summary", "")
        compact_judgments.append({
            "decision_id": item.get("decision_id"),
            "revision": item.get("revision"),
            "status": item.get("status"),
            "summary": _preview(summary, 620),
            "gap_count": len(item.get("gaps", [])),
        })
    compact_materials = []
    for item in version_scope.get("materials", []):
        compact_materials.append({
            "asset_id": item.get("asset_id"),
            "revision": item.get("revision"),
            "path": _preview(item.get("path", ""), 90),
            "hash_prefix": str(item.get("content_sha256") or "")[:12],
            "content_status": item.get("content_status"),
            "reading_status": item.get("reading_status"),
            "verification_status": item.get("verification_status"),
        })
    compact_gaps = []
    for item in gaps:
        text = str(item.get("text", ""))
        source_kinds = []
        for source in item.get("sources", []):
            if source in {"material", "assessment"}:
                kind = "material"
            elif str(source).startswith("decision:"):
                kind = "decision"
            elif str(source).startswith("failure:"):
                kind = "failure"
            elif str(source).startswith("capability:"):
                kind = "capability"
            else:
                kind = str(source)
            if kind not in source_kinds:
                source_kinds.append(kind)
        compact_gaps.append(_preview(text, 80))
    compact_attempts = {
        "routes": [
            {key: route.get(key) for key in ("id", "revision", "status", "runs_used", "stop_reason") if route.get(key) is not None}
            for route in attempts.get("routes", [])
        ],
        "related_failures": [
            {key: failure.get(key) for key in ("failure_id", "status", "severity", "resolution_status", "observable_failure") if failure.get(key) is not None}
            for failure in attempts.get("related_failures", [])
        ],
    }
    current_ids = selection.get("current_ids", [])
    history_ids = selection.get("history_ids", [])
    conflict_ids = selection.get("conflict_ids", [])
    selection_view: dict[str, Any] = {
        "reason": selection.get("reason"),
        "current_decision_ids": current_ids,
        "historical_decision_count": len(history_ids),
        "historical_decision_ids": history_ids,
        "inherited_decisions": [{"decision_id": item.get("id"), "revision": item.get("revision"),
                                  "state": "inherited_pending"} for item in selection.get("inherited", [])],
    }
    if conflict_ids:
        selection_view["unresolved_conflict"] = {
            "decision_ids": conflict_ids,
            "reason": "Multiple same-task current branches are not related by an explicit inheritance reference.",
        }
    view = {
        "schema_version": 1,
        "type": "TaskResumeView",
        "view_version": 1,
        "project_id": full.get("project_id"),
        "task_id": task_id,
        "task_revision": full.get("task_revision"),
        "state": full.get("state"),
        "question": question,
        "version_scope": {
            "task_context": version_scope.get("task_context"),
            "maturity": version_scope.get("maturity"),
            "materials": compact_materials,
            "source_bytes_reopened": False,
        },
        "judgments": compact_judgments,
        "inherited_judgments": [
            {"decision_id": item.get("decision_id"), "revision": item.get("revision"),
             "status": item.get("status"), "summary": _preview(item.get("summary", ""), 360),
             "scope": "historical parent judgment; applicability remains bounded by recorded gaps",
             "gap_count": len(item.get("gaps", [])),
             "gap_preview": [_preview(gap, 100) for gap in item.get("gaps", [])[:2]],
             "state": "inherited_pending"}
            for item in full.get("inherited_judgments", [])
        ],
        "judgment_selection": selection_view,
        "attempts_and_stops": compact_attempts,
        "gaps": {"count": len(gaps), "items": compact_gaps, "full_available": True},
        "candidate_actions": [
            ({
                "source": action.get("source"),
                "action": action.get("action"),
                "statement": _preview(action.get("statement", ""), 220),
                "stop_if": _preview(action.get("stop_if", ""), 60),
            } if str(action.get("source", "")).startswith("decision:") else _compact_action(action, 360))
            for action in actions
        ],
        "citations": {
            "question_id": citations.get("question_id"),
            "decision_ids": citations.get("decision_ids", []),
            "material_count": len(version_scope.get("materials", [])),
        },
        "expansion_commands": commands,
        "overflow": {
            "occurred": True,
            "full_detail_available_via_show": True,
            "reason": "Repeated fields were compressed; judgments, limits and next actions remain visible. Use show for full detail.",
            "remaining": {
                "historical_judgments": len(history_ids),
                "materials": len(version_scope.get("materials", [])),
                "gaps": len(gaps),
            },
            "expansion_commands": commands,
        },
    }
    # Keep the research meaning before optional detail.  These reductions are
    # mechanical and never remove the judgment summary or all key gaps.
    if _serialized_size(view) > fit_limit:
        view["version_scope"]["materials"] = [
            {key: item.get(key) for key in ("asset_id", "revision", "path", "content_status", "reading_status", "verification_status")}
            for item in compact_materials
        ]
        view["citations"] = {
            "question_id": citations.get("question_id"),
            "decision_ids": citations.get("decision_ids", []),
            "material_count": len(version_scope.get("materials", [])),
        }
    if _serialized_size(view) > fit_limit:
        view["attempts_and_stops"]["related_failures"] = [
            {key: failure.get(key) for key in ("failure_id", "status", "severity", "resolution_status") if failure.get(key) is not None}
            for failure in attempts.get("related_failures", [])
        ]
        view["gaps"]["items"] = [
            _preview(item.get("text", ""), 80) for item in gaps
        ]
    if _serialized_size(view) > fit_limit:
        view["version_scope"]["materials"] = {
            "count": len(version_scope.get("materials", [])),
            "statuses": sorted({
                f"{item.get('reading_status')}|{item.get('verification_status')}|{item.get('content_status')}"
                for item in version_scope.get("materials", [])
            }),
            "details_available": True,
        }
        view["citations"]["material_detail_command"] = commands[0] if commands else None
    if _serialized_size(view) > fit_limit:
        # Final deterministic fallback: preserve the research handoff fields
        # and exact pointers, while discarding repeated rows and verbose
        # diagnostics.  This path must still return a usable view, never an
        # instruction to inspect source code or an opaque error.
        current_judgments = []
        judgment_preview_limit = 260 if len(compact_judgments) > 1 else 520
        for item in compact_judgments[:4]:
            current_judgments.append({
                "decision_id": item.get("decision_id"),
                "revision": item.get("revision"),
                "status": item.get("status"),
                "summary": _preview(item.get("summary", ""), judgment_preview_limit),
                "gap_count": item.get("gap_count", 0),
            })
        first_gap = compact_gaps[:5]
        if len(compact_gaps) > len(first_gap):
            first_gap.append(f"[overflow] {len(compact_gaps) - len(first_gap)} further limitations; use show expansion")
        action_candidates = [
            action for action in actions
            if str(action.get("source", "")).startswith("decision:")
        ] or actions
        view = {
            "schema_version": 1,
            "type": "TaskResumeView",
            "view_version": 1,
            "project_id": full.get("project_id"),
            "task_id": task_id,
            "task_revision": full.get("task_revision"),
            "state": full.get("state"),
            "question": question,
            "version_scope": {
                "task_context": version_scope.get("task_context"),
                "maturity": version_scope.get("maturity"),
                "materials": {
                    "count": len(version_scope.get("materials", [])),
                    "statuses": sorted({
                        f"{item.get('reading_status')}|{item.get('verification_status')}|{item.get('content_status')}"
                        for item in version_scope.get("materials", [])
                    }),
                    "details_available": True,
                },
                "source_bytes_reopened": False,
            },
            "judgments": current_judgments,
            "inherited_judgments": [
                {"decision_id": item.get("decision_id"), "revision": item.get("revision"),
                 "status": item.get("status"), "summary": _preview(item.get("summary", ""), 180),
             "scope": "historical parent judgment",
             "gap_count": len(item.get("gaps", [])),
             "gap_preview": [_preview(gap, 55) for gap in item.get("gaps", [])[:1]],
                 "state": "inherited_pending"}
                for item in full.get("inherited_judgments", [])[:1]
            ],
            "judgment_selection": selection_view,
            "gaps": {"count": len(gaps), "items": first_gap, "full_available": True},
            "candidate_actions": [
                _compact_action(action, 230) for action in action_candidates[:1]
            ],
            "citations": {
                "question_id": citations.get("question_id"),
                "decision_ids": citations.get("decision_ids", []),
                "material_count": len(version_scope.get("materials", [])),
                "material_detail_command": commands[0] if commands else None,
            },
            "expansion_commands": commands,
            "overflow": {
                "occurred": True,
                "full_detail_available_via_show": True,
                "reason": "Repeated material/history/detail fields were compressed; current judgment, limitations and next action remain visible.",
                "remaining": {
                    "historical_judgments": len(history_ids),
                    "materials": len(version_scope.get("materials", [])),
                    "gaps": max(0, len(gaps) - len(first_gap)),
                    "candidate_actions": max(0, len(action_candidates) - 1),
                    "current_judgments": max(0, len(compact_judgments) - len(current_judgments)),
                },
            },
        }
    return view


def _apply_budget(view: dict[str, Any], max_chars: int, *, overflow: bool) -> dict[str, Any]:
    view["budget"] = {"max_default_unicode_chars": max_chars, "overflow": overflow}
    previous = None
    for _ in range(32):
        used = _serialized_size(view)
        view["budget"]["used_unicode_chars"] = used
        if used == previous:
            break
        previous = used
    return view


def resume_task(project_root: str | Path, task_id: str, *, max_chars: int = DEFAULT_MAX_CHARS) -> dict[str, Any]:
    """Return a compact, read-only continuation view for one persisted task."""
    if not isinstance(max_chars, int) or isinstance(max_chars, bool) or max_chars < 1000:
        raise ValueError("max_chars must be an integer >= 1000")
    root = Path(project_root).expanduser().resolve()
    store = ResearchStore(root)
    task = store.latest_record(task_id, "TaskState")
    if task is None:
        raise ValueError(f"unknown task: {task_id}")
    latest = _latest_records(store)
    packet = task.get("packet", {})
    if not isinstance(packet, dict):
        raise ValueError("TaskState packet must be an object")
    question, question_id, routes = _question_and_routes(latest, packet)
    route_ids = [item["id"] for item in routes]
    related_decisions = _decision_records(latest, task_id, packet, route_ids)
    inherited = _continuation_parent(store, task_id, packet) if is_research_review_continuation(packet) else None
    bound_current = _decision_bound_to_task_state(store, task)
    exact = [record for record in (inherited, bound_current) if record is not None]
    related_decisions = _decision_records(latest, task_id, packet, route_ids, exact_decisions=exact)
    selection = _decision_selection(related_decisions, task_id, packet,
                                    [inherited] if inherited and not packet.get("review_record_ref") else None)
    current_decisions = selection["current"]
    materials = _material_versions(latest, packet, related_decisions)
    failures = _related_failures(latest, task_id, route_ids)
    gaps = _gap_items(packet, current_decisions, failures)
    actions = _actions(packet, current_decisions)
    decision_ids = [item.get("id") for item in related_decisions if isinstance(item.get("id"), str)]
    citations = {
        "question_id": question_id,
        "decision_ids": decision_ids,
        "material_refs": [
            {"asset_id": item.get("asset_id"), "path": item.get("path"), "evidence_refs": packet_material.get("evidence_refs", [])}
            for item in materials
            for packet_material in packet.get("material_reads", [])
            if isinstance(packet_material, dict) and packet_material.get("asset_id") == item.get("asset_id")
        ],
    }
    version_scope = {
        "task_context": packet.get("task_context"),
        "maturity": packet.get("maturity"),
        "workflow_id": packet.get("workflow_id"),
        "materials": materials,
        "note": "Material status is from persisted records; this view does not re-read or re-hash source bytes.",
    }
    attempts = {"routes": routes, "related_failures": failures}
    judgments = _judgment_summaries(current_decisions)
    # Expansion is for the current branch, not whichever related Decision was
    # encountered first in the transaction stream.  Historical IDs remain in
    # citations/selection and can be queried explicitly when needed.
    commands = _commands(root, task_id, selection.get("current_ids", [])
                          or [item.get("id") for item in selection.get("inherited", [])], related_decisions)
    full = {
        "schema_version": 1,
        "type": "TaskResumeView",
        "view_version": 1,
        "project_id": store.project_id,
        "task_id": task_id,
        "task_revision": task.get("revision"),
        "state": task.get("state"),
        "question": question,
        "question_id": question_id,
        "version_scope": version_scope,
        "judgments": judgments,
        **({"inherited_judgments": _judgment_summaries(selection.get("inherited", []))}
           if selection.get("inherited") else {}),
        "judgment_selection": {
            "reason": selection.get("reason"),
            "current_decision_ids": selection.get("current_ids", []),
            "historical_decision_count": len(selection.get("history_ids", [])),
            "historical_decision_ids": selection.get("history_ids", []),
            **({"inherited_decisions": [{"decision_id": item.get("id"), "revision": item.get("revision"),
                                         "state": "inherited_pending"}
                                        for item in selection.get("inherited", [])]}
               if selection.get("inherited") else {}),
            **({
                "unresolved_conflict": {
                    "decision_ids": selection.get("conflict_ids", []),
                    "reason": "Multiple same-task current branches are not related by an explicit inheritance reference.",
                }
            } if selection.get("conflict_ids") else {}),
        },
        "attempts_and_stops": attempts,
        "gaps": gaps,
        "candidate_actions": actions,
        "citations": citations,
        "expansion_commands": commands,
        "budget": {"max_default_unicode_chars": max_chars},
    }
    full_size = _serialized_size(full)
    if full_size <= max_chars:
        complete = _apply_budget(full, max_chars, overflow=False)
        if complete["budget"]["used_unicode_chars"] <= max_chars:
            return complete
    view = _overflow_view(
        full, task_id, question, version_scope, judgments, attempts, gaps,
        actions, citations, commands, selection, max_chars,
    )
    if _serialized_size(view) > max_chars:
        # At the 1000-character floor retain the state distinction and exact
        # revision pointer first; all larger detail remains available through
        # the command carried in this compact view.
        inherited_summaries = full.get("inherited_judgments", [])
        compact_inherited = [{
            "decision_id": item.get("decision_id"), "revision": item.get("revision"),
            "state": "inherited_pending", "summary": _preview(item.get("summary", ""), 35),
            "scope": "historical parent judgment",
            "gap_count": len(item.get("gaps", [])),
            "gap_preview": [_preview(gap, 30) for gap in item.get("gaps", [])[:1]],
        } for item in inherited_summaries[:1]]
        compact_current = [{key: ( _preview(item.get(key, ""), 100) if key == "summary" else item.get(key))
                            for key in ("decision_id", "revision", "status", "summary") if item.get(key) is not None}
                           for item in judgments[:1]]
        expand = (commands[1:2] if len(commands) > 1 else commands[:1])
        view = {
            "schema_version": 1,
            "type": "TaskResumeView",
            "task_id": task_id,
            "state": task.get("state"),
            "judgments": compact_current,
            "inherited_judgments": compact_inherited,
            "judgment_selection": {
                "reason": selection.get("reason"),
                "current_decision_ids": selection.get("current_ids", []),
                **({"unresolved_conflict": {"decision_ids": selection.get("conflict_ids", [])}}
                   if selection.get("conflict_ids") else {}),
            },
            "expansion_commands": expand,
        }
    view = _apply_budget(view, max_chars, overflow=True)
    if view["budget"]["used_unicode_chars"] > max_chars:
        raise ValueError("compact resume view internal priority fallback exceeded max_chars")
    return view


def show_record(
    project_root: str | Path,
    record_id: str,
    *,
    section: str | None = None,
    revision: int | None = None,
) -> dict[str, Any]:
    """Return one persisted record or a selected section without side effects."""
    root = Path(project_root).expanduser().resolve()
    store = ResearchStore(root)
    if revision is not None and (not isinstance(revision, int) or isinstance(revision, bool) or revision <= 0):
        raise ValueError("revision must be a positive integer")
    record = store.latest_record(record_id) if revision is None else _record_revision(store, record_id, revision)
    if record is None:
        if revision is not None:
            raise ValueError(f"unknown record revision: {record_id}@{revision}")
        raise ValueError(f"unknown record: {record_id}")
    if section is None:
        payload: Any = record
    else:
        payload = record
        for part in section.split("."):
            if not isinstance(payload, dict) or part not in payload:
                raise ValueError(f"record {record_id} has no section: {section}")
            payload = payload[part]
    return {
        "schema_version": 1,
        "type": "OnDemandRecordView",
        "record_id": record_id,
        "record_type": record.get("type"),
        "revision": record.get("revision"),
        "section": section or "record",
        "record": copy.deepcopy(payload),
        "read_only": True,
    }
