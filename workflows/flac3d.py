"""Project-aware, bounded FLAC3D workflow routing.

The pack is deliberately a data-only planning result. It selects the small
set of checks relevant to the requested task; it never starts FLAC3D or
changes a project.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

WORKFLOW_ID = "mining_research_kernel.workflow.flac3d"
METHOD_IDS = (
    "mining_research_kernel.method.flac3d.syntax_verification",
    "mining_research_kernel.method.flac3d.static_check",
    "mining_research_kernel.method.flac3d.fake_execution",
)

_LEGACY_LAYERS = ("mcp_connectivity", "execution", "numerical", "physical", "engineering")
_GATE_IDS = _LEGACY_LAYERS + ("documentation", "static_check")


def _provider_value(providers: Mapping[str, Any], name: str) -> Any:
    value = providers.get(name)
    if value is None:
        return None
    if hasattr(value, "capability"):
        return value.capability()
    return value


def _task_kind(request: Mapping[str, Any]) -> str:
    value = request.get("task_type", request.get("type", "mining_research_kernel.task.syntax_change"))
    if not isinstance(value, str):
        return ""
    return value.rsplit(".", 1)[-1].casefold()


def build_flac3d_workflow_pack(project=None, request=None, providers=None, **kwargs):
    """Build a workflow pack from project, task and provider capabilities.

    ``providers`` accepts provider instances or their capability mappings.
    The legacy no-argument shape remains available for existing callers.
    """
    project = project if isinstance(project, Mapping) else {}
    request = request if isinstance(request, Mapping) else {}
    providers = providers if isinstance(providers, Mapping) else {}
    if not providers and isinstance(kwargs.get("provider_capabilities"), Mapping):
        providers = kwargs["provider_capabilities"]

    task_type = request.get("task_type", "mining_research_kernel.task.syntax_change")
    kind = _task_kind(request)
    product = project.get("product", "flac3d")
    product_version = project.get("product_version", "unknown")
    project_id = project.get("project_id", "unbound")
    entry = project.get("entry", "START.md")
    baseline = project.get("baseline", "cases/main.dat")
    execution_config = project.get("execution", {})
    configured_execution = execution_config.get("provider", "disabled") if isinstance(execution_config, Mapping) else "disabled"
    execution_cap = _provider_value(providers, "execution") or _provider_value(providers, configured_execution)
    documentation_cap = _provider_value(providers, "documentation")

    selected = {
        "syntax_change": ["documentation"],
        "static_check": ["static_check"],
        "fake_execution": ["execution"],
        "execution": ["execution"],
    }.get(kind, [])
    explicit = request.get("verification_gates", request.get("needs", ()))
    if isinstance(explicit, str):
        explicit = [explicit]
    if isinstance(explicit, (list, tuple)):
        selected = list(dict.fromkeys([*selected, *(x for x in explicit if isinstance(x, str))]))

    statuses = {}
    for gate in _GATE_IDS:
        statuses[gate] = {
            "gate_id": gate,
            "applicable": gate in selected,
            "status": "PENDING" if gate in selected else "NOT_APPLICABLE",
            "reason": "selected_for_task" if gate in selected else "task_does_not_require_gate",
        }
    if not documentation_cap or not documentation_cap.get("available", False):
        statuses["documentation"] = {
            "gate_id": "documentation", "applicable": "documentation" in selected,
            "status": "CANNOT_VERIFY" if "documentation" in selected else "NOT_APPLICABLE",
            "reason": "documentation_provider_unavailable" if "documentation" in selected else "task_does_not_require_gate",
        }
    if "execution" in statuses and "execution" in selected:
        if not execution_cap or not execution_cap.get("available", False):
            statuses["execution"]["status"] = "DISABLED"
            statuses["execution"]["reason"] = "execution_provider_disabled_or_unavailable"
        elif kind in {"fake_execution", "execution"}:
            statuses["execution"]["status"] = "READY"

    route_id = request.get("route_id", f"{WORKFLOW_ID}.route.default")
    route_ids = request.get("routes", [route_id])
    if isinstance(route_ids, str):
        route_ids = [route_ids]
    if not isinstance(route_ids, list) or not route_ids:
        route_ids = [f"{WORKFLOW_ID}.route.default"]

    read_order = ["existing_project", "known_workflow", "exploratory_inputs"]
    if "documentation" in selected:
        read_order.append("syntax_verification")
    default_tools = {
        "syntax_change": ["documentation.verify_syntax"],
        "static_check": ["static_check"],
        "fake_execution": ["execution.fake"],
        "execution": ["execution"],
    }.get(kind, [])
    requested_tools = request.get("allowed_tools", default_tools)
    return {
        "schema_version": 1,
        "type": "FLAC3DWorkflowPack",
        "workflow_id": WORKFLOW_ID,
        "project_id": project_id,
        "product": product,
        "product_version": product_version,
        "task_type": task_type,
        "method_ids": list(METHOD_IDS),
        "execution_provider": configured_execution,
        "execution_authorized": bool(project.get("execution_authorized", False)) and configured_execution != "disabled",
        "mutation_allowed": False,
        "read_order": read_order,
        "required_reads": [entry, baseline],
        "steps": ["read project entry and baseline", "inspect known workflow and failures",
                   "label exploratory assumptions", "perform the selected task action"],
        "verification_layers": list(_LEGACY_LAYERS),
        "verification_gates": list(selected),
        "gate_statuses": statuses,
        "gates": statuses,
        "routes": list(route_ids),
        "documentation_required": "documentation" in selected,
        "documentation_status": request.get("documentation_status", "NOT_APPLICABLE"),
        "allowed_tools": list(requested_tools) if isinstance(requested_tools, list) else [],
        "writeback": [project.get("errors", "docs/error-journal.jsonl"),
                      project.get("decisions", "docs/decisions.jsonl"),
                      "run records", project.get("research_map", "research/map.json")],
        "writeback_targets": {
            "errors": project.get("errors", "docs/error-journal.jsonl"),
            "decisions": project.get("decisions", "docs/decisions.jsonl"),
            "research_map": project.get("research_map", "research/map.json"),
        },
    }
