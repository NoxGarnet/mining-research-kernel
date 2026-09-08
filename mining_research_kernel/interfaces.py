"""Stable public contracts for extensions.

These contracts describe roles only.  Implementations belong to composition
roots or domain modules and are never imported by this module.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol


class ProjectAdapter(Protocol):
    def discover(self, workspace: Any) -> Mapping[str, Any]: ...


class WorkflowPack(Protocol):
    def build(self, project: Mapping[str, Any] | None = None) -> Mapping[str, Any]: ...


class DocumentationProvider(Protocol):
    def capability(self) -> Mapping[str, Any]: ...

    def verify_syntax(self, topic: str, command: str | None = None, **kwargs: Any) -> Mapping[str, Any]: ...


class SourceProvider(Protocol):
    def dispatch(self, workspace: Any, **kwargs: Any) -> Mapping[str, Any]: ...


class ExecutionProvider(Protocol):
    def execute(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class KnowledgeProvider(Protocol):
    def query(self, request: Mapping[str, Any]) -> Mapping[str, Any]: ...


class TransformProvider(Protocol):
    def transform(self, value: Any, **kwargs: Any) -> Any: ...


class CognitionPolicy(Protocol):
    def evaluate(self, proposal: Mapping[str, Any]) -> Mapping[str, Any]: ...


class ArtifactStore(Protocol):
    def put(self, artifact: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def get(self, artifact_id: str) -> Mapping[str, Any] | None: ...


class AgentHostAdapter(Protocol):
    def submit(self, task: Mapping[str, Any]) -> Mapping[str, Any]: ...


class RegistryView(Protocol):
    def by_kind(self, kind: str) -> tuple[Any, ...]: ...

    def resolve(self, record_or_id: Any) -> Callable[..., Any]: ...

    def record_for(self, extension_id: str, *, kind: str | None = None) -> Any: ...


# Kept as a type-level vocabulary for adapters that accept injected callables.
Reader = Callable[..., Any]
