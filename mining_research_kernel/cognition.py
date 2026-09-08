"""Small, file-native Core Cognition service.

Records are authoritative.  The cognition JSON written by :meth:`rebuild` is
only a deterministic projection and may be deleted and recreated.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .records import ResearchStore, ResearchStoreError


MECHANICAL_KINDS = frozenset({"file_exists", "file_hash", "return_code", "structured_test", "route_state"})
INVALIDATION_KINDS = frozenset({"record_missing", "revision_changed", "content_hash_changed", "explicitly_superseded"})
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
HASH_RE = re.compile(r"[0-9a-f]{64}\Z")
AUTO_PROVISIONAL_FACT_KEYS = {
    "file_exists": frozenset({"exists"}),
    "file_hash": frozenset({"sha256"}),
    "return_code": frozenset({"return_code"}),
    "structured_test": frozenset({"passed"}),
    "route_state": frozenset({"state"}),
}
_NO_MECHANICAL_FACT = object()


class CognitionError(ValueError):
    """Raised when a cognition operation fails closed."""


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or ID_RE.fullmatch(value) is None:
        raise CognitionError(f"{field} must match the project record id format")
    return value


def _nonempty(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CognitionError(f"{field} must be a non-empty string")
    return value.strip()


def _strings(value: Any, field: str, *, allow_empty: bool = True) -> list[str]:
    if value is None:
        value = []
    if not isinstance(value, list) or (not allow_empty and not value):
        raise CognitionError(f"{field} must be a {'non-empty ' if not allow_empty else ''}list")
    if not all(isinstance(item, str) and item.strip() for item in value):
        raise CognitionError(f"{field} must contain non-empty strings")
    return sorted(set(item.strip() for item in value))


def _derived_id(prefix: str, value: str) -> str:
    candidate = f"{prefix}.{value}"
    if len(candidate) <= 64:
        return candidate
    return f"{prefix}.{hashlib.sha256(candidate.encode('utf-8')).hexdigest()[:32]}"


def _json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise CognitionError(f"value is not canonical JSON: {exc}") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def _mechanical_fact_value(observation_kind: Any, observation: Any, fact_key: Any) -> Any:
    """Extract only explicitly allowlisted facts from a mechanical observation."""
    if fact_key not in AUTO_PROVISIONAL_FACT_KEYS.get(observation_kind, ()):
        return _NO_MECHANICAL_FACT
    if observation_kind == "file_exists" and isinstance(observation, bool):
        return observation
    if observation_kind == "file_hash":
        if isinstance(observation, dict):
            return observation.get("sha256", _NO_MECHANICAL_FACT)
        return observation if isinstance(observation, str) else _NO_MECHANICAL_FACT
    if observation_kind == "return_code" and isinstance(observation, int) and not isinstance(observation, bool):
        return observation
    if observation_kind == "structured_test" and isinstance(observation, dict) and isinstance(observation.get("passed"), bool):
        return observation["passed"]
    if observation_kind == "route_state" and isinstance(observation, dict) and isinstance(observation.get("state"), str):
        return observation["state"]
    return _NO_MECHANICAL_FACT


def _evidence_matches_mechanical_fact(latest: dict[str, dict[str, Any]], evidence_id: str,
                                      fact_key: str, fact_value: Any) -> bool:
    evidence = latest.get(evidence_id)
    if not isinstance(evidence, dict) or evidence.get("type") != "Evidence":
        return False
    asset = latest.get(evidence.get("asset_ref"))
    if not isinstance(asset, dict) or asset.get("type") != "Asset":
        return False
    if (evidence.get("evidence_kind") != "mechanical_observation"
            or asset.get("asset_kind") != "mechanical_observation"
            or evidence.get("observation_kind") != asset.get("observation_kind")
            or _digest(evidence.get("observation")) != _digest(asset.get("observation"))):
        return False
    observed = _mechanical_fact_value(evidence.get("observation_kind"), evidence.get("observation"), fact_key)
    return observed is not _NO_MECHANICAL_FACT and _digest(observed) == _digest(fact_value)


class CoreCognition:
    """Admission, invalidation, conflict and failure recovery for one project."""

    def __init__(self, project_root: str | Path, *, review_boundary: Any = None,
                 producer_role: str = "planning_agent", model: str = "core-cognition"):
        self.store = ResearchStore(project_root)
        self.project_root = self.store.project_root
        self.review_boundary = review_boundary
        self.producer = {"role": _nonempty(producer_role, "producer_role"), "model": _nonempty(model, "model")}

    def _transactions(self) -> list[dict[str, Any]]:
        return self.store.list_transactions()

    def _latest(self) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for tx in self._transactions():
            for record in tx["records"]:
                if record["revision"] >= records.get(record["id"], {"revision": 0})["revision"]:
                    records[record["id"]] = record
        return records

    def _history_record(self, record_id: str, revision: int) -> dict[str, Any] | None:
        for tx in self._transactions():
            for record in tx["records"]:
                if record["id"] == record_id and record["revision"] == revision:
                    return record
        return None

    def _operation(self, operation_id: str) -> dict[str, Any] | None:
        for tx in self._transactions():
            if tx["operation_id"] == operation_id:
                return {"operation_id": operation_id, "idempotent": True, "transaction": copy.deepcopy(tx), "records": copy.deepcopy(tx["records"])}
        return None

    def _commit(self, operation_id: str, records: list[dict[str, Any]], relationships: list[dict[str, Any]] | None = None,
                *, expected: dict[str, int] | None = None, producer: dict[str, str] | None = None) -> dict[str, Any]:
        effective_producer = producer or self.producer
        existing = self._operation(operation_id)
        if existing is not None:
            canonical_records = _json(records)
            canonical_relationships = _json(relationships or [])
            transaction = existing["transaction"]
            if (transaction["producer"] != effective_producer
                    or transaction["records"] != canonical_records
                    or transaction["relationships"] != canonical_relationships):
                raise CognitionError(f"conflicting payload for operation_id: {operation_id}")
            return existing
        return {"operation_id": operation_id, "idempotent": False,
                "transaction": self.store.commit(operation_id, effective_producer, records, relationships or [], expected_revisions=expected),
                "records": copy.deepcopy(records)}

    def _edge(self, edge_id: str, relation: str, from_record: dict[str, Any], to_record: dict[str, Any], source: str) -> dict[str, Any]:
        return {"schema_version": 1, "relationship_id": _id(edge_id, "relationship_id"), "revision": 1,
                "project_id": self.store.project_id, "relation": relation,
                "from_id": from_record["id"], "from_revision": from_record["revision"],
                "to_id": to_record["id"], "to_revision": to_record["revision"], "source_refs": [source]}

    def record_mechanical_evidence(self, observation_kind: str, observation: Any, *, operation_id: str,
                                   locator: dict[str, Any] | None = None, scope: dict[str, Any] | None = None,
                                   task_id: str | None = None, route_id: str | None = None, run_id: str | None = None,
                                   content_sha256: str | None = None) -> dict[str, Any]:
        operation_id = _id(operation_id, "operation_id")
        if observation_kind not in MECHANICAL_KINDS:
            raise CognitionError(f"unsupported mechanical observation kind: {observation_kind}")
        if observation_kind == "return_code" and (not isinstance(observation, int) or isinstance(observation, bool)):
            raise CognitionError("return_code observation must be an integer")
        if observation_kind == "file_exists" and not isinstance(observation, bool):
            raise CognitionError("file_exists observation must be boolean")
        if observation_kind == "structured_test" and (
                not isinstance(observation, dict) or not isinstance(observation.get("passed"), bool)):
            raise CognitionError("structured_test observation must contain boolean passed")
        if observation_kind == "route_state" and (
                not isinstance(observation, dict) or not isinstance(observation.get("state"), str)
                or observation["state"] not in {"proposed", "active", "blocked", "completed", "failed", "cannot_verify", "accepted", "rejected", "superseded"}):
            raise CognitionError("route_state observation must contain a known state")
        if observation_kind == "file_hash":
            candidate = observation.get("sha256") if isinstance(observation, dict) else observation
            if not isinstance(candidate, str) or HASH_RE.fullmatch(candidate) is None:
                raise CognitionError("file_hash observation must contain a lowercase sha256")
            content_sha256 = candidate
        if content_sha256 is not None and (not isinstance(content_sha256, str) or HASH_RE.fullmatch(content_sha256) is None):
            raise CognitionError("content_sha256 must be lowercase 64 hex")
        if locator is not None and not isinstance(locator, dict):
            raise CognitionError("locator must be an object")
        for value, field in ((task_id, "task_id"), (route_id, "route_id"), (run_id, "run_id")):
            if value is not None:
                _id(value, field)
        if scope is not None and (not isinstance(scope, dict) or not scope):
            raise CognitionError("scope must be a non-empty object")
        source = f"mechanical:{operation_id}"
        asset_id, evidence_id = _derived_id("asset", operation_id), _derived_id("evidence", operation_id)
        asset = {"schema_version": 1, "type": "Asset", "id": asset_id, "revision": 1, "project_id": self.store.project_id,
                 "scope": _json(scope or {"project_id": self.store.project_id}), "source_refs": [source],
                 "asset_kind": "mechanical_observation", "locator": _json(locator or {"observation_kind": observation_kind}),
                 "content_sha256": content_sha256, "authority": "authoritative", "status": "available",
                 "observation_kind": observation_kind, "observation": _json(observation), "task_id": task_id, "route_id": route_id, "run_id": run_id}
        evidence = {"schema_version": 1, "type": "Evidence", "id": evidence_id, "revision": 1, "project_id": self.store.project_id,
                    "scope": _json(scope or {"project_id": self.store.project_id}), "source_refs": [source],
                    "evidence_kind": "mechanical_observation", "asset_ref": asset_id,
                    "locator": _json(locator or {"observation_kind": observation_kind}), "status": "observed",
                    "observation_kind": observation_kind, "observation": _json(observation), "task_id": task_id, "route_id": route_id, "run_id": run_id}
        result = self._commit(operation_id, [asset, evidence], [self._edge(_derived_id("edge", operation_id), "evidence_derived_from_asset", evidence, asset, source)])
        result["queued_for_review"] = False
        return result

    def _dependencies(self, refs: list[str], supplied: Any, latest: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        values = supplied if supplied is not None else []
        if not isinstance(values, list):
            raise CognitionError("dependencies must be a list")
        dependencies: list[dict[str, Any]] = []
        for item in values:
            if not isinstance(item, dict):
                raise CognitionError("each dependency must be an object")
            record_id = _id(item.get("record_id"), "dependency.record_id")
            record_type = item.get("record_type")
            revision = item.get("revision")
            if not isinstance(record_type, str) or not record_type or not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise CognitionError("dependency requires record_type and revision")
            historical = self._history_record(record_id, revision)
            if historical is None or historical["type"] != record_type:
                raise CognitionError(f"dependency does not identify an existing record: {record_id}@{revision}")
            dep = {"record_id": record_id, "record_type": record_type, "revision": revision}
            if "content_sha256" in item:
                digest = item["content_sha256"]
                if not isinstance(digest, str) or HASH_RE.fullmatch(digest) is None:
                    raise CognitionError("dependency content_sha256 is invalid")
                dep["content_sha256"] = digest
            dependencies.append(dep)
        existing_ids = {(d["record_id"], d["record_type"]) for d in dependencies}
        for ref in refs:
            record = latest.get(ref)
            if record is None or record["type"] != "Evidence":
                raise CognitionError(f"evidence reference is not a current Evidence record: {ref}")
            key = (ref, "Evidence")
            if key not in existing_ids:
                dep = {"record_id": ref, "record_type": "Evidence", "revision": record["revision"]}
                dependencies.append(dep)
                existing_ids.add(key)
            asset = latest.get(record["asset_ref"])
            if asset is not None and (asset["id"], asset["type"]) not in existing_ids:
                dep = {"record_id": asset["id"], "record_type": "Asset", "revision": asset["revision"]}
                if asset.get("content_sha256"):
                    dep["content_sha256"] = asset["content_sha256"]
                dependencies.append(dep)
                existing_ids.add((asset["id"], "Asset"))
        return sorted(dependencies, key=lambda d: (d["record_type"], d["record_id"], d["revision"]))

    def propose(self, proposal: dict[str, Any], operation_id: str) -> dict[str, Any]:
        operation_id = _id(operation_id, "operation_id")
        if not isinstance(proposal, dict):
            raise CognitionError("proposal must be an object")
        latest = self._latest()
        proposal_id = _id(proposal.get("proposal_id", proposal.get("id")), "proposal_id")
        evidence_refs = proposal.get("evidence_refs", [])
        if not isinstance(evidence_refs, list) or not all(isinstance(v, str) for v in evidence_refs):
            raise CognitionError("evidence_refs must be a list of strings")
        evidence_refs = sorted(set(_id(v, "evidence_ref") for v in evidence_refs))
        counterevidence_refs = _strings(proposal.get("counterevidence_refs", []), "counterevidence_refs")
        for ref in counterevidence_refs:
            if latest.get(ref, {}).get("type") != "Evidence":
                raise CognitionError(f"counterevidence reference is not an Evidence record: {ref}")
        proposal_type = proposal.get("proposal_type", "project_lesson")
        requested = proposal.get("requested_status", "proposed")
        impact = proposal.get("impact", "medium")
        if proposal_type not in {"project_lesson", "workflow_rule", "domain_rule", "claim", "supersession", "conflict"}:
            raise CognitionError("proposal_type is invalid")
        if requested not in {"proposed", "provisional", "accepted", "rejected", "contested", "pending_review"}:
            raise CognitionError("requested_status is invalid")
        if impact not in {"low", "medium", "high"}:
            raise CognitionError("impact is invalid")
        statement = proposal.get("statement")
        if not isinstance(statement, str) or not statement.strip():
            raise CognitionError("statement must be non-empty")
        created_by = _nonempty(proposal.get("created_by", "host"), "created_by")
        created_by_role = _nonempty(proposal.get("created_by_role", "agent"), "created_by_role")
        created_model = _nonempty(proposal.get("created_model", "unknown"), "created_model")
        for field in ("task_id", "route_id", "claim_id"):
            if proposal.get(field) is not None:
                _id(proposal[field], field)
        for field in ("object_ref", "scope_key"):
            if proposal.get(field) is not None:
                _nonempty(proposal[field], field)
        scope = proposal.get("scope")
        if not isinstance(scope, dict) or not scope:
            raise CognitionError("scope must be a non-empty object")
        dependencies = self._dependencies(evidence_refs, proposal.get("dependencies"), latest)
        conditions = proposal.get("invalidation_conditions")
        if conditions is None:
            conditions = ["record_missing", "revision_changed"]
            if any("content_sha256" in d for d in dependencies):
                conditions.append("content_hash_changed")
        if not isinstance(conditions, list) or not all(v in INVALIDATION_KINDS for v in conditions):
            raise CognitionError("invalidation_conditions must use only fixed conditions")
        if not {"record_missing", "revision_changed"}.issubset(conditions):
            raise CognitionError("invalidation_conditions must include record_missing and revision_changed")
        if any("content_sha256" in d for d in dependencies) and "content_hash_changed" not in conditions:
            raise CognitionError("content-hash dependencies require content_hash_changed")
        fact_key = proposal.get("fact_key")
        scoped_fact = all(isinstance(proposal.get(field), str) and proposal[field].strip()
                          for field in ("object_ref", "scope_key"))
        if fact_key is not None and (not isinstance(fact_key, str) or not fact_key.strip()):
            raise CognitionError("fact_key must be a non-empty string or null")
        if fact_key is None and "fact_value" in proposal:
            raise CognitionError("fact_value requires a fact_key")
        has_fact_value = isinstance(fact_key, str) and bool(fact_key.strip()) and "fact_value" in proposal
        fact_value = _json(proposal.get("fact_value")) if has_fact_value else None
        for ref in evidence_refs:
            if not latest[ref].get("locator"):
                raise CognitionError(f"evidence has no locator: {ref}")
        review_key = _digest({"proposal_type": proposal_type, "fact_key": fact_key, "fact_value": fact_value,
                              "object_ref": proposal.get("object_ref"), "scope_key": proposal.get("scope_key"),
                              "impact": impact, "evidence_refs": evidence_refs})
        mechanically_supported = (
            scoped_fact and has_fact_value and bool(evidence_refs)
            and proposal_type == "project_lesson" and impact == "low"
            and requested in {"proposed", "provisional"}
            and all(_evidence_matches_mechanical_fact(latest, ref, fact_key, fact_value)
                    for ref in evidence_refs)
        )
        reason = "admitted_as_provisional" if mechanically_supported else "requires_review_or_more_evidence"
        admitted = "provisional" if reason == "admitted_as_provisional" else ("pending_review" if requested in {"accepted", "pending_review"} or impact == "high" or proposal_type == "domain_rule" else "proposed")
        record = {"schema_version": 1, "type": "CognitionProposal", "id": proposal_id, "proposal_id": proposal_id, "revision": 1,
                  "project_id": self.store.project_id, "scope": _json(scope), "source_refs": [f"proposal:{proposal_id}"],
                  "proposal_type": proposal_type, "statement": statement, "evidence_refs": evidence_refs,
                  "counterevidence_refs": counterevidence_refs, "requested_status": requested,
                  "admitted_status": admitted, "current_status": admitted, "created_by": created_by,
                  "created_by_role": created_by_role, "created_model": created_model,
                  "impact": impact, "object_ref": proposal.get("object_ref"), "scope_key": proposal.get("scope_key"),
                  "fact_key": fact_key, "fact_value": fact_value, "dependencies": dependencies, "invalidation_conditions": sorted(set(conditions)),
                  "expiry_conditions": sorted(set(proposal.get("expiry_conditions", []))), "review_key": review_key, "status_reason": reason,
                  "task_id": proposal.get("task_id"), "route_id": proposal.get("route_id"), "claim_id": proposal.get("claim_id")}
        relationships = [self._edge(_derived_id("edge", f"{proposal_id}.evidence.{index}"), "cognition_proposal_uses_evidence", record, latest[ref], f"proposal:{proposal_id}") for index, ref in enumerate(evidence_refs)]
        result = self._commit(operation_id, [record], relationships)
        result["queued_for_review"] = admitted == "pending_review"
        return result

    def _dependency_state(self, proposal: dict[str, Any], latest: dict[str, dict[str, Any]]) -> str | None:
        for dep in proposal.get("dependencies", []):
            current = latest.get(dep["record_id"])
            if current is None or current["type"] != dep["record_type"]:
                if "record_missing" in proposal["invalidation_conditions"]:
                    return "dependency_missing"
            if current is None:
                continue
            if current["revision"] != dep["revision"] and "revision_changed" in proposal["invalidation_conditions"]:
                return "dependency_revision_changed"
            if "content_sha256" in dep and current.get("content_sha256") != dep["content_sha256"] and "content_hash_changed" in proposal["invalidation_conditions"]:
                return "dependency_content_hash_changed"
            if current.get("status") in {"superseded", "rejected"} and "explicitly_superseded" in proposal["invalidation_conditions"]:
                return "dependency_superseded"
        return None

    def review(self, proposal_id: str, operation_id: str, *, review_ref: str, evidence_refs: list[str] | None = None,
               scope: dict[str, Any] | None = None, impact: str | None = None, decision: str = "accept") -> dict[str, Any]:
        proposal_id, operation_id, review_ref = _id(proposal_id, "proposal_id"), _id(operation_id, "operation_id"), _id(review_ref, "review_ref")
        existing = self._operation(operation_id)
        if existing is not None:
            review_record = next((record for record in existing["records"] if record.get("type") == "CognitionReview"), None)
            if (review_record is None or review_record.get("proposal_id") != proposal_id
                    or review_record.get("review_ref") != review_ref
                    or review_record.get("decision") != decision
                    or (impact is not None and review_record.get("impact") != impact)
                    or (scope is not None and review_record.get("scope") != _json(scope))
                    or (evidence_refs is not None and review_record.get("evidence_refs") != _strings(evidence_refs, "review evidence_refs"))):
                raise CognitionError(f"conflicting payload for operation_id: {operation_id}")
            return existing
        if self.review_boundary is None:
            raise CognitionError("accepted cognition requires an injected trusted review boundary")
        proposal = self.store.latest_record(proposal_id, "CognitionProposal")
        if proposal is None:
            raise CognitionError(f"unknown proposal: {proposal_id}")
        refs = _strings(evidence_refs if evidence_refs is not None else proposal["evidence_refs"], "review evidence_refs")
        refs = sorted(set(_id(ref, "review evidence_ref") for ref in refs))
        latest = self._latest()
        if decision == "accept" and not refs:
            raise CognitionError("accepted cognition requires at least one Evidence reference")
        dependency_reason = self._dependency_state(proposal, latest)
        if dependency_reason:
            raise CognitionError(f"proposal cannot be reviewed while stale: {dependency_reason}")
        for ref in refs:
            if latest.get(ref, {}).get("type") != "Evidence":
                raise CognitionError(f"review evidence is not an Evidence record: {ref}")
        if not isinstance(scope or proposal["scope"], dict) or not (scope or proposal["scope"]):
            raise CognitionError("review scope must be a non-empty object")
        impact = impact or proposal["impact"]
        if impact is not None and impact != proposal["impact"]:
            raise CognitionError("review cannot change proposal impact")
        if impact not in {None, "low", "medium", "high"} or decision not in {"accept", "reject", "contested"}:
            raise CognitionError("invalid review decision or impact")
        impact = proposal["impact"]
        request = {"proposal_id": proposal_id, "decision": decision, "scope": scope or proposal["scope"], "impact": impact, "evidence_refs": refs, "review_ref": review_ref}
        if hasattr(self.review_boundary, "authorize"):
            authorization = self.review_boundary.authorize(request)
        elif callable(self.review_boundary):
            authorization = self.review_boundary(request)
        else:
            raise CognitionError("review boundary must be an injected callable or authorize object")
        if not isinstance(authorization, dict) or authorization.get("authorized") is not True or not isinstance(authorization.get("boundary_id"), str) or not authorization["boundary_id"].strip():
            raise CognitionError("review boundary did not authorize this review")
        review_id = _derived_id("review", operation_id)
        updated = copy.deepcopy(proposal)
        updated["revision"] += 1
        updated["admitted_status"] = {"accept": "accepted", "reject": "rejected", "contested": "contested"}[decision]
        updated["current_status"] = updated["admitted_status"]
        updated["status_reason"] = "trusted_boundary_review"
        review_record = {"schema_version": 1, "type": "CognitionReview", "id": review_id, "review_id": review_id, "revision": 1,
                         "project_id": self.store.project_id, "scope": _json(scope or proposal["scope"]), "source_refs": [f"review:{review_ref}"],
                         "proposal_id": proposal_id, "review_ref": review_ref, "decision": decision, "evidence_refs": refs,
                         "impact": impact, "boundary_id": authorization["boundary_id"], "reviewer_label": authorization.get("reviewer_label", "trusted_boundary")}
        relationships = [self._edge(_derived_id("edge", f"{review_id}.proposal"), "cognition_review_reviews_proposal", review_record, updated, f"review:{review_ref}")]
        relationships += [self._edge(_derived_id("edge", f"{review_id}.evidence.{i}"), "cognition_review_uses_evidence", review_record, latest[ref], f"review:{review_ref}") for i, ref in enumerate(refs)]
        review_producer = {"role": "acceptance_agent", "model": _nonempty(
            authorization.get("model", "trusted-review-boundary"), "review model")}
        return self._commit(operation_id, [updated, review_record], relationships,
                            expected={proposal_id: proposal["revision"]}, producer=review_producer)

    def record_failure(self, failure: dict[str, Any], operation_id: str) -> dict[str, Any]:
        operation_id = _id(operation_id, "operation_id")
        if not isinstance(failure, dict):
            raise CognitionError("failure must be an object")
        failure_id = _id(failure.get("failure_id", failure.get("id")), "failure_id")
        observable = failure.get("observable_failure")
        if not isinstance(observable, str) or not observable.strip():
            raise CognitionError("observable_failure must be non-empty")
        source_refs = _strings(failure.get("source_refs") or [f"failure:{failure_id}"], "source_refs", allow_empty=False)
        affected_versions = _strings(failure.get("affected_product_versions", []), "affected_product_versions")
        input_assets = _strings(failure.get("input_assets", []), "input_assets")
        evidence_assets = _strings(failure.get("evidence_assets", []), "evidence_assets")
        object_refs = _strings(failure.get("object_refs", []), "object_refs")
        for value, field in ((failure.get("task_id"), "task_id"), (failure.get("route_id"), "route_id"), (failure.get("run_id"), "run_id")):
            if value is not None:
                _id(value, field)
        scope = failure.get("scope")
        if scope is not None and (not isinstance(scope, dict) or not scope):
            raise CognitionError("failure scope must be a non-empty object")
        record = {"schema_version": 1, "type": "Failure", "id": failure_id, "failure_id": failure_id, "revision": 1,
                  "project_id": self.store.project_id, "scope": _json(scope or {"project_id": self.store.project_id}),
                  "source_refs": source_refs, "status": failure.get("status", "observed"),
                  "observable_failure": observable, "reproduction": _json(failure.get("reproduction", [])),
                  "affected_product_versions": affected_versions, "input_assets": input_assets,
                  "evidence_assets": evidence_assets, "root_cause_status": failure.get("root_cause_status", "unknown"),
                  "resolution_status": failure.get("resolution_status", "open"), "applicability": failure.get("applicability", "project_only"),
                  "object_refs": object_refs, "task_id": failure.get("task_id"), "route_id": failure.get("route_id"),
                  "run_id": failure.get("run_id"), "severity": failure.get("severity", "error"), "affected_scope": _json(failure.get("affected_scope", {}))}
        relationships = []
        latest = self._latest()
        if record["run_id"] and latest.get(record["run_id"], {}).get("type") == "RunReference":
            relationships.append(self._edge(_derived_id("edge", f"{failure_id}.run"), "failure_observed_in_run", record, latest[record["run_id"]], f"failure:{failure_id}"))
        return self._commit(operation_id, [record], relationships)

    def _conflicts(self, proposals: list[dict[str, Any]], relationships: list[dict[str, Any]]) -> set[str]:
        groups: dict[tuple[Any, Any, Any], list[dict[str, Any]]] = {}
        for proposal in proposals:
            if (isinstance(proposal.get("object_ref"), str) and proposal["object_ref"].strip()
                    and isinstance(proposal.get("scope_key"), str) and proposal["scope_key"].strip()
                    and isinstance(proposal.get("fact_key"), str) and proposal["fact_key"].strip()):
                key = (proposal.get("object_ref"), proposal.get("scope_key"), proposal.get("fact_key"))
                groups.setdefault(key, []).append(proposal)
        contested: set[str] = set()
        for group in groups.values():
            values = {_digest(p.get("fact_value")) for p in group}
            if len(values) > 1:
                contested.update(p["id"] for p in group)
        claim_ids = {e["to_id"] for e in relationships if e["relation"] == "evidence_contradicts_claim"}
        for proposal in proposals:
            if proposal.get("object_ref") in claim_ids or proposal.get("claim_id") in claim_ids:
                contested.add(proposal["id"])
            if any(d.get("record_id") in claim_ids for d in proposal.get("dependencies", [])):
                contested.add(proposal["id"])
        changed = True
        while changed:
            changed = False
            for proposal in proposals:
                if proposal["id"] in contested:
                    continue
                if any(d.get("record_id") in contested for d in proposal.get("dependencies", [])):
                    contested.add(proposal["id"])
                    changed = True
        return contested

    def failures(self, *, object_ref: str | None = None, task_id: str | None = None, route_id: str | None = None, version: str | None = None) -> list[dict[str, Any]]:
        failures = [r for r in self._latest().values() if r["type"] == "Failure"]
        def match(record: dict[str, Any]) -> bool:
            if object_ref is not None and object_ref not in record.get("object_refs", []): return False
            if task_id is not None and record.get("task_id") != task_id: return False
            if route_id is not None and record.get("route_id") != route_id: return False
            if version is not None and version not in record.get("affected_product_versions", []): return False
            return True
        return sorted((copy.deepcopy(f) for f in failures if match(f)), key=lambda r: r["id"])

    def failure_gate(self, *, object_ref: str | None = None, task_id: str | None = None,
                     route_id: str | None = None, version: str | None = None) -> dict[str, Any]:
        """Return a mechanical preflight result for a proposed related action."""
        related = self.failures(object_ref=object_ref, task_id=task_id, route_id=route_id, version=version)
        blocking = [failure for failure in related if failure.get("resolution_status") == "open"]
        return {"status": "blocked" if blocking else "clear",
                "failure_ids": [failure["id"] for failure in blocking],
                "related_failure_ids": [failure["id"] for failure in related],
                "resume_condition": "resolve_or_scope_away_from_related_failures" if blocking else None}

    def rebuild(self, output: str | Path | None = None, *, object_ref: str | None = None, task_id: str | None = None,
                route_id: str | None = None, version: str | None = None) -> dict[str, Any]:
        latest = self._latest()
        all_relationships = [e for tx in self._transactions() for e in tx["relationships"]]
        relationships: dict[str, dict[str, Any]] = {}
        for edge in all_relationships:
            if edge["revision"] >= relationships.get(edge["relationship_id"], {"revision": 0})["revision"]:
                relationships[edge["relationship_id"]] = edge
        proposals = sorted((copy.deepcopy(r) for r in latest.values() if r["type"] == "CognitionProposal"), key=lambda r: r["id"])
        for proposal in proposals:
            dependency_reason = self._dependency_state(proposal, latest)
            if dependency_reason:
                proposal["current_status"] = "stale"
                proposal["status_reason"] = dependency_reason
            else:
                proposal["current_status"] = proposal["admitted_status"]
        eligible = [p for p in proposals if p["current_status"] not in {"stale", "rejected"}]
        contested = self._conflicts(eligible, list(relationships.values()))
        for proposal in proposals:
            if proposal["id"] in contested:
                proposal["current_status"] = "contested"
                proposal["status_reason"] = "structured_conflict"
        queue: dict[str, list[str]] = {}
        for p in proposals:
            if p["current_status"] == "pending_review":
                queue.setdefault(p["review_key"], []).append(p["id"])
        routes = sorted((copy.deepcopy(r) for r in latest.values() if r["type"] == "Route"), key=lambda r: r["id"])
        questions = sorted((copy.deepcopy(r) for r in latest.values() if r["type"] == "ResearchQuestion"), key=lambda r: r["id"])
        view = {"schema_version": 1, "type": "CoreCognition", "project_id": self.store.project_id,
                "research_questions": questions, "routes": routes,
                "provisional": [p for p in proposals if p["current_status"] == "provisional"],
                "supported_within_scope": [p for p in proposals if p["current_status"] == "accepted"],
                "accepted": [p for p in proposals if p["current_status"] == "accepted"],
                "proposed": [p for p in proposals if p["current_status"] == "proposed"],
                "contested": [p for p in proposals if p["current_status"] == "contested"],
                "stale": [p for p in proposals if p["current_status"] == "stale"],
                "pending_review": [{"review_key": key, "proposal_ids": sorted(ids)} for key, ids in sorted(queue.items())],
                "missing_evidence": [p["id"] for p in proposals if not p["evidence_refs"]],
                "failures": self.failures(object_ref=object_ref, task_id=task_id, route_id=route_id, version=version)}
        if output is not None:
            target = (self.project_root / output).resolve()
            if target == self.project_root or self.project_root not in target.parents:
                raise CognitionError("cognition view output escapes project root")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.tmp")
            temporary.write_text(json.dumps(view, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        return view


__all__ = ["CoreCognition", "CognitionError", "MECHANICAL_KINDS"]
