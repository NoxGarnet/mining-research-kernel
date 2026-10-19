"""Validate and atomically persist caller-supplied reading observations.

This module never opens a source, resolves a URL, or claims to verify reading.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.records import ResearchStore, WriterLockedError
from mining_research_kernel.r2_workflow import _record, _relationship, _sha256_json


_HEX = re.compile(r"^[0-9a-f]{64}$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z]:[\\/](?:[^\\/\s]+[\\/])*[^\\/\s]*", re.IGNORECASE)
_UNC_PATH = re.compile(r"\\\\[^\\/\s]+[\\/][^\\/\s]+")
_UNIX_PATH = re.compile(r"(?:^|\s)/(?:[^/\s]+/)+[^/\s]*")
_FILE_URL = re.compile(r"file:", re.IGNORECASE)
_TOP = {"schema_version", "kind", "origin", "captured_at", "source", "reader", "passages", "limitations"}
_SOURCE = {"source_id", "title", "doi", "url", "version", "source_kind", "source_sha256", "authority"}
_READER = {"tool", "method"}
_PASSAGE = {"locator", "status", "text_sha256", "excerpt", "limitations"}
_LOCATOR = {"kind", "value", "start_page", "end_page"}


@contextmanager
def _writer_retry(store: ResearchStore, operation_id: str):
    """Wait briefly for a competing identical/different operation to finish."""
    for attempt in range(100):
        lock = store.writer(operation_id)
        try:
            lock.__enter__()
            break
        except WriterLockedError:
            if attempt == 99:
                raise
            time.sleep(0.05)
    try:
        yield
    finally:
        lock.__exit__(None, None, None)


def _object(value: Any, keys: set[str], required: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    if set(value) - keys or required - set(value):
        raise ValueError(f"{label} has unknown or missing fields")
    return value


def _string(value: Any, label: str, limit: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or (not empty and not value.strip()) or len(value) > limit:
        raise ValueError(f"{label} must be a string of at most {limit} characters")
    if _WINDOWS_PATH.search(value) or _UNC_PATH.search(value) or _UNIX_PATH.search(value) or _FILE_URL.search(value):
        raise ValueError(f"{label} must not contain a local absolute path or file URL")
    return value


def _enum(value: Any, allowed: set[str], label: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ValueError(f"{label} has an unsupported value")
    return value


def _hash(value: Any, label: str, *, nullable: bool = True) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def validate_observation(data: Any) -> dict[str, Any]:
    """Return a normalized deep copy of a strict v1 reading observation."""
    top = _object(data, _TOP, _TOP, "observation")
    if type(top["schema_version"]) is not int or top["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    if top["kind"] != "reading_observation":
        raise ValueError("invalid observation kind or origin")
    origin = _enum(top["origin"], {"agent_supplied", "synthetic"}, "origin")
    captured = _string(top["captured_at"], "captured_at", 40)
    try:
        parsed_time = datetime.fromisoformat(captured.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("captured_at must be an ISO-8601 UTC timestamp") from exc
    if parsed_time.tzinfo is None or parsed_time.utcoffset().total_seconds() != 0:
        raise ValueError("captured_at must be UTC")

    src = _object(top["source"], _SOURCE, _SOURCE, "source")
    source_id = _string(src["source_id"], "source_id", 200)
    title = _string(src["title"], "title", 500)
    doi = src["doi"]
    if doi is not None:
        doi = _string(doi, "doi", 300).strip()
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.I)
        if not _DOI.fullmatch(doi):
            raise ValueError("doi must be a normalized DOI")
        doi = doi.lower()
    url = src["url"]
    if url is not None:
        url = _string(url, "url", 2048)
        if not re.match(r"^https?://[^\s]+$", url, re.I):
            raise ValueError("url must be an http(s) URL")
    version = src["version"]
    if version is not None:
        version = _string(version, "version", 200)
    source_kind = src["source_kind"]
    authority = src["authority"]
    source_kind = _enum(source_kind, {"local_pdf", "web_article", "local_text"}, "source_kind")
    authority = _enum(authority, {"original_publication", "derived", "unknown"}, "authority")
    source_hash = _hash(src["source_sha256"], "source_sha256")

    reader = _object(top["reader"], _READER, _READER, "reader")
    tool = _string(reader["tool"], "reader.tool", 120)
    method = reader["method"]
    method = _enum(method, {"text", "visual", "ocr", "mixed"}, "reader.method")
    passages = top["passages"]
    if not isinstance(passages, list) or not 1 <= len(passages) <= 20:
        raise ValueError("passages must contain 1 to 20 entries")
    normalized_passages = []
    seen = set()
    for i, raw in enumerate(passages):
        p = _object(raw, _PASSAGE, _PASSAGE, f"passages[{i}]")
        loc = _object(p["locator"], _LOCATOR, {"kind", "value"}, f"passages[{i}].locator")
        lk = loc["kind"]
        lk = _enum(lk, {"pdf_pages", "section", "figure", "table", "lines"}, "locator.kind")
        if (lk == "pdf_pages") != ("start_page" in loc and "end_page" in loc):
            raise ValueError("pdf_pages requires page bounds; other locator kinds forbid them")
        if lk != "pdf_pages" and set(loc) != {"kind", "value"}:
            raise ValueError("page bounds are only valid for pdf_pages")
        value = _string(loc["value"], "locator.value", 300)
        if lk == "pdf_pages":
            start, end = loc["start_page"], loc["end_page"]
            if type(start) is not int or type(end) is not int or not (1 <= start <= end <= 100000):
                raise ValueError("page bounds must be ordered positive 1-based integers")
            locator = {"kind": lk, "value": value, "start_page": start, "end_page": end}
        else:
            locator = {"kind": lk, "value": value}
        if value in seen:
            raise ValueError("locator.value must be unique within a capture")
        seen.add(value)
        status = p["status"]
        excerpt = _string(p["excerpt"], f"passages[{i}].excerpt", 1000, empty=True)
        text_hash = _hash(p["text_sha256"], f"passages[{i}].text_sha256")
        limits = p["limitations"]
        if not isinstance(limits, list) or not 1 <= len(limits) <= 20:
            raise ValueError("passage limitations must explicitly preserve at least one limitation")
        limits = [_string(x, "passage limitation", 300) for x in limits]
        if status == "read":
            if not excerpt.strip():
                raise ValueError("read passage requires a non-empty excerpt")
        elif status == "unavailable":
            if excerpt or text_hash is not None:
                raise ValueError("unavailable passage cannot contain excerpt or text hash")
        else:
            raise ValueError("passage status must be read or unavailable")
        normalized_passages.append({"locator": locator, "status": status,
                                    "text_sha256": text_hash, "excerpt": excerpt,
                                    "limitations": limits})
    limits = top["limitations"]
    if not isinstance(limits, list) or not 1 <= len(limits) <= 34:
        raise ValueError("root limitations must explicitly preserve at least one limitation")
    limits = [_string(x, "limitation", 500) for x in limits]
    # Preserve uncertainty explicitly so downstream reports cannot mistake a
    # caller supplied excerpt for a verified source/version or full reading.
    if version is None:
        limits.append("source_version_unknown")
    if source_hash is None:
        limits.append("original_source_sha256_unknown")
    if any(p["status"] == "unavailable" for p in normalized_passages):
        limits.append("one_or_more_passages_unavailable")
    if any(p["text_sha256"] is None for p in normalized_passages if p["status"] == "read"):
        limits.append("one_or_more_reading_text_sha256_unknown")
    limits = list(dict.fromkeys(limits))
    if len(limits) > 34:
        raise ValueError("limitations exceed the 34-item normalized maximum after required gaps")
    normalized = {"schema_version": 1, "kind": "reading_observation", "origin": origin,
        "captured_at": captured,
        "source": {"source_id": source_id, "title": title, "doi": doi, "url": url,
                   "version": version, "source_kind": source_kind, "source_sha256": source_hash,
                   "authority": authority},
        "reader": {"tool": tool, "method": method}, "passages": normalized_passages,
        "limitations": limits}
    return copy.deepcopy(normalized)


def record_reading_observation(project_root: str | Path, *, observation_id: str,
                               observation: Any, task_context: str = "production") -> dict[str, Any]:
    """Atomically persist one immutable embedded Asset/Evidence pair."""
    if not isinstance(observation_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", observation_id):
        raise ValueError("observation_id must be a stable record-safe identifier")
    task_context = _enum(task_context, {"production", "synthetic"}, "task_context")
    normalized = validate_observation(observation)
    if normalized["origin"] == "synthetic" and task_context != "synthetic":
        raise ValueError("synthetic observation cannot be recorded in production")
    request = {"observation_id": observation_id, "observation": normalized, "task_context": task_context}
    request_hash = _sha256_json(request)
    suffix = hashlib.sha256(observation_id.encode("utf-8")).hexdigest()[:24]
    asset_id, evidence_id = f"reading.asset.{suffix}", f"reading.evidence.{suffix}"
    operation_id = f"reading.{suffix}"
    store = ResearchStore(project_root)
    source_refs = [f"reading_observation:{observation_id}", f"asset:{asset_id}", f"evidence:{evidence_id}"]
    payload = {"kind": "reading_observation_record", "request": request,
               "provenance": {"producer": "agent_supplied", "request_sha256": request_hash,
                              "source_revalidated": False, "query_performed": False}}
    payload_hash = _sha256_json(payload)
    locator = {"path": f"record:{asset_id}#payload", "path_kind": "record_embedded",
               "record_id": asset_id, "field": "payload", "embedded_payload": "payload",
               "caller_label": f"reading-observation:{observation_id}"}
    asset = _record("Asset", asset_id, store.project_id, source_refs, asset_kind="reading_observation",
                    locator=locator, content_sha256=payload_hash, authority="derived", status="observed",
                    payload=payload)
    evidence = _record("Evidence", evidence_id, store.project_id, source_refs,
                       evidence_kind="reading_observation", asset_ref=asset_id,
                       locator=locator, status="observed")
    relation = _relationship(f"reading.relation.{suffix}", "evidence_derived_from_asset",
                             evidence, asset, store.project_id, source_refs)
    with _writer_retry(store, operation_id):
        prior = store.latest_record(asset_id, "Asset")
        if prior is not None:
            prior_payload = prior.get("payload")
            prior_request = prior_payload.get("request") if isinstance(prior_payload, dict) else None
            if prior_request != request:
                raise ValueError(f"observation_id already records a different request: {observation_id}")
            if (prior != asset or not isinstance(prior.get("payload"), dict)
                    or _sha256_json(prior["payload"]) != payload_hash):
                raise ValueError("existing reading observation Asset is damaged or inconsistent")
            if prior.get("asset_kind") != "reading_observation" or prior.get("authority") != "derived":
                raise ValueError("existing reading observation Asset has invalid kind or authority")
            ev = store.latest_record(evidence_id, "Evidence")
            if ev != evidence or ev is None or ev.get("asset_ref") != asset_id:
                raise ValueError("existing reading observation Evidence is damaged or inconsistent")
            relations = [relation_value for tx in store.list_transactions()
                         for relation_value in tx.get("relationships", [])
                         if relation_value.get("relationship_id") == relation["relationship_id"]]
            if relations != [relation]:
                raise ValueError("existing reading observation Asset/Evidence relationship is damaged")
            if prior.get("content_sha256") != payload_hash:
                raise ValueError("existing reading observation payload hash is inconsistent")
            return {"status": "replayed", "asset_ref": asset_id, "evidence_ref": evidence_id,
                    "observation_id": observation_id, "query_performed": False,
                    "source_revalidated": False, "reading_status": _reading_status(normalized)}
        store.commit(operation_id, {"role": "host", "model": "reading_observation"},
                     [asset, evidence], [relation], lock_held=True)
    return {"status": "recorded", "asset_ref": asset_id, "evidence_ref": evidence_id,
            "observation_id": observation_id, "query_performed": False,
            "source_revalidated": False, "reading_status": _reading_status(normalized)}


def _reading_status(observation: Mapping[str, Any]) -> str:
    read = sum(p["status"] == "read" for p in observation["passages"])
    if not read:
        return "UNAVAILABLE"
    if read != len(observation["passages"]):
        return "PARTIAL"
    return "READ_WITH_LIMITS"
