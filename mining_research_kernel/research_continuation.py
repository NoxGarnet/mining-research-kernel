"""Explicit continuation of one durable research question across source tasks."""
from __future__ import annotations

import copy
from typing import Any

from mining_research_kernel.records import ResearchStore, ResearchStoreError
from mining_research_kernel.source_review import start_source_review
from mining_research_kernel.literature_comparison import start_literature_comparison
from mining_research_kernel.r2_workflow import _id


def _revision(store: ResearchStore, record_id: str, revision: int, kind: str) -> dict[str, Any]:
    for transaction in store.list_transactions():
        for record in transaction.get("records", []):
            if record.get("id") == record_id and record.get("revision") == revision and record.get("type") == kind:
                return copy.deepcopy(record)
    raise ValueError(f"missing {kind} revision {record_id}@{revision}")


def _task(store: ResearchStore, task_id: str) -> dict[str, Any]:
    result = store.latest_record(task_id, "TaskState")
    if result is None:
        raise ValueError(f"unknown task: {task_id}")
    return result


def _decision_for_state(store: ResearchStore, state: dict[str, Any]) -> dict[str, Any] | None:
    packet = state.get("packet", {})
    decision_id = packet.get("review_record_ref")
    if not isinstance(decision_id, str):
        operation_results = state.get("operation_results", {})
        decision_id = next((item.get("decision_id") for item in operation_results.values()
                            if isinstance(item, dict) and item.get("status") == "recorded"), None)
    if not isinstance(decision_id, str):
        return None
    for transaction in store.list_transactions():
        state_match = any(record.get("type") == "TaskState" and record.get("id") == state.get("id")
                          and record.get("revision") == state.get("revision") for record in transaction.get("records", []))
        if not state_match:
            continue
        decision = next((record for record in transaction.get("records", [])
                         if record.get("type") == "Decision" and record.get("id") == decision_id), None)
        if decision:
            return copy.deepcopy(decision)
    # A later Decision revision may be present; find the one explicitly paired
    # with this exact TaskState revision, never substitute the latest revision.
    return None


def _task_question(store: ResearchStore, task_id: str, packet: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    route_ids = packet.get("routes")
    route_id = route_ids[0] if isinstance(route_ids, list) and len(route_ids) == 1 else f"{task_id}.route.1"
    route = store.latest_record(route_id, "Route")
    if route is None or route.get("task_id") != task_id:
        raise ValueError("task Route is missing or belongs to a different task")
    question_id = (route or {}).get("research_question_id") or (route or {}).get("question_id")
    packet_question_id = packet.get("input", {}).get("research_question_id")
    if packet_question_id is not None and packet_question_id != question_id:
        raise ValueError("TaskPacket ResearchQuestion does not match its persisted Route")
    if not isinstance(question_id, str):
        raise ValueError("task has no ResearchQuestion route")
    question = store.latest_record(question_id, "ResearchQuestion")
    if question is None or question.get("project_id") != store.project_id:
        raise ValueError("task ResearchQuestion is missing or belongs to another project")
    return route, question


def _route_target_at_creation(store: ResearchStore, route: dict[str, Any], relation: str,
                              record_type: str) -> dict[str, Any]:
    for transaction in store.list_transactions():
        for edge in transaction.get("relationships", []):
            if edge.get("relation") == relation and edge.get("from_id") == route.get("id"):
                return _revision(store, edge.get("to_id"), edge.get("to_revision"), record_type)
    raise ValueError(f"Route has no {relation} relationship")


def _result(started: dict[str, Any], question_id: str) -> dict[str, Any]:
    return {**started, "question_id": question_id}


def _route_question_id(store: ResearchStore, task_id: str) -> str:
    state = store.latest_record(task_id, "TaskState")
    packet = state.get("packet", {}) if state else {}
    route_ids = packet.get("routes")
    route_id = route_ids[0] if isinstance(route_ids, list) and len(route_ids) == 1 else f"{task_id}.route.1"
    route = store.latest_record(route_id, "Route")
    if route is None or route.get("task_id") != task_id:
        raise ValueError("task Route is missing or belongs to a different task")
    question_id = (route or {}).get("research_question_id") or (route or {}).get("question_id")
    if not isinstance(question_id, str):
        raise ValueError("task Route has no ResearchQuestion reference")
    question = store.latest_record(question_id, "ResearchQuestion")
    if question is None or question.get("project_id") != store.project_id:
        raise ValueError("task Route references an invalid ResearchQuestion")
    return question_id


def begin_research(project_root, *, task_id: str, question: str, asset_refs: list[str],
                   mode="literature", dimensions=None, task_context="production") -> dict[str, Any]:
    task_id = _id(task_id, "task_id")
    if not isinstance(question, str) or not question.strip():
        raise ValueError("question must be non-empty")
    if mode not in {"literature", "sources", "combined_sources"}:
        raise ValueError("mode must be literature or sources")
    review_mode = "literature_comparison" if mode == "literature" else "selected_sources"
    starter = start_literature_comparison if review_mode == "literature_comparison" else start_source_review
    kwargs = {"_research_tracking": True}
    if review_mode == "literature_comparison":
        kwargs["dimensions"] = dimensions
    else:
        kwargs["review_mode"] = review_mode
    started = starter(project_root, task_id=task_id, question=question,
                      asset_refs=asset_refs, task_context=task_context, **kwargs)
    return _result(started, _route_question_id(ResearchStore(project_root), task_id))


def continue_research(project_root, *, task_id: str, from_task_id: str,
                      asset_refs: list[str] | None = None, reason: str | None = None) -> dict[str, Any]:
    task_id, from_task_id = _id(task_id, "task_id"), _id(from_task_id, "from_task_id")
    if reason is not None and (not isinstance(reason, str) or not reason.strip() or len(reason) > 1000):
        raise ValueError("reason must be non-empty text up to 1000 characters")
    store = ResearchStore(project_root)
    parent = _task(store, from_task_id)
    parent_packet = parent.get("packet", {})
    route, question = _task_question(store, from_task_id, parent_packet)
    question_text = question.get("statement")
    if not isinstance(question_text, str) or not question_text:
        raise ValueError("ResearchQuestion statement is invalid")
    existing = store.latest_record(task_id, "TaskState")
    if existing:
        stored = existing.get("packet", {}).get("input", {}).get("research_continuation")
        if (not isinstance(stored, dict) or stored.get("previous_task_id") != from_task_id
                or stored.get("question_id") != question["id"] or stored.get("reason") != reason):
            raise ValueError("task_id already exists with a different continuation request")
        selected_assets = list(existing.get("packet", {}).get("asset_refs", []))
        if asset_refs is not None and list(asset_refs) != selected_assets:
            raise ValueError("task_id already exists with different selected Assets")
        replay_context = {"question_record": question, "continuation": copy.deepcopy(stored),
                          "expected_revisions": {}, "previous_route_id": (route or {}).get("id")}
        mode = existing["packet"].get("input", {}).get("review_mode", "combined_sources")
        dimensions = existing["packet"].get("input", {}).get("dimensions")
        if mode == "literature_comparison":
            started = start_literature_comparison(project_root, task_id=task_id, question=question_text,
                                                  asset_refs=selected_assets,
                                                  task_context=existing["packet"].get("task_context", "production"),
                                                  dimensions=dimensions, _continuation=replay_context)
        elif mode in {"combined_sources", "selected_sources"}:
            started = start_source_review(project_root, task_id=task_id, question=question_text,
                                          asset_refs=selected_assets,
                                          task_context=existing["packet"].get("task_context", "production"),
                                          review_mode=mode, dimensions=dimensions, _continuation=replay_context)
        else:
            raise ValueError("stored continuation has an unsupported review mode")
        return _result(started, question["id"])
    original_question = _route_target_at_creation(store, route, "route_addresses_question", "ResearchQuestion")
    if original_question.get("statement") != question_text:
        raise ValueError("ResearchQuestion statement changed after the base task; begin a new question")
    claim = _route_target_at_creation(store, route, "route_targets_claim", "Claim")
    if (not claim or claim.get("statement") != f"Evidence synthesis addressing: {original_question['statement']}"):
        raise ValueError("base task claim does not match its original ResearchQuestion")
    parent_review_question = parent_packet.get("input", {}).get("review_question")
    if parent_review_question is not None and parent_review_question != original_question["statement"]:
        raise ValueError("base task review question does not match its original ResearchQuestion")
    comparison = (prior_decision := _decision_for_state(store, parent))
    comparison = comparison.get("assessment", {}).get("literature_comparison") if comparison else None
    if isinstance(comparison, dict) and comparison.get("question") != original_question["statement"]:
        raise ValueError("base Decision addresses a different ResearchQuestion; begin a new question")
    prior_decision_id = parent_packet.get("review_record_ref")
    if not isinstance(prior_decision_id, str):
        operation = parent.get("operation_results", {})
        prior_decision_id = next((value.get("decision_id") for value in operation.values()
                                  if isinstance(value, dict) and value.get("status") == "recorded"), None)
    if not isinstance(prior_decision_id, str):
        raise ValueError("previous task has no completed Decision")
    prior_decision = _decision_for_state(store, parent)
    if (parent.get("state") != "completed" or prior_decision is None
            or prior_decision.get("id") != prior_decision_id
            or prior_decision.get("judgment", {}).get("status") not in {"PROVISIONAL_WITH_GAPS", "INSUFFICIENT"}):
        raise ValueError("continuation requires a completed task with an actual incomplete Decision")
    decision = prior_decision
    continuation = {
        "question_id": question["id"], "previous_task_id": from_task_id,
        "previous_task_revision": parent["revision"], "previous_decision_id": decision["id"],
        "previous_decision_revision": decision["revision"], "reason": reason,
    }
    selected_assets = list(parent_packet.get("asset_refs", [])) if asset_refs is None else asset_refs
    if not isinstance(selected_assets, list) or not selected_assets:
        raise ValueError("continuation requires an explicit or inherited non-empty asset set")
    # A pre-existing exact replay is handled before revision freshness checks, so
    # later parent revisions cannot make replay mutate or invalidate its packet.
    expected = {from_task_id: parent["revision"], decision["id"]: decision["revision"]}
    if route is not None:
        expected[route["id"]] = route["revision"]
    context = {"question_record": question, "continuation": continuation,
               "expected_revisions": expected, "previous_route_id": (route or {}).get("id")}
    # Pre-comparison #7 research-start tasks used combined paper+documentation
    # reviews and did not persist review_mode. Only literature-start stored it.
    mode = parent_packet.get("input", {}).get("review_mode", "combined_sources")
    if mode not in {"literature_comparison", "combined_sources", "selected_sources"}:
        raise ValueError("previous task is not a compatible source review")
    dimensions = parent_packet.get("input", {}).get("dimensions")
    if mode == "literature_comparison":
        started = start_literature_comparison(project_root, task_id=task_id, question=question_text,
                                              asset_refs=selected_assets, task_context=parent_packet.get("task_context", "production"),
                                              dimensions=dimensions, _continuation=context)
    else:
        started = start_source_review(project_root, task_id=task_id, question=question_text,
                                      asset_refs=selected_assets,
                                      task_context=parent_packet.get("task_context", "production"),
                                      review_mode=mode, dimensions=dimensions, _continuation=context)
    return _result(started, question["id"])


def research_progress(project_root, *, task_id: str) -> dict[str, Any]:
    store = ResearchStore(project_root)
    cursor = _id(task_id, "task_id")
    newest_first = []
    visited = set()
    current_task = None
    question = None
    expected_task_revision = None
    for _ in range(100):
        state_task_id = cursor
        if cursor in visited:
            raise ValueError("continuation chain contains a cycle")
        visited.add(cursor)
        state = (_task(store, cursor) if expected_task_revision is None else
                 _revision(store, cursor, expected_task_revision, "TaskState"))
        packet = state.get("packet", {})
        route, found_question = _task_question(store, cursor, packet)
        if question is None:
            question = found_question
            current_task = {"task_id": cursor, "task_revision": state["revision"], "state": state["state"]}
        elif found_question["id"] != question["id"]:
            raise ValueError("continuation chain crosses ResearchQuestions")
        continuation = packet.get("input", {}).get("research_continuation")
        decision_id = packet.get("review_record_ref")
        decision = _decision_for_state(store, state)
        if continuation:
            previous_id = continuation.get("previous_task_id")
            previous_revision = continuation.get("previous_task_revision")
            previous_decision_id = continuation.get("previous_decision_id")
            previous_decision_revision = continuation.get("previous_decision_revision")
            if not all(isinstance(x, str) for x in (previous_id, previous_decision_id)):
                raise ValueError("continuation link is malformed")
            if continuation.get("question_id") != question["id"]:
                raise ValueError("continuation link targets a different ResearchQuestion")
            prev_state = _revision(store, previous_id, previous_revision, "TaskState")
            bound_decision = _revision(store, previous_decision_id, previous_decision_revision, "Decision")
            paired_decision = _decision_for_state(store, prev_state)
            if (prev_state.get("packet", {}).get("review_record_ref") != previous_decision_id
                    or prev_state.get("state") != "completed" or paired_decision != bound_decision):
                raise ValueError("continuation previous Decision is not bound to previous task")
            prev_route, prev_question = _task_question(store, previous_id, prev_state.get("packet", {}))
            if (prev_question["id"] != question["id"] or not route
                    or route.get("parent_route_id") != prev_route.get("id")):
                raise ValueError("continuation Route parent does not match its previous task and question")
            parent_edge_found = any(
                edge.get("relation") == "route_child_of_route"
                and edge.get("from_id") == route.get("id")
                and edge.get("to_id") == prev_route.get("id")
                for tx in store.list_transactions() for edge in tx.get("relationships", [])
            )
            if not parent_edge_found:
                raise ValueError("continuation Route is missing its route_child_of_route relationship")
            if previous_id not in visited:
                cursor = previous_id
                expected_task_revision = previous_revision
            else:
                raise ValueError("continuation chain contains a cycle")
        elif route and route.get("parent_route_id"):
            raise ValueError("route parent exists without a continuation link")
        refs = packet.get("refs", {})
        newest_first.append({"task_id": state_task_id,
                             "task_revision": state["revision"], "state": state["state"],
                             "decision_id": decision_id,
                             "decision_revision": decision.get("revision") if decision else None,
                             "judgment": copy.deepcopy(decision.get("judgment")) if decision else None,
                             "source_bindings": copy.deepcopy(packet.get("input", {}).get("source_bindings", [])),
                             "asset_refs": copy.deepcopy(packet.get("asset_refs", [])),
                             "evidence_refs": copy.deepcopy(packet.get("evidence_refs", [])),
                             "continuation": copy.deepcopy(continuation)})
        if not continuation:
            break
    else:
        raise ValueError("continuation chain exceeds 100 tasks")
    return {"question_id": question["id"], "question": question["statement"], "task_id": task_id,
            "steps": list(reversed(newest_first)), "current_task": current_task,
            "source_queries_performed": False, "verification_run": False,
            "completion_decision": "user_owned"}
