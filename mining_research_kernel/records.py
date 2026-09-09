"""Project-local immutable research transactions and a deterministic map view.

This module deliberately has no provider, database, or runtime dependencies.
The transaction files are the authority; the map is only a rebuildable view.
"""
from __future__ import annotations

import json
import hashlib
import copy
import os
import re
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Callable, Iterable

from mining_research_kernel.artifacts import _reject_reparse_chain


def _check_record_path(path: Path) -> None:
    try:
        _reject_reparse_chain(path, "research records")
    except ValueError as exc:
        raise ResearchStoreError(str(exc)) from exc


SCHEMA_VERSION = 1
TRANSACTION_TYPE = "ResearchTransaction"
MAP_TYPE = "ResearchMap"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
SEQUENCE_RE = re.compile(r"[0-9]{8}\.json\Z", re.ASCII)
TEMP_RE = re.compile(r"\.[^/\\]+\.tmp\Z", re.ASCII)
HASH_RE = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)

RECORD_TYPES = frozenset(
    {
        "ResearchQuestion",
        "Hypothesis",
        "TaskState",
        "Asset",
        "Claim",
        "Evidence",
        "Route",
        "Failure",
        "Decision",
        "Verification",
        "RunReference",
        "RouteComparison",
        "CognitionProposal",
        "CognitionReview",
    }
)
RELATIONS = frozenset(
    {
        "route_addresses_question",
        "route_tests_hypothesis",
        "evidence_supports_claim",
        "evidence_contradicts_claim",
        "run_executes_route",
        "run_produces_evidence",
        "verification_checks_run",
        "failure_observed_in_run",
        "decision_closes_route",
        "source_documents_claim",
        "evidence_derived_from_asset",
        "route_child_of_route",
        "route_supersedes_route",
        "route_in_comparison",
        "route_targets_claim",
        "cognition_proposal_uses_evidence",
        "cognition_review_reviews_proposal",
        "cognition_review_uses_evidence",
    }
)
RELATION_ENDPOINTS = {
    "route_addresses_question": ("Route", "ResearchQuestion"),
    "route_tests_hypothesis": ("Route", "Hypothesis"),
    "evidence_supports_claim": ("Evidence", "Claim"),
    "evidence_contradicts_claim": ("Evidence", "Claim"),
    "run_executes_route": ("RunReference", "Route"),
    "run_produces_evidence": ("RunReference", "Evidence"),
    "verification_checks_run": ("Verification", "RunReference"),
    "failure_observed_in_run": ("Failure", "RunReference"),
    "decision_closes_route": ("Decision", "Route"),
    "source_documents_claim": ("Evidence", "Claim"),
    "evidence_derived_from_asset": ("Evidence", "Asset"),
    "route_child_of_route": ("Route", "Route"),
    "route_supersedes_route": ("Route", "Route"),
    "route_in_comparison": ("RouteComparison", "Route"),
    "route_targets_claim": ("Route", "Claim"),
    "cognition_proposal_uses_evidence": ("CognitionProposal", "Evidence"),
    "cognition_review_reviews_proposal": ("CognitionReview", "CognitionProposal"),
    "cognition_review_uses_evidence": ("CognitionReview", "Evidence"),
}


class ResearchStoreError(ValueError):
    """Base error for malformed or unsafe store operations."""


class WriterLockedError(ResearchStoreError):
    """Raised when another writer owns the project lock."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        text = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ResearchStoreError(f"value is not canonical JSON: {exc}") from exc
    return text.encode("utf-8")


def _pretty_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    ).encode("utf-8")


def _transaction_digest(transaction: dict[str, Any]) -> str:
    unsigned = dict(transaction)
    unsigned.pop("content_sha256", None)
    return hashlib.sha256(_canonical_bytes(unsigned)).hexdigest()


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_revision(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _validate_id(value: Any, field: str) -> None:
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ResearchStoreError(
            f"{field} must match ASCII [A-Za-z0-9][A-Za-z0-9._-]{{0,63}}"
        )


def _validate_source_refs(value: Any, field: str = "source_refs") -> None:
    if not isinstance(value, list):
        raise ResearchStoreError(f"{field} must be a list")
    if not all(_is_nonempty_string(item) for item in value):
        raise ResearchStoreError(f"{field} entries must be non-empty strings")


def _validate_scope(value: Any) -> None:
    if not isinstance(value, dict) or not value:
        raise ResearchStoreError("scope must be a non-empty object")


def _require_string(record: dict[str, Any], field: str) -> None:
    if field not in record:
        raise ResearchStoreError(f"missing {field}")
    if not _is_nonempty_string(record[field]):
        raise ResearchStoreError(f"{field} must be a non-empty string")


def _validate_json_object(value: Any, field: str) -> None:
    if not isinstance(value, dict):
        raise ResearchStoreError(f"{field} must be an object")
    try:
        encoded = _canonical_bytes(value)
        round_tripped = json.loads(encoded.decode("utf-8"))
    except ResearchStoreError as exc:
        raise ResearchStoreError(f"{field} must be canonical JSON") from exc
    if round_tripped != value:
        raise ResearchStoreError(f"{field} must be canonical JSON")


def _validate_record(record: Any, project_id: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ResearchStoreError("record must be an object")
    if record.get("schema_version") != SCHEMA_VERSION:
        raise ResearchStoreError("record schema_version must be 1")
    record_type = record.get("type")
    if record_type not in RECORD_TYPES:
        raise ResearchStoreError(f"unsupported record type: {record_type!r}")
    _validate_id(record.get("id"), "record id")
    if not _is_revision(record.get("revision")):
        raise ResearchStoreError("record revision must be an integer >= 1")
    if record.get("project_id") != project_id:
        raise ResearchStoreError("record project_id does not match project config")
    _validate_scope(record.get("scope"))
    _validate_source_refs(record.get("source_refs"))

    if record_type in {"ResearchQuestion", "Hypothesis"}:
        _require_string(record, "statement")
        _require_string(record, "status")
    elif record_type == "TaskState":
        if record.get("task_id") != record.get("id"):
            raise ResearchStoreError("TaskState task_id must equal id")
        if record.get("state") not in {"proposed", "ready", "running", "completed", "blocked", "failed"}:
            raise ResearchStoreError("TaskState state is invalid")
        packet = record.get("packet")
        _validate_json_object(packet, "TaskState packet")
        if packet.get("project_id") != project_id or packet.get("task_id") != record["id"]:
            raise ResearchStoreError("TaskState packet project_id/task_id does not match record")
        _validate_json_object(record.get("operation_results"), "operation_results")
    elif record_type == "Asset":
        _require_string(record, "asset_kind")
        if not isinstance(record.get("locator"), dict):
            raise ResearchStoreError("locator must be an object")
        content_sha256 = record.get("content_sha256")
        if content_sha256 is not None and (
            not isinstance(content_sha256, str) or HASH_RE.fullmatch(content_sha256) is None
        ):
            raise ResearchStoreError("content_sha256 must be lowercase 64 hex or null")
        if record.get("authority") not in {"authoritative", "derived"}:
            raise ResearchStoreError("authority is invalid")
        _require_string(record, "status")
    elif record_type == "Claim":
        _require_string(record, "statement")
        _require_string(record, "status")
    elif record_type == "Evidence":
        _require_string(record, "evidence_kind")
        _require_string(record, "asset_ref")
        if "locator" not in record or record["locator"] is None:
            raise ResearchStoreError("missing locator")
        _require_string(record, "status")
    elif record_type == "Route":
        if record.get("status") not in {"proposed", "active", "blocked", "completed", "failed", "cannot_verify", "accepted", "rejected", "superseded"}:
            raise ResearchStoreError("Route status is invalid")
        _require_string(record, "question_id")
        if "research_question_id" in record and record["research_question_id"] != record["question_id"]:
            raise ResearchStoreError("Route research_question_id must equal question_id")
        if "hypothesis_id" not in record:
            raise ResearchStoreError("missing hypothesis_id")
        if record["hypothesis_id"] is not None and not _is_nonempty_string(record["hypothesis_id"]):
            raise ResearchStoreError("hypothesis_id must be a non-empty string or null")
        _require_string(record, "workflow_id")
        _require_string(record, "method_id")
        budget = record.get("budget")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget < 0:
            raise ResearchStoreError("budget must be an integer >= 0")
        if "route_id" in record and record["route_id"] != record["id"]:
            raise ResearchStoreError("Route route_id must equal id")
        for field in ("task_id", "claim_id"):
            if field in record and record[field] is not None and not _is_nonempty_string(record[field]):
                raise ResearchStoreError(f"Route {field} must be a non-empty string or null")
        for field in ("parent_route_id", "supersedes_route_id"):
            if field in record and record[field] is not None and not _is_nonempty_string(record[field]):
                raise ResearchStoreError(f"{field} must be a non-empty string or null")
        for field in ("write_set", "stop_conditions", "outputs"):
            if field in record:
                if not isinstance(record[field], list):
                    raise ResearchStoreError(f"Route {field} must be a list")
                if field == "write_set" and not all(_is_nonempty_string(item) for item in record[field]):
                    raise ResearchStoreError("Route write_set entries must be non-empty strings")
        if "runs_used" in record and (not isinstance(record["runs_used"], int) or isinstance(record["runs_used"], bool) or record["runs_used"] < 0):
            raise ResearchStoreError("Route runs_used must be an integer >= 0")
        if "stop_reason" in record and record["stop_reason"] is not None and not _is_nonempty_string(record["stop_reason"]):
            raise ResearchStoreError("Route stop_reason must be a non-empty string or null")
        if "reservations" in record:
            if not isinstance(record["reservations"], list):
                raise ResearchStoreError("Route reservations must be a list")
            for reservation in record["reservations"]:
                _validate_json_object(reservation, "Route reservation")
    elif record_type == "RouteComparison":
        _require_string(record, "question_id")
        route_ids = record.get("route_ids")
        if not isinstance(route_ids, list) or not route_ids or not all(_is_nonempty_string(item) for item in route_ids):
            raise ResearchStoreError("RouteComparison route_ids must be a non-empty list of strings")
        entries = record.get("entries")
        if not isinstance(entries, list) or len(entries) != len(route_ids):
            raise ResearchStoreError("RouteComparison entries must match route_ids")
        for entry in entries:
            _validate_json_object(entry, "RouteComparison entry")
        if record.get("status") != "archived":
            raise ResearchStoreError("RouteComparison status must be archived")
        if "stop_reason" in record and record["stop_reason"] is not None and not _is_nonempty_string(record["stop_reason"]):
            raise ResearchStoreError("RouteComparison stop_reason must be a non-empty string or null")
    elif record_type == "Failure":
        _require_string(record, "status")
        _require_string(record, "observable_failure")
        if "failure_id" in record and record["failure_id"] != record["id"]:
            raise ResearchStoreError("Failure failure_id must equal id")
        if "run_id" in record and record["run_id"] is not None and not _is_nonempty_string(record["run_id"]):
            raise ResearchStoreError("Failure run_id must be a non-empty string or null")
        if "route_id" in record and record["route_id"] is not None and not _is_nonempty_string(record["route_id"]):
            raise ResearchStoreError("Failure route_id must be a non-empty string or null")
        if "task_id" in record and record["task_id"] is not None and not _is_nonempty_string(record["task_id"]):
            raise ResearchStoreError("Failure task_id must be a non-empty string or null")
        if "reproduction" in record and not isinstance(record["reproduction"], list):
            raise ResearchStoreError("Failure reproduction must be a list")
        for field in ("affected_product_versions", "input_assets", "evidence_assets", "object_refs"):
            if field in record and (not isinstance(record[field], list) or not all(_is_nonempty_string(v) for v in record[field])):
                raise ResearchStoreError(f"Failure {field} must be a list of non-empty strings")
        if "root_cause_status" in record and record["root_cause_status"] not in {"unknown", "suspected", "verified"}:
            raise ResearchStoreError("Failure root_cause_status is invalid")
        if "resolution_status" in record and record["resolution_status"] not in {"open", "mitigated", "resolved", "superseded"}:
            raise ResearchStoreError("Failure resolution_status is invalid")
        if "applicability" in record and record["applicability"] not in {"project_only", "workflow_candidate"}:
            raise ResearchStoreError("Failure applicability is invalid")
    elif record_type == "CognitionProposal":
        if record.get("proposal_id") != record.get("id"):
            raise ResearchStoreError("CognitionProposal proposal_id must equal id")
        if record.get("proposal_type") not in {"project_lesson", "workflow_rule", "domain_rule", "claim", "supersession", "conflict"}:
            raise ResearchStoreError("CognitionProposal proposal_type is invalid")
        _require_string(record, "statement")
        for field in ("evidence_refs", "counterevidence_refs"):
            if not isinstance(record.get(field), list) or not all(_is_nonempty_string(v) for v in record[field]):
                raise ResearchStoreError(f"CognitionProposal {field} must be a list of non-empty strings")
        scope = record.get("scope")
        if not isinstance(scope, dict) or not scope:
            raise ResearchStoreError("CognitionProposal scope must be a non-empty object")
        if record.get("requested_status") not in {"proposed", "provisional", "accepted", "rejected", "contested", "pending_review"}:
            raise ResearchStoreError("CognitionProposal requested_status is invalid")
        if record.get("admitted_status") not in {"proposed", "provisional", "accepted", "rejected", "contested", "pending_review", "stale"}:
            raise ResearchStoreError("CognitionProposal admitted_status is invalid")
        if record.get("current_status") not in {"proposed", "provisional", "accepted", "rejected", "contested", "pending_review", "stale"}:
            raise ResearchStoreError("CognitionProposal current_status is invalid")
        _require_string(record, "created_by")
        if "impact" in record and record["impact"] not in {"low", "medium", "high"}:
            raise ResearchStoreError("CognitionProposal impact is invalid")
        if "fact_key" in record and record["fact_key"] is not None and not _is_nonempty_string(record["fact_key"]):
            raise ResearchStoreError("CognitionProposal fact_key must be a non-empty string or null")
        if "object_ref" in record and record["object_ref"] is not None and not _is_nonempty_string(record["object_ref"]):
            raise ResearchStoreError("CognitionProposal object_ref must be a non-empty string or null")
        for field in ("dependencies", "invalidation_conditions"):
            if field in record and not isinstance(record[field], list):
                raise ResearchStoreError(f"CognitionProposal {field} must be a list")
        if "review_key" in record:
            _require_string(record, "review_key")
    elif record_type == "CognitionReview":
        if record.get("review_id") != record.get("id"):
            raise ResearchStoreError("CognitionReview review_id must equal id")
        _require_string(record, "proposal_id")
        _require_string(record, "review_ref")
        if record.get("decision") not in {"accept", "reject", "contested"}:
            raise ResearchStoreError("CognitionReview decision is invalid")
        if not isinstance(record.get("evidence_refs"), list) or not all(_is_nonempty_string(v) for v in record["evidence_refs"]):
            raise ResearchStoreError("CognitionReview evidence_refs must be a list of non-empty strings")
        if not isinstance(record.get("scope"), dict) or not record["scope"]:
            raise ResearchStoreError("CognitionReview scope must be a non-empty object")
        if record.get("impact") not in {"low", "medium", "high"}:
            raise ResearchStoreError("CognitionReview impact is invalid")
    elif record_type == "Decision":
        _require_string(record, "status")
        _require_string(record, "statement")
    elif record_type == "Verification":
        _require_string(record, "status")
        _require_string(record, "gate_id")
    elif record_type == "RunReference":
        _require_string(record, "run_id")
        manifest_sha256 = record.get("manifest_sha256")
        if not isinstance(manifest_sha256, str) or HASH_RE.fullmatch(manifest_sha256) is None:
            raise ResearchStoreError("manifest_sha256 must be lowercase 64 hex")
        _require_string(record, "status")
    return record


def _validate_relationship(relationship: Any, project_id: str) -> dict[str, Any]:
    if not isinstance(relationship, dict):
        raise ResearchStoreError("relationship must be an object")
    if relationship.get("schema_version") != SCHEMA_VERSION:
        raise ResearchStoreError("relationship schema_version must be 1")
    _validate_id(relationship.get("relationship_id"), "relationship_id")
    if not _is_revision(relationship.get("revision")):
        raise ResearchStoreError("relationship revision must be an integer >= 1")
    if relationship.get("project_id") != project_id:
        raise ResearchStoreError("relationship project_id does not match project config")
    relation = relationship.get("relation")
    if relation not in RELATIONS:
        raise ResearchStoreError(f"unsupported relation: {relation!r}")
    _validate_id(relationship.get("from_id"), "from_id")
    _validate_id(relationship.get("to_id"), "to_id")
    if not _is_revision(relationship.get("from_revision")):
        raise ResearchStoreError("from_revision must be an integer >= 1")
    if not _is_revision(relationship.get("to_revision")):
        raise ResearchStoreError("to_revision must be an integer >= 1")
    _validate_source_refs(relationship.get("source_refs"))
    return relationship


def _validate_transaction_shape(transaction: Any, project_id: str, sequence: int | None = None) -> dict[str, Any]:
    if not isinstance(transaction, dict):
        raise ResearchStoreError("transaction must be an object")
    if transaction.get("schema_version") != SCHEMA_VERSION:
        raise ResearchStoreError("transaction schema_version must be 1")
    if transaction.get("type") != TRANSACTION_TYPE:
        raise ResearchStoreError("transaction type must be ResearchTransaction")
    tx_sequence = transaction.get("sequence")
    if not isinstance(tx_sequence, int) or isinstance(tx_sequence, bool) or tx_sequence < 1:
        raise ResearchStoreError("transaction sequence must be a positive integer")
    if sequence is not None and tx_sequence != sequence:
        raise ResearchStoreError("transaction sequence does not match filename")
    _validate_id(transaction.get("operation_id"), "operation_id")
    producer = transaction.get("producer")
    if not isinstance(producer, dict):
        raise ResearchStoreError("producer must be an object")
    _require_string(producer, "role")
    _require_string(producer, "model")
    records = transaction.get("records")
    relationships = transaction.get("relationships")
    if not isinstance(records, list):
        raise ResearchStoreError("records must be a list")
    if not isinstance(relationships, list):
        raise ResearchStoreError("relationships must be a list")
    if "content_sha256" in transaction:
        digest = transaction["content_sha256"]
        if not isinstance(digest, str) or digest != _transaction_digest(transaction):
            raise ResearchStoreError("transaction content_sha256 does not match content")
    for record in records:
        _validate_record(record, project_id)
    for relationship in relationships:
        _validate_relationship(relationship, project_id)
    _validate_cognition_admission_policy(records, relationships, producer)
    return transaction


def _validate_cognition_admission_policy(records: list[dict[str, Any]],
                                         relationships: list[dict[str, Any]],
                                         producer: dict[str, Any]) -> None:
    """Require an auditable review transaction for accepted cognition.

    This is a controlled write boundary, not authentication.  A caller with
    equal filesystem permissions can still forge the complete transaction;
    the Host review boundary remains the authority for ordinary use.
    """
    accepted = [record for record in records
                if record.get("type") == "CognitionProposal"
                and record.get("admitted_status") == "accepted"]
    if not accepted:
        return
    if producer.get("role") != "acceptance_agent":
        raise ResearchStoreError("accepted cognition requires acceptance_agent producer")
    reviews = {record.get("proposal_id"): record for record in records
               if record.get("type") == "CognitionReview" and record.get("decision") == "accept"}
    for proposal in accepted:
        review = reviews.get(proposal.get("id"))
        if review is None or not _is_nonempty_string(review.get("boundary_id")):
            raise ResearchStoreError("accepted cognition requires a same-transaction trusted review")
        if not any(edge.get("relation") == "cognition_review_reviews_proposal"
                   and edge.get("from_id") == review.get("id")
                   and edge.get("to_id") == proposal.get("id")
                   and edge.get("to_revision") == proposal.get("revision")
                   for edge in relationships):
            raise ResearchStoreError("accepted cognition requires a review provenance relationship")


class _Writer:
    def __init__(self, lock_path: Path, operation_id: str):
        self.lock_path = lock_path
        self.operation_id = operation_id
        self._owner_bytes = _pretty_bytes({"operation_id": operation_id})
        self._owned = False

    def __enter__(self) -> "_Writer":
        _check_record_path(self.lock_path)
        _check_record_path(self.lock_path.parent / "records")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(str(self.lock_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise WriterLockedError(f"project writer lock is held: {self.lock_path}") from exc
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(self._owner_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            self._owned = True
        except Exception:
            try:
                self.lock_path.unlink()
            except FileNotFoundError:
                pass
            raise
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        if not self._owned:
            return
        try:
            if self.lock_path.read_bytes() == self._owner_bytes:
                self.lock_path.unlink()
        finally:
            self._owned = False


class ResearchStore:
    """An immutable, single-writer transaction store rooted at one project."""

    def __init__(self, project_root: str | os.PathLike[str], injection_hook: Callable[..., Any] | None = None):
        self.project_root = Path(project_root).resolve()
        if not self.project_root.is_dir():
            raise ResearchStoreError(f"project root is not a directory: {self.project_root}")
        self.project_id, self._configured_map = self._read_project_config()
        self.research_dir = self.project_root / "research"
        self.records_dir = self.research_dir / "records"
        self.lock_path = self.research_dir / ".writer.lock"
        self.injection_hook = injection_hook

    def _read_project_config(self) -> tuple[str, Path]:
        config_path = self.project_root / "flac3d_project.yaml"
        if not config_path.is_file():
            raise ResearchStoreError("missing project config: flac3d_project.yaml")
        try:
            from flac3d_project import load_config

            config = load_config(self.project_root)
        except Exception as exc:
            raise ResearchStoreError(f"invalid project config: {exc}") from exc
        project_id = config.get("project_id") if isinstance(config, dict) else None
        if not _is_nonempty_string(project_id):
            raise ResearchStoreError("project config project_id must be a non-empty string")
        configured = config.get("research_map", "research/map.json")
        if not isinstance(configured, str) or not configured.strip():
            raise ResearchStoreError("project config research_map must be a path")
        map_path = (self.project_root / configured).resolve()
        if map_path != self.project_root and self.project_root not in map_path.parents:
            raise ResearchStoreError("project config research_map escapes project root")
        return project_id, map_path

    def writer(self, operation_id: str) -> _Writer:
        _validate_id(operation_id, "operation_id")
        _check_record_path(self.records_dir)
        return _Writer(self.lock_path, operation_id)

    acquire_writer = writer

    def _call_hook(self, stage: str, hook: Callable[..., Any] | None) -> None:
        callback = hook if hook is not None else self.injection_hook
        if callback is not None:
            callback(stage)

    def _read_transactions(self) -> list[dict[str, Any]]:
        _check_record_path(self.records_dir)
        if not self.records_dir.exists():
            return []
        if not self.records_dir.is_dir():
            raise ResearchStoreError("research/records is not a directory")
        entries: list[tuple[int, Path]] = []
        for path in self.records_dir.iterdir():
            _check_record_path(path)
            if path.is_dir():
                continue
            if TEMP_RE.fullmatch(path.name):
                continue
            if path.suffix == ".json":
                if not SEQUENCE_RE.fullmatch(path.name):
                    raise ResearchStoreError(f"invalid transaction filename: {path.name}")
                sequence = int(path.stem)
                if sequence < 1:
                    raise ResearchStoreError(f"invalid transaction sequence: {path.name}")
                entries.append((sequence, path))
        entries.sort(key=lambda item: item[0])
        for expected, (sequence, _) in enumerate(entries, start=1):
            if sequence != expected:
                raise ResearchStoreError(
                    f"transaction sequence gap: expected {expected}, got {sequence}"
                )
        transactions: list[dict[str, Any]] = []
        for sequence, path in entries:
            try:
                transaction = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ResearchStoreError(f"cannot read transaction {path.name}: {exc}") from exc
            transactions.append(_validate_transaction_shape(transaction, self.project_id, sequence))
        self._validate_history(transactions)
        return transactions

    def list_transactions(self) -> list[dict[str, Any]]:
        return self._read_transactions()

    load_transactions = list_transactions

    def _validate_history(self, transactions: Iterable[dict[str, Any]]) -> None:
        transactions = list(transactions)
        seen_sequences: set[int] = set()
        seen_operations: set[str] = set()
        latest_records: dict[str, dict[str, Any]] = {}
        seen_record_versions: set[tuple[str, int]] = set()
        latest_relationships: dict[str, dict[str, Any]] = {}
        seen_relationship_versions: set[tuple[str, int]] = set()

        for transaction in transactions:
            sequence = transaction["sequence"]
            if sequence in seen_sequences:
                raise ResearchStoreError(f"duplicate transaction sequence: {sequence}")
            seen_sequences.add(sequence)
            operation_id = transaction["operation_id"]
            if operation_id in seen_operations:
                raise ResearchStoreError(f"duplicate operation_id: {operation_id}")
            seen_operations.add(operation_id)

            before_records = dict(latest_records)
            same_transaction: dict[tuple[str, int], dict[str, Any]] = {}
            for record in sorted(transaction["records"], key=lambda item: (item["id"], item["revision"])):
                key = (record["id"], record["revision"])
                if key in seen_record_versions or key in same_transaction:
                    raise ResearchStoreError(f"duplicate record id+revision: {key[0]}@{key[1]}")
                same_transaction[key] = record
            for record in sorted(same_transaction.values(), key=lambda item: (item["id"], item["revision"])):
                previous = latest_records.get(record["id"])
                expected = 1 if previous is None else previous["revision"] + 1
                if record["revision"] != expected:
                    raise ResearchStoreError(
                        f"revision gap for {record['id']}: expected {expected}, got {record['revision']}"
                    )
                if previous is not None and previous["type"] != record["type"]:
                    raise ResearchStoreError(f"record type changed for {record['id']}")
                latest_records[record["id"]] = record
                seen_record_versions.add((record["id"], record["revision"]))

            same_relationship: dict[tuple[str, int], dict[str, Any]] = {}
            for relationship in sorted(
                transaction["relationships"], key=lambda item: (item["relationship_id"], item["revision"])
            ):
                key = (relationship["relationship_id"], relationship["revision"])
                if key in seen_relationship_versions or key in same_relationship:
                    raise ResearchStoreError(f"duplicate relationship id+revision: {key[0]}@{key[1]}")
                same_relationship[key] = relationship
            for relationship in sorted(
                same_relationship.values(), key=lambda item: (item["relationship_id"], item["revision"])
            ):
                previous = latest_relationships.get(relationship["relationship_id"])
                expected = 1 if previous is None else previous["revision"] + 1
                if relationship["revision"] != expected:
                    raise ResearchStoreError(
                        f"relationship revision gap for {relationship['relationship_id']}: "
                        f"expected {expected}, got {relationship['revision']}"
                    )
                latest_relationships[relationship["relationship_id"]] = relationship
                seen_relationship_versions.add(
                    (relationship["relationship_id"], relationship["revision"])
                )

            available = dict(before_records)
            available.update({(record["id"]): record for record in same_transaction.values()})
            for relationship in transaction["relationships"]:
                from_record = available.get(relationship["from_id"])
                to_record = available.get(relationship["to_id"])
                expected_from, expected_to = RELATION_ENDPOINTS[relationship["relation"]]
                if from_record is None or from_record["revision"] != relationship["from_revision"]:
                    same = same_transaction.get((relationship["from_id"], relationship["from_revision"]))
                    from_record = same if same is not None else None
                if to_record is None or to_record["revision"] != relationship["to_revision"]:
                    same = same_transaction.get((relationship["to_id"], relationship["to_revision"]))
                    to_record = same if same is not None else None
                if from_record is None or to_record is None:
                    raise ResearchStoreError(
                        f"dangling relationship endpoint: {relationship['relationship_id']}"
                    )
                if from_record["type"] != expected_from or to_record["type"] != expected_to:
                    raise ResearchStoreError(
                        f"invalid endpoint types for relation {relationship['relation']}"
                    )

            for evidence in transaction["records"]:
                if evidence["type"] != "Evidence":
                    continue
                asset = available.get(evidence["asset_ref"])
                if asset is None or asset["type"] != "Asset":
                    raise ResearchStoreError(
                        f"Evidence {evidence['id']} asset_ref has no Asset provenance"
                    )
                if not any(
                    relationship["relation"] == "evidence_derived_from_asset"
                    and relationship["from_id"] == evidence["id"]
                    and relationship["from_revision"] == evidence["revision"]
                    and relationship["to_id"] == evidence["asset_ref"]
                    and relationship["to_revision"] == asset["revision"]
                    for relationship in transaction["relationships"]
                ):
                    raise ResearchStoreError(
                        f"Evidence {evidence['id']} requires evidence_derived_from_asset provenance"
                    )

    def commit(
        self,
        operation_id: str,
        producer: dict[str, Any],
        records: list[dict[str, Any]],
        relationships: list[dict[str, Any]] | None = None,
        *,
        injection_hook: Callable[..., Any] | None = None,
        expected_revisions: dict[str, int] | None = None,
        lock_held: bool = False,
    ) -> dict[str, Any]:
        _validate_id(operation_id, "operation_id")
        if not isinstance(producer, dict):
            raise ResearchStoreError("producer must be an object")
        _require_string(producer, "role")
        _require_string(producer, "model")
        if not isinstance(records, list):
            raise ResearchStoreError("records must be a list")
        if relationships is None:
            relationships = []
        if not isinstance(relationships, list):
            raise ResearchStoreError("relationships must be a list")
        if expected_revisions is not None:
            if not isinstance(expected_revisions, dict):
                raise ResearchStoreError("expected_revisions must be an object")
            for record_id, revision in expected_revisions.items():
                _validate_id(record_id, "expected record id")
                if not _is_revision(revision):
                    raise ResearchStoreError("expected record revision must be an integer >= 1")
        # Canonicalize caller-owned objects before acquiring the lock or writing.
        try:
            producer = json.loads(_canonical_bytes(producer).decode("utf-8"))
            records = json.loads(_canonical_bytes(records).decode("utf-8"))
            relationships = json.loads(_canonical_bytes(relationships).decode("utf-8"))
        except ResearchStoreError:
            raise
        for record in records:
            _validate_record(record, self.project_id)
        for relationship in relationships:
            _validate_relationship(relationship, self.project_id)
        _validate_cognition_admission_policy(records, relationships, producer)

        # ``lock_held`` is an internal composition hook for services that must
        # inspect current records and commit the resulting update under the
        # same project writer lock. Ordinary callers keep the safe default.
        lock = nullcontext() if lock_held else self.writer(operation_id)
        with lock:
            transactions = self._read_transactions()
            if expected_revisions:
                latest_records = self._latest_record_map(transactions)
                for record_id, expected in expected_revisions.items():
                    actual = latest_records.get(record_id)
                    actual_revision = actual["revision"] if actual is not None else 0
                    if actual_revision != expected:
                        raise ResearchStoreError(
                            f"record revision changed for {record_id}: "
                            f"expected {expected}, got {actual_revision}"
                        )
            existing = next(
                (transaction for transaction in transactions if transaction["operation_id"] == operation_id),
                None,
            )
            if existing is not None:
                if (
                    existing["producer"] != producer
                    or existing["records"] != records
                    or existing["relationships"] != relationships
                ):
                    raise ResearchStoreError(f"conflicting payload for operation_id: {operation_id}")
                return existing

            sequence = max((transaction["sequence"] for transaction in transactions), default=0) + 1
            transaction = {
                "schema_version": SCHEMA_VERSION,
                "type": TRANSACTION_TYPE,
                "sequence": sequence,
                "operation_id": operation_id,
                "producer": producer,
                "records": records,
                "relationships": relationships,
            }
            transaction["content_sha256"] = _transaction_digest(transaction)
            _validate_transaction_shape(transaction, self.project_id, sequence)
            self._validate_history([*transactions, transaction])
            self.records_dir.mkdir(parents=True, exist_ok=True)
            temporary = self.records_dir / f".{operation_id}.tmp"
            target = self.records_dir / f"{sequence:08d}.json"
            _check_record_path(temporary)
            _check_record_path(target)
            temporary.write_bytes(_pretty_bytes(transaction))
            with temporary.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            self._call_hook("after_temp_fsync", injection_hook)
            self._call_hook("before_replace", injection_hook)
            os.replace(str(temporary), str(target))
            self._call_hook("after_replace", injection_hook)
            return transaction

    def _latest_record_map(self, transactions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        records: dict[str, dict[str, Any]] = {}
        for transaction in transactions:
            for record in transaction["records"]:
                if record["revision"] >= records.get(record["id"], {"revision": 0})["revision"]:
                    records[record["id"]] = record
        return records

    def latest_record(self, record_id: str, type: str | None = None) -> dict[str, Any] | None:
        _validate_id(record_id, "record id")
        if type is not None and type not in RECORD_TYPES:
            raise ResearchStoreError(f"unsupported record type: {type!r}")
        latest = self._latest_record_map(self._read_transactions()).get(record_id)
        if latest is None or (type is not None and latest["type"] != type):
            return None
        return copy.deepcopy(latest)

    def register_local_material(
        self,
        path: str | os.PathLike[str],
        material_kind: str,
        *,
        citation_locator: dict[str, Any] | None = None,
        source_refs: list[str] | None = None,
        source_documents_claim: str | None = None,
    ) -> dict[str, Any]:
        """Register caller-selected local material without copying its bytes.

        The source is read once for its digest and is never written.  Absolute
        paths are allowed only as explicit caller input; persisted locators
        expose a project-relative path or a controlled caller label.
        """
        if material_kind not in {"primary/original", "project_record", "derived_reading_note"}:
            raise ResearchStoreError("material_kind is unsupported")
        raw = Path(path).expanduser()
        explicit_external = raw.is_absolute()
        if not explicit_external and (".." in raw.parts or str(raw).startswith(("/", "\\"))):
            raise ResearchStoreError("relative material path escapes project root")
        resolved = raw.resolve() if explicit_external else (self.project_root / raw).resolve()
        if not explicit_external:
            try:
                locator_path = resolved.relative_to(self.project_root).as_posix()
            except ValueError as exc:
                raise ResearchStoreError("relative material path resolves outside project root") from exc
        else:
            try:
                locator_path = resolved.relative_to(self.project_root).as_posix()
            except ValueError:
                locator_path = f"caller:{resolved.name}"
        if not resolved.is_file():
            raise ResearchStoreError("material path must be an existing file")
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        authority = "derived" if material_kind == "derived_reading_note" else "authoritative"
        identity = f"{self.project_id}|{material_kind}|{digest}"
        suffix = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        asset_id = f"asset.local.{suffix}"
        evidence_id = f"evidence.local.{suffix}"
        refs = list(source_refs or [])
        if not all(_is_nonempty_string(item) for item in refs):
            raise ResearchStoreError("source_refs entries must be non-empty strings")
        refs = list(dict.fromkeys([*refs, f"asset:{asset_id}"]))
        # Persist only a project-relative path or a controlled caller label;
        # never expose an external absolute path in the record.
        locator = {"path": locator_path,
                   "path_kind": "project_relative" if not locator_path.startswith("caller:") else "caller_label"}
        if citation_locator is not None:
            if not isinstance(citation_locator, dict) or not citation_locator:
                raise ResearchStoreError("citation_locator must be a non-empty object")
            locator["citation"] = copy.deepcopy(citation_locator)
        asset = {
            "schema_version": SCHEMA_VERSION, "type": "Asset", "id": asset_id,
            "revision": 1, "project_id": self.project_id,
            "scope": {"project_id": self.project_id}, "source_refs": refs,
            "asset_kind": material_kind, "locator": locator,
            "content_sha256": digest, "authority": authority, "status": "observed",
        }
        evidence = {
            "schema_version": SCHEMA_VERSION, "type": "Evidence", "id": evidence_id,
            "revision": 1, "project_id": self.project_id,
            "scope": {"project_id": self.project_id}, "source_refs": refs,
            "evidence_kind": material_kind, "asset_ref": asset_id,
            "locator": copy.deepcopy(locator), "status": "observed",
        }
        relations = [{
            "schema_version": SCHEMA_VERSION, "relationship_id": f"relation.local.{suffix}",
            "revision": 1, "project_id": self.project_id,
            "relation": "evidence_derived_from_asset", "from_id": evidence_id,
            "from_revision": 1, "to_id": asset_id, "to_revision": 1,
            "source_refs": refs,
        }]
        if source_documents_claim is not None:
            claim = self.latest_record(source_documents_claim, "Claim")
            if claim is None:
                raise ResearchStoreError("source_documents_claim must reference an existing Claim")
            relations.append({
                "schema_version": SCHEMA_VERSION, "relationship_id": f"relation.local.{suffix}.claim",
                "revision": 1, "project_id": self.project_id,
                "relation": "source_documents_claim", "from_id": evidence_id,
                "from_revision": 1, "to_id": claim["id"], "to_revision": claim["revision"],
                "source_refs": refs,
            })
        transaction = self.commit(
            f"register-local-material.{suffix}", {"role": "planning_agent", "model": "research-store"},
            [asset, evidence], relations,
        )
        return {"asset": copy.deepcopy(asset), "evidence": copy.deepcopy(evidence),
                "relationships": copy.deepcopy(relations), "transaction": transaction}

    def _latest(self, transactions: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records = self._latest_record_map(transactions)
        relationships: dict[str, dict[str, Any]] = {}
        for transaction in transactions:
            for relationship in transaction["relationships"]:
                if relationship["revision"] >= relationships.get(
                    relationship["relationship_id"], {"revision": 0}
                )["revision"]:
                    relationships[relationship["relationship_id"]] = relationship
        return [record for record in records.values() if record["type"] != "TaskState"], list(relationships.values())

    def rebuild_research_map(self, output: str | os.PathLike[str] | None = None) -> dict[str, Any]:
        output_path = None if output is None else (self.project_root / output).resolve()
        if output_path is not None and output_path != self.project_root and self.project_root not in output_path.parents:
            raise ResearchStoreError("research map output escapes project root")

        def build() -> dict[str, Any]:
            transactions = self._read_transactions()
            records, relationships = self._latest(transactions)
            return {
                "schema_version": SCHEMA_VERSION,
                "type": MAP_TYPE,
                "project_id": self.project_id,
                "nodes": sorted(records, key=lambda item: (item["type"], item["id"], item["revision"])),
                "edges": sorted(
                    relationships,
                    key=lambda item: (
                        item["relation"],
                        item["from_id"],
                        item["to_id"],
                        item["relationship_id"],
                        item["revision"],
                    ),
                ),
            }

        if output_path is None:
            return build()
        with self.writer("rebuild-map"):
            view = build()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = output_path.with_name(f".{output_path.name}.tmp")
            temporary.write_bytes(_pretty_bytes(view))
            with temporary.open("r+b") as stream:
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(str(temporary), str(output_path))
        return view
