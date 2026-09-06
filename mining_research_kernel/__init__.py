"""Public, dependency-free kernel contracts and generic services."""

from .core import asset, discover_all, discover_sources, inspect_source, safe_path, sha256, validate_record
from .interfaces import (
    AgentHostAdapter,
    ArtifactStore,
    CognitionPolicy,
    DocumentationProvider,
    ExecutionProvider,
    KnowledgeProvider,
    ProjectAdapter,
    RegistryView,
    SourceProvider,
    TransformProvider,
    WorkflowPack,
)
from .registry import ExtensionRecord, ExtensionRegistry, RegistryError
from .routes import RouteLifecycle, RouteLifecycleError
from .cognition import CognitionError, CoreCognition

__all__ = [
    "AgentHostAdapter", "ArtifactStore", "CognitionPolicy", "DocumentationProvider",
    "ExecutionProvider", "KnowledgeProvider", "ProjectAdapter", "SourceProvider",
    "TransformProvider", "WorkflowPack", "RegistryView", "ExtensionRecord", "ExtensionRegistry",
    "RegistryError", "asset", "discover_all", "discover_sources",
    "inspect_source", "safe_path", "sha256", "validate_record", "RouteLifecycle",
    "RouteLifecycleError", "CoreCognition", "CognitionError",
]
