"""Compatibility facade for the pre-package registry API.

New code should use :mod:`mining_research_kernel.registry` and the strict
application registry in :mod:`default_extensions`.  Legacy callers retain
their unnamespaced constructor and identifiers here only.
"""
from __future__ import annotations

from typing import Any

from default_extensions import DEFAULT_REGISTRY
from mining_research_kernel.registry import (
    ExtensionRecord,
    ExtensionRegistry as _ExtensionRegistry,
    RegistryError,
)

_LEGACY_ALLOWED_CAPABILITIES = frozenset({"discover", "inspect", "validate", "read_only"})
_LEGACY_ALLOWED_KINDS = frozenset({
    "project", "source", "tool", "knowledge", "workflow",
    "project_adapter", "workflow_pack", "documentation_provider", "source_provider",
    "execution_provider", "knowledge_provider", "transform_provider", "cognition_policy",
    "artifact_store", "agent_host_adapter",
})


class ExtensionRegistry(_ExtensionRegistry):
    """Legacy-mode registry used only by existing callers and fixtures."""

    def __init__(self, records=()):
        super().__init__(records, strict_ids=False)

    @staticmethod
    def _record_errors(record, *, strict_ids=False):
        errors = _ExtensionRegistry._record_errors(record, strict_ids=strict_ids)
        if not isinstance(record, ExtensionRecord):
            return errors

        kind_errors = [error for error in errors if error.startswith("unknown kind:")]
        if record.extension_kind in _LEGACY_ALLOWED_KINDS:
            kind_errors = []
        capability_errors = []
        capabilities = record.capabilities
        if not isinstance(capabilities, (set, frozenset, tuple, list)):
            capability_errors = ["capabilities must be a collection"]
        else:
            capability_errors = [f"unknown capability: {capability}" for capability in capabilities
                                 if capability not in _LEGACY_ALLOWED_CAPABILITIES]
        implementation_errors = [error for error in errors if "implementation entry" in error]
        other_errors = [error for error in errors
                        if not error.startswith("unknown kind:")
                        and not error.startswith("capabilities must be")
                        and not error.startswith("unknown capability:")
                        and "implementation entry" not in error]
        return other_errors + kind_errors + capability_errors + implementation_errors


def register_extension(registry: _ExtensionRegistry, **kwargs: Any) -> ExtensionRecord:
    """Convenience API for explicit test or application registration."""
    return registry.register(ExtensionRecord(**kwargs))


__all__ = ["DEFAULT_REGISTRY", "ExtensionRecord", "ExtensionRegistry", "RegistryError", "register_extension"]
