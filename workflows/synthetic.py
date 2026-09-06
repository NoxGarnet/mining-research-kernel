"""A deliberately small second-domain workflow used by R5 acceptance.

The workflow is a provider/builder only. Task state, execution accounting,
records, Run Ledger, verification and derived views stay in the shared kernel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


WORKFLOW_ID = "mining_research_kernel.workflow.synthetic"
METHOD_IDS = (
    "mining_research_kernel.method.synthetic.static_check",
    "mining_research_kernel.method.synthetic.fake_execution",
)


def _kind(request: Mapping[str, Any]) -> str:
    value = request.get("task_type", "mining_research_kernel.task.static_check")
    return value.rsplit(".", 1)[-1].casefold() if isinstance(value, str) else ""


def _capability(providers: Mapping[str, Any], name: str) -> Mapping[str, Any] | None:
    value = providers.get(name)
    if value is None:
        return None
    value = value.capability() if hasattr(value, "capability") else value
    return value if isinstance(value, Mapping) else None


def build_synthetic_workflow_pack(project=None, request=None, providers=None, **kwargs):
    """Build a non-FLAC3D fixture pack with the same TaskEngine contract."""
    project = project if isinstance(project, Mapping) else {}
    request = request if isinstance(request, Mapping) else {}
    providers = providers if isinstance(providers, Mapping) else {}
    if not providers and isinstance(kwargs.get("provider_capabilities"), Mapping):
        providers = kwargs["provider_capabilities"]

    task_type = request.get("task_type", "mining_research_kernel.task.static_check")
    kind = _kind(request)
    selected = ["execution"] if kind in {"fake_execution", "execution"} else ["static_check"]
    explicit = request.get("verification_gates", request.get("needs", ()))
    if isinstance(explicit, str):
        explicit = [explicit]
    if isinstance(explicit, (list, tuple)):
        selected = list(dict.fromkeys([*selected, *(x for x in explicit if isinstance(x, str))]))

    execution_config = project.get("execution", {})
    configured = execution_config.get("provider", "disabled") if isinstance(execution_config, Mapping) else "disabled"
    execution_cap = _capability(providers, "execution") or _capability(providers, configured)
    statuses = {
        "static_check": {"gate_id": "static_check", "applicable": "static_check" in selected,
                         "status": "PENDING" if "static_check" in selected else "NOT_APPLICABLE",
                         "reason": "selected_for_task" if "static_check" in selected else "task_does_not_require_gate"},
        "execution": {"gate_id": "execution", "applicable": "execution" in selected,
                       "status": "PENDING" if "execution" in selected else "NOT_APPLICABLE",
                       "reason": "selected_for_task" if "execution" in selected else "task_does_not_require_gate"},
    }
    if "execution" in selected:
        if not execution_cap or not execution_cap.get("available", False):
            statuses["execution"].update(status="DISABLED", reason="execution_provider_disabled_or_unavailable")
        elif kind in {"fake_execution", "execution"}:
            statuses["execution"].update(status="READY")

    route_id = request.get("route_id", f"{WORKFLOW_ID}.route.default")
    route_ids = request.get("routes", [route_id])
    if isinstance(route_ids, str):
        route_ids = [route_ids]
    if not isinstance(route_ids, list) or not route_ids:
        route_ids = [f"{WORKFLOW_ID}.route.default"]
    default_tools = {"static_check": ["synthetic.static_check"],
                     "fake_execution": ["execution.fake"],
                     "execution": ["execution"]}.get(kind, [])
    requested_tools = request.get("allowed_tools", default_tools)
    return {
        "schema_version": 1,
        "type": "SyntheticWorkflowPack",
        "workflow_id": WORKFLOW_ID,
        "project_id": project.get("project_id", "unbound"),
        "product": "synthetic",
        "product_version": "fixture-1",
        "task_type": task_type,
        "method_ids": list(METHOD_IDS),
        "execution_provider": configured,
        "execution_authorized": bool(execution_cap and execution_cap.get("available", False)),
        "mutation_allowed": False,
        "read_order": ["existing_project", "synthetic_workflow", "exploratory_inputs"],
        "required_reads": [project.get("entry", "START.md"), project.get("baseline", "cases/main.dat")],
        "steps": ["read project contract", "inspect synthetic workflow state", "perform the selected bounded fixture action"],
        "verification_layers": ["static", "execution", "provenance"],
        "verification_gates": list(selected),
        "gate_statuses": statuses,
        "gates": statuses,
        "routes": list(route_ids),
        "documentation_required": False,
        "documentation_status": "NOT_APPLICABLE",
        "allowed_tools": list(requested_tools) if isinstance(requested_tools, list) else [],
        "writeback": ["run records", project.get("research_map", "research/map.json")],
        "writeback_targets": {"research_map": project.get("research_map", "research/map.json")},
    }


__all__ = ["WORKFLOW_ID", "build_synthetic_workflow_pack"]
