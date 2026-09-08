"""Side-effect-free disabled and fixture execution providers."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _request_operation(request: Mapping[str, Any]) -> str:
    operation = request.get("operation", request.get("mode", "execute"))
    return operation if isinstance(operation, str) else ""


class DisabledExecutionProvider:
    """A visible, fail-closed provider selected by default."""

    provider_id = "mining_research_kernel.execution.disabled"

    def capability(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "type": "ProviderCapability", "provider_id": self.provider_id,
            "provider_kind": "execution", "available": False, "host_local": True,
            "capabilities": [], "product_version": None, "authorization_required": True,
            "last_checked": None, "diagnostics": ["disabled_by_default"], "status": "disabled",
        }

    def supports(self, request: Mapping[str, Any]) -> bool:
        return False

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        operation = _request_operation(request)
        return {
            "schema_version": 1, "type": "ExecutionResult", "provider_id": self.provider_id,
            "provider": self.provider_id, "status": "UNAVAILABLE", "stop_reason": "execution_provider_disabled",
            "operation": operation, "side_effect": "none", "input_digest": _digest(request),
            "output": None,
        }

    dispatch = execute


class FakeExecutionProvider:
    """Deterministic execution over explicitly supplied synthetic fixtures."""

    provider_id = "mining_research_kernel.execution.fake"

    def __init__(self) -> None:
        self.dispatches: list[dict[str, Any]] = []

    def capability(self) -> dict[str, Any]:
        return {
            "schema_version": 1, "type": "ProviderCapability", "provider_id": self.provider_id,
            "provider_kind": "execution", "available": True, "host_local": True,
            "capabilities": ["read", "execute"], "product_version": "synthetic",
            "authorization_required": False, "last_checked": None,
            "diagnostics": ["synthetic_fixture_only"], "status": "available",
        }

    def supports(self, request: Mapping[str, Any]) -> bool:
        if not isinstance(request, Mapping) or _request_operation(request) not in {"read", "execute", "mutate"}:
            return False
        if _request_operation(request) == "mutate":
            return False
        context = request.get("task_context", request.get("context", ""))
        task_type = str(request.get("task_type", "")).rsplit(".", 1)[-1].casefold()
        fixture_context = context == "synthetic" or (
            bool(request.get("fixture_id")) and request.get("fixture_kind") in {"static", "synthetic"}
        )
        return fixture_context and task_type in {
            "static_check", "fake_execution", "execution", "fixture_execution", "",
        }

    def execute(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(request, Mapping):
            return {"schema_version": 1, "type": "ExecutionResult", "provider_id": self.provider_id,
                    "status": "REJECTED", "stop_reason": "request_must_be_mapping",
                    "operation": "", "side_effect": "none", "input_digest": _digest(request), "output": None}
        operation = _request_operation(request)
        digest = _digest(request)
        fixture_id = request.get("fixture_id", "synthetic.default")
        base = {"schema_version": 1, "type": "ExecutionResult", "provider_id": self.provider_id,
                "provider": self.provider_id, "status": "COMPLETED", "operation": operation, "side_effect": "none",
                "fixture_id": fixture_id, "fixture_identity": str(fixture_id),
                "input_digest": digest}
        if operation == "mutate":
            base.update(status="REJECTED", stop_reason="mutation_denied", output=None)
        elif operation not in {"read", "execute"}:
            base.update(status="REJECTED", stop_reason="operation_unsupported", output=None)
        elif not self.supports(request):
            base.update(status="UNAVAILABLE", stop_reason="synthetic_or_static_fixture_required", output=None)
        else:
            base["output"] = {"fixture_id": str(fixture_id), "input_digest": digest,
                              "observation": "deterministic_synthetic_result"}
        self.dispatches.append(deepcopy(base))
        return base

    dispatch = execute


__all__ = ["DisabledExecutionProvider", "FakeExecutionProvider"]
