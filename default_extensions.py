"""Application composition root for the built-in extensions.

Concrete imports intentionally stop here.  The package contracts and generic
services remain independent of these choices.
"""
from __future__ import annotations

from pathlib import Path

from mining_research_kernel.registry import ExtensionRecord, ExtensionRegistry


DEFAULT_REGISTRY = ExtensionRegistry((
    ExtensionRecord(
        "mining_research_kernel.project.flac3d", "project",
        frozenset({"discover", "read_only"}), "adapters.flac3d:discover"),
    ExtensionRecord(
        "mining_research_kernel.project.ceramsite", "project",
        frozenset({"discover", "read_only"}), "adapters.ceramsite:discover"),
    ExtensionRecord(
        "mining_research_kernel.source.zotero_readonly", "source",
        frozenset({"discover", "inspect", "read_only"}),
        "adapters.zotero_mcp_readonly:dispatch"),
    ExtensionRecord(
        "mining_research_kernel.workflow.flac3d", "workflow",
        frozenset({"build", "read_only"}), "workflows.flac3d:build_flac3d_workflow_pack"),
    ExtensionRecord(
        "mining_research_kernel.documentation.default", "documentation",
        frozenset({"syntax_lookup", "syntax_citation"}),
        "providers.documentation:resolve_documentation"),
), aliases={
    "flac3d_coal_roadway": "mining_research_kernel.project.flac3d",
    "ceramsite_research": "mining_research_kernel.project.ceramsite",
    "zotero_mcp_readonly": "mining_research_kernel.source.zotero_readonly",
})


def registry_for_workspace(workspace: Path) -> ExtensionRegistry:
    """Select a configured project adapter at the composition boundary."""
    if (workspace / "flac3d_project.yaml").is_file():
        project = DEFAULT_REGISTRY.record_for("mining_research_kernel.project.flac3d")
        records = (project,) + tuple(record for record in DEFAULT_REGISTRY.records
                                     if record.extension_kind != "project")
        ids = {record.extension_id for record in records}
        aliases = {alias: target for alias, target in DEFAULT_REGISTRY.aliases.items()
                   if target in ids}
        return ExtensionRegistry(records, aliases=aliases)
    return DEFAULT_REGISTRY
