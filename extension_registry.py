"""Small, explicit Extension Registry used by the read-only discovery layer.

This is deliberately a static registry: entries are registered by code, and
implementations are resolved only from the explicitly supplied callable or
``module:attribute`` import path.  It is not a plugin loader.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Any, Callable

ALLOWED_KINDS = frozenset({"project", "source", "tool", "knowledge"})
ALLOWED_CAPABILITIES = frozenset({"discover", "inspect", "validate", "read_only"})


class RegistryError(ValueError):
    """Invalid registry definition or registration operation."""


@dataclass(frozen=True)
class ExtensionRecord:
    extension_id: str
    kind: str
    capabilities: frozenset[str]
    implementation: Callable[..., Any] | str


class ExtensionRegistry:
    """An ordered, explicitly populated collection of extension records."""

    def __init__(self, records: list[ExtensionRecord] | tuple[ExtensionRecord, ...] = ()):
        self._records: list[ExtensionRecord] = []
        for record in records:
            self.register(record)

    @property
    def records(self) -> tuple[ExtensionRecord, ...]:
        return tuple(self._records)

    def register(self, record: ExtensionRecord) -> ExtensionRecord:
        errors = self._record_errors(record)
        if isinstance(record, ExtensionRecord) and any(r.extension_id == record.extension_id for r in self._records):
            errors.insert(0, f"duplicate extension_id: {record.extension_id}")
        if any(e.startswith("duplicate extension_id") for e in errors):
            raise RegistryError(errors[0])
        if errors:
            raise RegistryError("; ".join(errors))
        self._records.append(record)
        return record

    def validate(self) -> list[str]:
        """Return stable diagnostics without mutating the registry."""
        diagnostics: list[str] = []
        seen: set[str] = set()
        for record in self._records:
            if record.extension_id in seen:
                diagnostics.append(f"duplicate extension_id: {record.extension_id}")
            seen.add(record.extension_id)
            diagnostics.extend(self._record_errors(record, check_duplicate=False))
            if not any("implementation entry" in error for error in self._record_errors(record, check_duplicate=False)):
                try:
                    self.resolve(record)
                except RegistryError as exc:
                    diagnostics.append(str(exc))
        return diagnostics

    def by_kind(self, kind: str) -> tuple[ExtensionRecord, ...]:
        return tuple(record for record in self._records if record.kind == kind)

    @staticmethod
    def _record_errors(record: ExtensionRecord, check_duplicate: bool = True) -> list[str]:
        errors: list[str] = []
        if not isinstance(record, ExtensionRecord):
            return ["record must be an ExtensionRecord"]
        if not isinstance(record.extension_id, str) or not record.extension_id.strip():
            errors.append("invalid extension_id")
        if record.kind not in ALLOWED_KINDS:
            errors.append(f"unknown kind: {record.kind}")
        capabilities = record.capabilities
        if not isinstance(capabilities, (set, frozenset, tuple, list)):
            errors.append("capabilities must be a collection")
        else:
            for capability in capabilities:
                if capability not in ALLOWED_CAPABILITIES:
                    errors.append(f"unknown capability: {capability}")
        implementation = record.implementation
        valid_entry = callable(implementation)
        if isinstance(implementation, str):
            valid_entry = ":" in implementation and all(implementation.split(":", 1))
        if not valid_entry:
            errors.append("missing or invalid implementation entry")
        return errors

    @staticmethod
    def resolve(record: ExtensionRecord) -> Callable[..., Any]:
        implementation = record.implementation
        if callable(implementation):
            return implementation
        if not isinstance(implementation, str) or ":" not in implementation:
            raise RegistryError(f"missing or invalid implementation entry: {record.extension_id}")
        module_name, attribute = implementation.split(":", 1)
        try:
            target: Any = importlib.import_module(module_name)
            for part in attribute.split("."):
                target = getattr(target, part)
        except (ImportError, AttributeError) as exc:
            raise RegistryError(f"invalid implementation entry for {record.extension_id}: {implementation}") from exc
        if not callable(target):
            raise RegistryError(f"invalid implementation entry for {record.extension_id}: {implementation}")
        return target


DEFAULT_REGISTRY = ExtensionRegistry((
    ExtensionRecord("flac3d_coal_roadway", "project", frozenset({"discover", "read_only"}), "adapters.flac3d:discover"),
    ExtensionRecord("ceramsite_research", "project", frozenset({"discover", "read_only"}), "adapters.ceramsite:discover"),
    ExtensionRecord("zotero_mcp_readonly", "source", frozenset({"discover", "inspect", "read_only"}), "adapters.zotero_mcp_readonly:dispatch"),
))


def register_extension(registry: ExtensionRegistry, **kwargs: Any) -> ExtensionRecord:
    """Convenience API for explicit test or application registration."""
    return registry.register(ExtensionRecord(**kwargs))
