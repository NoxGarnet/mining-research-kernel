"""Bounded, read-only capture of explicit Itasca output files."""
from __future__ import annotations

import base64
import hashlib
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping

from mining_research_kernel.artifacts import (
    _absolute_without_follow, _is_reparse_point, _reject_reparse_chain,
)
from mining_research_kernel.records import ResearchStore, ResearchStoreError
from mining_research_kernel.r2_workflow import _edge_id, _record, _relationship

MAX_OUTPUT_BYTES = 1024 * 1024
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
_PRODUCER = {"role": "host", "model": "itasca_outputs"}


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        raise ValueError(f"{field} must be a bounded ASCII identifier")
    return value


def _relative_parts(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, str) or not value or len(value) > 4096:
        raise ValueError(f"{field} must be a non-empty project-relative path")
    if "\\" in value or value.startswith("/") or ":" in value:
        raise ValueError(f"{field} must use project-relative POSIX path syntax")
    parts = tuple(value.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} contains an unsafe path component")
    return parts


def _check_chain(root: Path, target: Path) -> None:
    """Reject symlinks and Windows reparse points in every selected component."""
    current = root
    if _is_reparse_point(current):
        raise ValueError("project_root cannot be a symlink or reparse point")
    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Itasca output path escapes project_root") from exc
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current) and _is_reparse_point(current):
            raise ValueError(f"Itasca output path cannot pass through a symlink or reparse point: {current}")


def _read_snapshot(root: Path, plan: Mapping[str, Any], path_text: str, kind: str) -> tuple[bytes, str]:
    output_parts = _relative_parts(plan.get("output_root"), "plan.output_root")
    file_parts = _relative_parts(path_text, "path")
    if file_parts[:len(output_parts)] != output_parts or len(file_parts) <= len(output_parts):
        raise ValueError("path must identify a file beneath plan.output_root")
    target = root.joinpath(*file_parts)
    _check_chain(root, target)
    try:
        before = target.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Itasca output must be a regular file")
        if before.st_size > MAX_OUTPUT_BYTES:
            raise ValueError(f"Itasca output exceeds maximum size of {MAX_OUTPUT_BYTES} bytes")
        with target.open("rb") as stream:
            raw = stream.read(MAX_OUTPUT_BYTES + 1)
            after = os.fstat(stream.fileno())
    except OSError as exc:
        raise ValueError(f"cannot read Itasca output: {exc}") from exc
    if len(raw) > MAX_OUTPUT_BYTES:
        raise ValueError(f"Itasca output exceeds maximum size of {MAX_OUTPUT_BYTES} bytes")
    if not stat.S_ISREG(after.st_mode) or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
        raise ValueError("Itasca output changed while being read")
    _check_chain(root, target)
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Itasca output must be strict UTF-8 text") from exc
    if kind == "csv":
        import csv
        import io
        try:
            rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
        except csv.Error as exc:
            raise ValueError(f"Itasca CSV output is malformed: {exc}") from exc
        if not rows:
            raise ValueError("Itasca CSV output must not be empty")
    return raw, hashlib.sha256(raw).hexdigest()


def _load_run(project_root: Path, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    # Lazy import avoids the report/output loader cycle.
    from mining_research_kernel.itasca_execution import load_itasca_run

    loaded = load_itasca_run(project_root, run_id)
    if not isinstance(loaded, Mapping):
        raise ValueError("load_itasca_run returned an invalid result")
    run_ref, plan = loaded.get("run_ref"), loaded.get("plan")
    if not isinstance(run_ref, Mapping) or not isinstance(plan, Mapping):
        raise ValueError("Itasca run result must contain run_ref and plan objects")
    if plan.get("schema_version") != 1 or plan.get("kind") != "itasca_execution_plan":
        raise ValueError("RunReference is not bound to an Itasca execution plan")
    if plan.get("run_id") != run_id or run_ref.get("run_id") != run_id:
        raise ValueError("Itasca run id does not match the selected RunReference")
    if run_ref.get("type") != "RunReference" or not isinstance(run_ref.get("revision"), int):
        raise ValueError("Itasca run_ref must be a persisted RunReference record")
    if run_ref.get("status") not in {"completed", "failed", "interrupted"}:
        raise ValueError("Itasca outputs can be captured only after a terminal run status")
    if plan.get("task_context") not in {"production", "synthetic"}:
        raise ValueError("Itasca plan has an invalid task_context")
    if plan.get("origin") not in {"provided_script", "synthetic"}:
        raise ValueError("Itasca plan has an invalid origin")
    if (plan.get("task_context") == "synthetic") != (plan.get("origin") == "synthetic"):
        raise ValueError("Itasca plan origin does not match its task_context")
    return dict(run_ref), dict(plan)


def _stored_operation(store: ResearchStore, operation_record_id: str, *, operation_id: str,
                      run_id: str, path: str, kind: str, source_path: Path,
                      root: Path) -> dict[str, Any] | None:
    for transaction in store.list_transactions():
        if transaction.get("operation_id") != operation_record_id:
            continue
        records = transaction.get("records", [])
        assets = [record for record in records if record.get("type") == "Asset" and record.get("asset_kind") == "itasca_output"]
        evidences = [record for record in records if record.get("type") == "Evidence" and record.get("evidence_kind") == "itasca_output"]
        if len(assets) != 1 or len(evidences) != 1:
            raise ValueError("existing Itasca output operation is damaged")
        asset, evidence = assets[0], evidences[0]
        payload = asset.get("payload")
        if (not isinstance(payload, dict) or payload.get("operation_id") != operation_id
                or payload.get("run_id") != run_id or payload.get("path") != path
                or payload.get("output_kind") != kind
                or evidence.get("asset_ref") != asset.get("id")
                or payload.get("evidence_id") != evidence.get("id")
                or hashlib.sha256(_canonical(payload)).hexdigest() != asset.get("content_sha256")):
            raise ValueError("operation_id was already used for conflicting or damaged Itasca output")
        decoded = _decode_snapshot(payload)
        if hashlib.sha256(decoded).hexdigest() != payload.get("sha256"):
            raise ValueError("stored Itasca output snapshot hash mismatch")
        if payload.get("size_bytes") != len(decoded):
            raise ValueError("stored Itasca output snapshot size mismatch")
        _check_chain(root, source_path)
        if os.path.lexists(source_path):
            current, current_hash = _read_snapshot(root, {"output_root": payload.get("output_root")}, path, kind)
            if current_hash != payload.get("sha256") or current != decoded:
                raise ValueError("operation_id was replayed after the Itasca output bytes changed")
        if not any(edge.get("relation") == "run_produces_evidence"
                   and edge.get("from_id") == payload.get("run_ref_id")
                   and edge.get("from_revision") == payload.get("run_revision")
                   and edge.get("to_id") == evidence.get("id") for edge in transaction.get("relationships", [])):
            raise ValueError("stored Itasca output is missing its run relationship")
        if not any(edge.get("relation") == "evidence_derived_from_asset"
                   and edge.get("from_id") == evidence.get("id")
                   and edge.get("to_id") == asset.get("id")
                   for edge in transaction.get("relationships", [])):
            raise ValueError("stored Itasca output is missing its asset relationship")
        return _receipt(asset, evidence, payload, replayed=True)
    return None


def _canonical(value: Any) -> bytes:
    import json
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _decode_snapshot(payload: Mapping[str, Any]) -> bytes:
    try:
        encoded = payload.get("bytes_base64")
        if not isinstance(encoded, str):
            raise ValueError
        return base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("stored Itasca output snapshot is damaged") from exc


def _receipt(asset: Mapping[str, Any], evidence: Mapping[str, Any], payload: Mapping[str, Any], *, replayed: bool) -> dict[str, Any]:
    return {"asset_ref": asset["id"], "evidence_ref": evidence["id"],
            "run_ref": payload["run_ref_id"], "run_ref_id": payload["run_ref_id"],
            "run_revision": payload["run_revision"], "run_id": payload["run_id"],
            "path": payload["path"], "kind": payload["output_kind"], "sha256": payload["sha256"],
            "size_bytes": payload["size_bytes"], "replayed": replayed,
            "diagnostic_only": payload["diagnostic_only"],
            "provenance_limit": "caller-association-not-authenticated"}


def capture_itasca_output(project_root: str | os.PathLike[str], *, run_id: str, operation_id: str,
                          path: str, kind: str = "csv") -> dict[str, Any]:
    """Embed one explicitly selected completed-run output as immutable evidence.

    Caller association records which RunReference the caller selected; it does
    not authenticate that the file was produced by the referenced script.
    """
    raw_root = _absolute_without_follow(project_root)
    _reject_reparse_chain(raw_root, "project_root")
    root = raw_root.resolve()
    run_id = _id(run_id, "run_id")
    operation_id = _id(operation_id, "operation_id")
    if kind not in {"csv", "log", "text"}:
        raise ValueError("kind must be csv, log, or text")
    if not isinstance(path, str):
        raise ValueError("path must be a project-relative string")
    run_ref, plan = _load_run(root, run_id)
    if kind == "csv" and run_ref["status"] != "completed":
        raise ValueError("CSV outputs require a completed Itasca run")
    if kind == "csv" and plan.get("task_context") == "production" and plan.get("origin") == "synthetic":
        raise ValueError("synthetic Itasca execution cannot produce production CSV evidence")
    store = ResearchStore(root)
    output_parts = _relative_parts(plan.get("output_root"), "plan.output_root")
    path_parts = _relative_parts(path, "path")
    if path_parts[:len(output_parts)] != output_parts or len(path_parts) <= len(output_parts):
        raise ValueError("path must identify a file beneath plan.output_root")
    source_path = root.joinpath(*path_parts)
    operation_record_id = "itasca-output." + hashlib.sha256(operation_id.encode("ascii")).hexdigest()[:32]
    replay = _stored_operation(store, operation_record_id, operation_id=operation_id,
        run_id=run_id, path=path, kind=kind, source_path=source_path, root=root)
    if replay is not None:
        return replay
    latest = store.latest_record(run_ref["id"], "RunReference")
    if latest is None or latest.get("revision") != run_ref["revision"]:
        raise ValueError("RunReference changed while preparing output capture")
    raw, digest = _read_snapshot(root, plan, path, kind)
    request = {"run_ref_id": run_ref["id"], "run_revision": run_ref["revision"], "run_id": run_id,
               "path": path, "kind": kind, "sha256": digest, "size_bytes": len(raw)}
    request_hash = hashlib.sha256(_canonical(request)).hexdigest()
    suffix = hashlib.sha256((store.project_id + "|" + operation_id).encode("utf-8")).hexdigest()[:32]
    asset_id, evidence_id = "itasca.out." + suffix, "evidence.itasca.out." + suffix
    payload = {"schema_version": 1, "kind": "itasca_output_snapshot", "run_ref_id": run_ref["id"],
               "run_revision": run_ref["revision"], "task_context": plan["task_context"],
               "origin": plan["origin"], "run_id": run_id, "path": path, "sha256": digest,
               "output_kind": kind, "size_bytes": len(raw), "bytes_base64": base64.b64encode(raw).decode("ascii"),
               "diagnostic_only": run_ref["status"] in {"failed", "interrupted"},
               "provenance_limit": "caller-association-not-authenticated", "request_sha256": request_hash,
               "operation_id": operation_id, "output_root": plan["output_root"],
               "evidence_id": evidence_id}
    source_refs = [f"run:{run_id}", f"runref:{run_ref['id']}", f"asset:{asset_id}", f"evidence:{evidence_id}"]
    asset = _record("Asset", asset_id, store.project_id, source_refs, asset_kind="itasca_output",
                    locator={"path": f"record:{asset_id}#payload", "path_kind": "record_embedded",
                             "source_path": path}, content_sha256=hashlib.sha256(_canonical(payload)).hexdigest(),
                    authority="derived", status="observed", payload=payload)
    evidence = _record("Evidence", evidence_id, store.project_id, source_refs,
                       evidence_kind="itasca_output", asset_ref=asset_id,
                       locator={"run_id": run_id, "path": path, "kind": kind}, status="observed")
    edges = [
        _relationship(_edge_id(operation_id, "run-output-evidence"), "run_produces_evidence", run_ref, evidence,
                      store.project_id, source_refs),
        _relationship(_edge_id(operation_id, "output-evidence-asset"), "evidence_derived_from_asset", evidence, asset,
                      store.project_id, source_refs),
    ]
    store.commit(operation_record_id, _PRODUCER, [asset, evidence], edges,
                 expected_revisions={run_ref["id"]: run_ref["revision"]})
    return _receipt(asset, evidence, payload, replayed=False)


__all__ = ["capture_itasca_output", "MAX_OUTPUT_BYTES"]
