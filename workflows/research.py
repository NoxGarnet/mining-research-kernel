"""Domain-neutral, read-only evidence review using the existing TaskEngine."""
from __future__ import annotations

from collections.abc import Mapping


WORKFLOW_ID = "mining_research_kernel.workflow.research"
METHOD_ID = "mining_research_kernel.method.research.evidence_review"


def build_research_workflow_pack(project=None, request=None, providers=None, **kwargs):
    """Describe evidence review without implying a solver or domain validator."""
    project = project if isinstance(project, Mapping) else {}
    request = request if isinstance(request, Mapping) else {}
    task_type = request.get("task_type", "mining_research_kernel.task.evidence_review")
    if not isinstance(task_type, str) or task_type.rsplit(".", 1)[-1] != "evidence_review":
        raise ValueError("research workflow supports only evidence_review tasks")
    gates = request.get("verification_gates", request.get("needs", []))
    if gates:
        raise ValueError("research evidence review does not implement verification gates")
    tools = request.get("allowed_tools", ["evidence.read_only"])
    if not isinstance(tools, list) or any(tool != "evidence.read_only" for tool in tools):
        raise ValueError("research workflow allows only evidence.read_only")
    route = request.get("route_id", f"{WORKFLOW_ID}.route.default")
    routes = request.get("routes", [route])
    if not isinstance(routes, list) or not routes:
        raise ValueError("research workflow requires explicit route identifiers")
    return {
        "schema_version": 1,
        "type": "ResearchWorkflowPack",
        "workflow_id": WORKFLOW_ID,
        "project_id": project.get("project_id", "unbound"),
        "product": project.get("product", "research"),
        "product_version": project.get("product_version", "unknown"),
        "task_type": task_type,
        "method_ids": [METHOD_ID],
        "execution_provider": "disabled",
        "execution_authorized": False,
        "mutation_allowed": False,
        "read_order": ["project_entry", "selected_materials"],
        "required_reads": [],
        "steps": ["read selected evidence", "record judgment and limits"],
        "verification_layers": [],
        "verification_gates": [],
        "gate_statuses": {},
        "gates": {},
        "capability_statuses": {
            "evidence_review": {
                "capability_id": METHOD_ID,
                "available": True,
                "state": "read_only_material_linking",
                "reason": "selected_materials_and_limits_are_explicit",
                "resume_condition": "provide the evidence needed for this question",
                "scope": "read_only",
            },
        },
        "routes": list(routes),
        "documentation_required": False,
        "documentation_status": "NOT_APPLICABLE",
        "allowed_tools": list(tools),
        "writeback": ["research/records"],
        "writeback_targets": {"research_map": project.get("research_map", "research/map.json")},
    }
