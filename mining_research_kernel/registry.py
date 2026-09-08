"""Explicit extension registry with stable, namespaced identifiers."""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import re
from typing import Any, Callable, Iterable


class RegistryError(ValueError):
    """Invalid registry definition or resolution operation."""


NAMESPACED_ID = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
ALLOWED_KINDS = frozenset({
    "workflow", "project", "documentation", "source", "execution", "knowledge",
    "transform", "cognition_policy", "artifact_store", "agent_host",
})


@dataclass(frozen=True, init=False)
class ExtensionRecord:
    extension_id: str
    extension_kind: str
    capabilities: frozenset[str]
    implementation: Callable[..., Any] | str
    contract_version: int = 1

    def __init__(self, extension_id: str, extension_kind: str | None = None,
                 capabilities=frozenset(), implementation=None, contract_version: int = 1,
                 *, kind: str | None = None):
        if extension_kind is None:
            extension_kind = kind
        if isinstance(capabilities, (set, frozenset, tuple, list)):
            capabilities = frozenset(capabilities)
        object.__setattr__(self, "extension_id", extension_id)
        object.__setattr__(self, "extension_kind", extension_kind)
        object.__setattr__(self, "capabilities", capabilities)
        object.__setattr__(self, "implementation", implementation)
        object.__setattr__(self, "contract_version", contract_version)

    @property
    def kind(self) -> str:
        """Compatibility spelling for callers of the pre-package API."""
        return self.extension_kind


class ExtensionRegistry:
    """Ordered, explicitly populated records; never scans or auto-discovers."""

    def __init__(self, records: Iterable[ExtensionRecord] = (), *, aliases: dict[str, str] | None = None,
                 strict_ids: bool = True):
        self._records: list[ExtensionRecord] = []
        self._aliases: dict[str, str] = {}
        self.strict_ids = strict_ids
        for record in records:
            self.register(record)
        for alias, target in (aliases or {}).items():
            self.register_alias(alias, target)

    @property
    def records(self) -> tuple[ExtensionRecord, ...]:
        return tuple(self._records)

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def register_alias(self, alias: str, extension_id: str) -> str:
        if not isinstance(alias, str) or not alias.strip():
            raise RegistryError("invalid extension alias")
        canonical = self.canonical_id(extension_id)
        if canonical not in {record.extension_id for record in self._records}:
            raise RegistryError(f"unknown extension_id: {extension_id}")
        if alias in self._aliases and self._aliases[alias] != canonical:
            raise RegistryError(f"duplicate extension alias: {alias}")
        self._aliases[alias] = canonical
        return alias

    def canonical_id(self, extension_id: str) -> str:
        if not isinstance(extension_id, str) or not extension_id.strip():
            raise RegistryError("invalid extension_id")
        return self._aliases.get(extension_id, extension_id)

    def register(self, record: ExtensionRecord) -> ExtensionRecord:
        errors = self._record_errors(record, strict_ids=self.strict_ids)
        if isinstance(record, ExtensionRecord) and any(r.extension_id == record.extension_id for r in self._records):
            errors.insert(0, f"duplicate extension_id: {record.extension_id}")
        if any(e.startswith("duplicate extension_id") for e in errors):
            raise RegistryError(errors[0])
        if errors:
            raise RegistryError("; ".join(errors))
        self._records.append(record)
        return record

    def validate(self) -> list[str]:
        diagnostics: list[str] = []
        seen: set[str] = set()
        for record in self._records:
            if record.extension_id in seen:
                diagnostics.append(f"duplicate extension_id: {record.extension_id}")
            seen.add(record.extension_id)
            errors = self._record_errors(record, strict_ids=self.strict_ids)
            diagnostics.extend(errors)
            if not any("implementation entry" in error for error in errors):
                try:
                    self.resolve(record)
                except RegistryError as exc:
                    diagnostics.append(str(exc))
        return diagnostics

    def by_kind(self, kind: str) -> tuple[ExtensionRecord, ...]:
        return tuple(record for record in self._records if record.extension_kind == kind)

    def record_for(self, extension_id: str, *, kind: str | None = None) -> ExtensionRecord:
        canonical = self.canonical_id(extension_id)
        for record in self._records:
            if record.extension_id == canonical and (kind is None or record.extension_kind == kind):
                return record
        raise RegistryError(f"unknown extension_id: {extension_id}")

    def resolve(self, record_or_id: ExtensionRecord | str) -> Callable[..., Any]:
        # Resolve membership before touching importlib.  Unknown ids therefore
        # fail closed without importing caller-controlled module names.
        if isinstance(record_or_id, str):
            record = self.record_for(record_or_id)
        else:
            if not any(candidate is record_or_id for candidate in self._records):
                raise RegistryError(f"unknown extension_id: {record_or_id.extension_id}")
            record = record_or_id
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

    @staticmethod
    def _record_errors(record: ExtensionRecord, *, strict_ids: bool = True) -> list[str]:
        errors: list[str] = []
        if not isinstance(record, ExtensionRecord):
            return ["record must be an ExtensionRecord"]
        if not isinstance(record.extension_id, str) or not record.extension_id.strip():
            errors.append("invalid extension_id")
        elif strict_ids and not NAMESPACED_ID.fullmatch(record.extension_id):
            errors.append(f"extension_id must be namespaced: {record.extension_id}")
        if not isinstance(record.extension_kind, str) or record.extension_kind not in ALLOWED_KINDS:
            errors.append(f"unknown kind: {record.extension_kind}")
        if record.contract_version != 1:
            errors.append(f"unsupported contract_version: {record.contract_version!r}")
        capabilities = record.capabilities
        if not isinstance(capabilities, (set, frozenset)):
            errors.append("capabilities must be a collection")
        else:
            for capability in capabilities:
                if not isinstance(capability, str) or not capability.strip():
                    errors.append("capabilities must contain non-empty strings")
        implementation = record.implementation
        valid_entry = callable(implementation)
        if isinstance(implementation, str):
            valid_entry = ":" in implementation and all(implementation.split(":", 1))
        if not valid_entry:
            errors.append("missing or invalid implementation entry")
        return errors
