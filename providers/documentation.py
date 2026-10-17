"""Bounded, read-only local HTML documentation provider.

The registration file is an explicit host-side trust input. A query, an
index, or an injected callback cannot establish document identity. This module
verifies one small unit: the command name in a real Syntax section. It does
not validate FISH grammar, options, combinations, or whole scripts.
The separate passage-reading API uses the same registration to read bounded
explanations without claiming syntax or engineering verification.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Callable, Mapping

VERIFIED = "VERIFIED"
SYNTHETIC_VERIFIED = "SYNTHETIC_VERIFIED"
CANNOT_VERIFY = "CANNOT_VERIFY"

_SUPPORTED_SCHEMA_VERSION = 1
_MODES = {"local", "auto", "installed", "official_web", "unavailable"}
_REGISTRATION_KEYS = {
    "schema_version", "source_id", "root", "product", "document_family",
    "document_build", "trust_class", "product_subdir", "pages",
}
_VERSION = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SOURCE_ID = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9]*)+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _duplicate_key_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate_key:{key}")
        result[key] = value
    return result


def _invalid(detail: str) -> ValueError:
    return ValueError(f"invalid_registration:{detail}")


def _safe_page_path(value: Any, *, field_name: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise _invalid(f"{field_name}_must_be_relative_posix_path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        raise _invalid(f"{field_name}_must_be_relative_posix_path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise _invalid(f"{field_name}_contains_traversal")
    if parts[0] != "flac3d":
        raise _invalid(f"{field_name}_outside_product_subtree")
    return value


@dataclass(frozen=True)
class RegisteredDocumentationSource:
    """Strict host-selected documentation registration metadata."""

    schema_version: int
    source_id: str
    root: str
    product: str
    document_family: str
    document_build: str
    trust_class: str
    product_subdir: str
    pages: Mapping[str, str]
    registration_path: Path = field(default=Path("."), repr=False, compare=False)

    @property
    def root_path(self) -> Path:
        root = Path(self.root)
        if root.is_absolute():
            return root
        return self.registration_path.parent / root


def load_registration(path: str | Path) -> RegisteredDocumentationSource:
    """Load one strict JSON registration selected by the host."""
    registration_path = Path(path).resolve()
    try:
        raw = registration_path.read_text(encoding="utf-8")
        value = json.loads(raw, object_pairs_hook=_duplicate_key_object)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("invalid_registration:"):
            raise
        raise _invalid("json") from exc

    if not isinstance(value, dict):
        raise _invalid("root_must_be_object")
    if set(value) != _REGISTRATION_KEYS:
        unknown = sorted(set(value) - _REGISTRATION_KEYS)
        missing = sorted(_REGISTRATION_KEYS - set(value))
        detail = f"unknown={unknown}" if unknown else f"missing={missing}"
        raise _invalid(f"fields:{detail}")
    if value["schema_version"] != _SUPPORTED_SCHEMA_VERSION or isinstance(value["schema_version"], bool):
        raise _invalid("unsupported_schema_version")
    for key in ("source_id", "root", "product", "document_family", "document_build",
                "trust_class", "product_subdir"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise _invalid(f"{key}_must_be_nonempty_string")
        if any(ord(char) < 32 or ord(char) == 127 for char in value[key]):
            raise _invalid(f"{key}_contains_control_character")
    if not _SOURCE_ID.fullmatch(value["source_id"]):
        raise _invalid("source_id_must_be_dot_namespaced")
    if value["product"] != "flac3d":
        raise _invalid("product_must_be_flac3d")
    if value["product_subdir"] != "flac3d":
        raise _invalid("product_subdir_must_be_flac3d")
    if not re.fullmatch(r"\d+\.\d+", value["document_family"]):
        raise _invalid("document_family_invalid")
    if not _VERSION.fullmatch(value["document_build"]):
        raise _invalid("document_build_invalid")
    if value["document_build"].rsplit(".", 1)[0] != value["document_family"]:
        raise _invalid("document_build_family_mismatch")
    if value["trust_class"] not in {"official_local", "synthetic"}:
        raise _invalid("trust_class_invalid")
    if not isinstance(value["pages"], dict) or not value["pages"]:
        raise _invalid("pages_must_be_nonempty_object")

    pages: dict[str, str] = {}
    for page, digest in value["pages"].items():
        page = _safe_page_path(page, field_name="page")
        if not isinstance(digest, str) or not _SHA256.fullmatch(digest):
            raise _invalid(f"page_digest_invalid:{page}")
        pages[page] = digest

    return RegisteredDocumentationSource(
        schema_version=value["schema_version"],
        source_id=value["source_id"], root=value["root"], product=value["product"],
        document_family=value["document_family"], document_build=value["document_build"],
        trust_class=value["trust_class"], product_subdir=value["product_subdir"],
        pages=MappingProxyType(pages), registration_path=registration_path,
    )


class _Node:
    def __init__(self, tag: str, attrs: Mapping[str, str] | None = None) -> None:
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children: list[_Node | str] = []


class _DocumentParser(HTMLParser):
    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input",
                  "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {k.lower(): (v or "") for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in self._void_tags:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._void_tags and len(self.stack) > 1:
            self.stack.pop()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].children.append(data)


def _walk(node: _Node):
    for child in node.children:
        if isinstance(child, _Node):
            yield child
            yield from _walk(child)


def _text(node: _Node) -> str:
    return "".join(child if isinstance(child, str) else _text(child) for child in node.children)


def _normal_text(value: str) -> str:
    return " ".join(value.split()).strip().casefold()


def _classes(node: _Node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def _descendants(node: _Node, tag: str | None = None) -> list[_Node]:
    return [item for item in _walk(node) if tag is None or item.tag == tag]


def _leaf_cmdname_text(node: _Node) -> list[str]:
    cmd_nodes = [item for item in _descendants(node, "span") if "cmdname" in _classes(item)]
    leaves = [item for item in cmd_nodes
              if not any("cmdname" in _classes(child) for child in _descendants(item, "span"))]
    return [_text(item) for item in (leaves or cmd_nodes)]


def _compact_command(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _extract_metadata(parser: _DocumentParser) -> tuple[str | None, str | None]:
    titles = _descendants(parser.root, "title")
    title_families = []
    for title in titles:
        match = re.search(
            r"Itasca\s+Software\s+(\d+\.\d+)(?:\.\d+)?\s+documentation\b",
            _text(title), flags=re.IGNORECASE,
        )
        if match:
            title_families.append(match.group(1))
    if not title_families or len(set(title_families)) != 1:
        return None, None
    family = title_families[0]

    headers = [item for item in _descendants(parser.root) if item.tag in {"h1", "header"}]
    header_families = []
    for header in headers:
        header_match = re.search(r"(?<!\d)(\d+\.\d+)(?:\.\d+)?(?!\d)", _text(header))
        if header_match:
            header_families.append(header_match.group(1))
    if any(header_family != family for header_family in header_families):
        return None, None

    scripts = [_text(item) for item in _descendants(parser.root, "script")]
    builds = []
    for script in scripts:
        if "DOCUMENTATION_OPTIONS" not in script:
            continue
        builds.extend(re.findall(
            r"\bVERSION\s*:\s*['\"]([^'\"]+)['\"]",
            script, flags=re.IGNORECASE,
        ))
    if not builds or len(set(builds)) != 1:
        return family, None
    return family, builds[0]


class _CapabilityView(dict):
    """Keep the old provider_type lookup compatible with the new schema."""

    def __getitem__(self, key: str):
        if key == "provider_type":
            return super().__getitem__("source_kind")
        return super().__getitem__(key)

    def get(self, key: str, default: Any = None):
        if key == "provider_type":
            return super().get("source_kind", default)
        return super().get(key, default)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _uncovered() -> list[str]:
    return ["parameters", "parameter_combinations", "full_script", "grammar"]


class DocumentationProvider:
    """Read and verify a registered local HTML documentation source."""

    def __init__(self, registration: RegisteredDocumentationSource | None,
                 *, source_kind: str = "local", unavailable_reason: str | None = None) -> None:
        self.registration = registration
        self._source_kind = source_kind
        self._unavailable_reason = unavailable_reason

    def capability(self) -> dict[str, Any]:
        source = self.registration
        available = bool(source and source.root_path.is_dir())
        diagnostics = []
        if self._unavailable_reason:
            diagnostics.append(self._unavailable_reason)
        elif source is None:
            diagnostics.append("registration_required")
        elif not source.root_path.is_dir():
            diagnostics.append("registered_root_missing")
        else:
            diagnostics.append("registered_local_source")
        return _CapabilityView({
            "schema_version": 1, "type": "ProviderCapability",
            "provider_id": "mining_research_kernel.documentation.local",
            "provider_kind": "documentation", "source_kind": self._source_kind,
            "available": available, "host_local": True,
            "capabilities": ["syntax_lookup", "syntax_citation"] if available else [],
            "product_version": source.document_family if source else None,
            "authorization_required": False,
            "last_checked": _now(), "diagnostics": diagnostics,
        })

    def _base_citation(self, topic: Any, anchor: Any, status: str,
                       *, body_hash: str | None = None,
                       query_hash: str | None = None,
                       fetched_at: str | None = None,
                       checked_at: str | None = None) -> dict[str, Any]:
        source = self.registration
        return {
            "source_id": source.source_id if source else None,
            "trust_class": source.trust_class if source else None,
            "product": source.product if source else None,
            "document_family": source.document_family if source else None,
            "document_build": source.document_build if source else None,
            "page": topic if isinstance(topic, str) else None,
            "anchor": anchor if isinstance(anchor, str) else None,
            "sha256": body_hash,
            "sha256_body": body_hash,
            "query_sha256": query_hash,
            "fetched_at": fetched_at,
            "checked_at": checked_at,
            "status": status,
        }

    def _result(self, reason: str, *, topic: Any = None, anchor: Any = None,
                product: Any = None, product_version: Any = None,
                command: Any = None, task_context: str = "production",
                body_hash: str | None = None, fetched_at: str | None = None,
                checked_at: str | None = None, coverage_scope: str = "none",
                uncovered: list[str] | None = None,
                query_hash: str | None = None) -> dict[str, Any]:
        citation = self._base_citation(topic, anchor, CANNOT_VERIFY,
                                       body_hash=body_hash, query_hash=query_hash,
                                       fetched_at=fetched_at, checked_at=checked_at)
        details = [reason]
        if product is not None:
            details.append(f"requested_product={product}")
        if product_version is not None:
            details.append(f"requested_product_version={product_version}")
        if command is not None:
            details.append(f"requested_command={command}")
        if task_context != "production":
            details.append(f"task_context={task_context}")
        return {"status": CANNOT_VERIFY, "stop_reason": reason, "diagnostics": details,
                "citation": citation, "coverage_scope": coverage_scope,
                "uncovered": list(uncovered if uncovered is not None else _uncovered())}

    def verify_syntax(self, topic: str, command: str | None = None, *,
                      product: str | None = None, product_version: str | None = None,
                      source: str | None = None, anchor: str | None = None,
                      task_context: str = "production") -> dict[str, Any]:
        """Verify only an exact command name in the registered page's HTML."""
        if not isinstance(task_context, str) or task_context not in {"production", "synthetic"}:
            return self._result("task_context_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if (not isinstance(product, str) or not product.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in product)):
            return self._result("target_product_required", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if (not isinstance(product_version, str) or not product_version.strip()
                or any(ord(char) < 32 or ord(char) == 127 for char in product_version)):
            return self._result("target_product_version_required", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if not isinstance(topic, str) or not topic.strip():
            return self._result("topic_required", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        try:
            topic = _safe_page_path(topic, field_name="topic")
        except ValueError:
            return self._result("topic_path_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if not isinstance(command, str) or not command.strip():
            return self._result("topic_only", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if any(ord(char) < 32 or ord(char) == 127 for char in command):
            return self._result("command_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if anchor is not None and (not isinstance(anchor, str) or
                                   any(ord(char) < 32 or ord(char) == 127 for char in anchor)):
            return self._result("anchor_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        if source is not None and (not isinstance(source, str) or
                                   any(ord(char) < 32 or ord(char) == 127 for char in source)):
            return self._result("source_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context)
        command = " ".join(command.split())
        query = {"product": product, "product_version": product_version,
                 "topic": topic, "command": command, "source": source,
                 "anchor": anchor, "task_context": task_context}
        query_hash = hashlib.sha256(json.dumps(query, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False).encode("utf-8")).hexdigest()

        registration = self.registration
        if registration is None:
            return self._result("registration_required", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if self._source_kind != "local":
            return self._result("documentation_source_unavailable", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if registration.schema_version != 1 or isinstance(registration.schema_version, bool):
            return self._result("registration_schema_version_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if registration.trust_class not in {"official_local", "synthetic"}:
            return self._result("registration_trust_class_invalid", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if registration.trust_class == "synthetic" and task_context != "synthetic":
            return self._result("synthetic_source_not_for_production", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if registration.trust_class == "official_local" and task_context != "production":
            return self._result("official_source_requires_production_context", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if product != registration.product:
            return self._result("target_product_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if product_version not in {registration.document_family, registration.document_build}:
            return self._result("target_product_version_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        if topic not in registration.pages:
            return self._result("page_not_registered", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)

        root = registration.root_path.resolve()
        product_root = (registration.root_path / registration.product_subdir).resolve()
        page_path = (registration.root_path / Path(*PurePosixPath(topic).parts)).resolve()
        if not _is_relative_to(page_path, root) or not _is_relative_to(page_path, product_root):
            return self._result("page_path_outside_registered_product_root", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                query_hash=query_hash)
        expected_digest = registration.pages[topic]
        fetched_at = _now()
        try:
            body = page_path.read_bytes()
        except (OSError, ValueError):
            return self._result("page_missing_or_unreadable", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                fetched_at=fetched_at, query_hash=query_hash)
        body_hash = hashlib.sha256(body).hexdigest()
        checked_at = _now()
        if body_hash != expected_digest:
            return self._result("page_hash_drift", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        try:
            html = body.decode("utf-8")
            parser = _DocumentParser()
            parser.feed(html)
            parser.close()
        except (UnicodeError, ValueError):
            return self._result("html_unreadable", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)

        actual_family, actual_build = _extract_metadata(parser)
        if actual_family is None:
            return self._result("document_family_unreadable", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        if actual_family != registration.document_family:
            return self._result("document_family_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        if actual_build is None:
            return self._result("document_build_unreadable", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        if actual_build != registration.document_build:
            return self._result("document_build_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)

        expected_anchor = "command:" + ".".join(command.split())
        if anchor is not None and anchor != expected_anchor:
            return self._result("anchor_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        if source is not None and source not in {"local", registration.source_id}:
            return self._result("source_not_applicable", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)

        sections = [section for section in _descendants(parser.root, "section")
                    if any(_normal_text(item_text) == "syntax"
                           for item in _descendants(section)
                           for item_text in [_text(item)]
                           if (item.tag in {"p", "h2", "h3"} or "rubric" in _classes(item)))]
        if not sections:
            return self._result("syntax_section_missing", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        section = next((item for item in sections
                        if _slug(_text(next((h for h in _descendants(item, "h1")), item))) ==
                        _slug(f"{command} command")), None)
        if section is None:
            return self._result("syntax_heading_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        heading = next((h for h in _descendants(section, "h1")), None)
        if heading is None or _normal_text(_text(heading)) != _normal_text(f"{command} command"):
            return self._result("syntax_heading_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        if section.attrs.get("id") != _slug(_text(heading)):
            return self._result("syntax_section_id_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)

        signatures = [item for item in _descendants(section, "dt")
                      if {"sig", "sig-object"}.issubset(_classes(item))]
        expected_compact = _compact_command(command)
        signature = next((item for item in signatures
                          if _compact_command(" ".join(_leaf_cmdname_text(item))) == expected_compact), None)
        if signature is None:
            return self._result("command_signature_missing", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)
        if signature.attrs.get("id") != expected_anchor:
            return self._result("command_anchor_mismatch", topic=topic, anchor=anchor,
                                product=product, product_version=product_version,
                                command=command, task_context=task_context,
                                body_hash=body_hash, fetched_at=fetched_at,
                                checked_at=checked_at, query_hash=query_hash)

        status = SYNTHETIC_VERIFIED if registration.trust_class == "synthetic" else VERIFIED
        citation = self._base_citation(topic, anchor or expected_anchor, status,
                                       body_hash=body_hash, query_hash=query_hash,
                                       fetched_at=fetched_at, checked_at=checked_at)
        return {"status": status, "stop_reason": "exact_command_name_match",
                "diagnostics": ["html_read", "metadata_matched", "syntax_section_matched",
                                "command_signature_matched"],
                "citation": citation, "coverage_scope": "command_name_only",
                "uncovered": _uncovered()}


def _unavailable(kind: str, reason: str) -> DocumentationProvider:
    return DocumentationProvider(None, source_kind=kind, unavailable_reason=reason)


def resolve_documentation(config: Mapping[str, Any], *, project_root: Path | None = None,
                          registration: RegisteredDocumentationSource | None = None,
                          official_lookup: Callable[..., Any] | None = None,
                          installed_lookup: Callable[..., Any] | None = None) -> DocumentationProvider:
    """Resolve only an explicitly registered local source.

    ``project_root``, lookup callbacks, and legacy config indexes are retained
    in the signature for composition compatibility, but cannot create a trust
    registration or establish VERIFIED evidence.
    """
    del project_root, official_lookup, installed_lookup
    if not isinstance(config, Mapping):
        return _unavailable("unavailable", "invalid_documentation_config")
    mode = config.get("provider", "auto")
    if not isinstance(mode, str) or mode not in _MODES:
        return _unavailable("unavailable", "unsupported_provider_mode")
    if mode in {"installed", "official_web", "unavailable"}:
        return _unavailable(mode, f"{mode}_provider_unavailable")
    if not isinstance(registration, RegisteredDocumentationSource):
        return _unavailable("local", "registration_required")
    return DocumentationProvider(registration)


def verify_syntax(config: Mapping[str, Any], topic: str, command: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Compatibility wrapper; it does not restore legacy callback/index trust."""
    return resolve_documentation(
        config,
        project_root=kwargs.pop("project_root", None),
        registration=kwargs.pop("registration", None),
        official_lookup=kwargs.pop("official_lookup", None),
        installed_lookup=kwargs.pop("installed_lookup", None),
    ).verify_syntax(topic, command, **kwargs)


# Bounded passage reading shares this provider's registered HTML boundary.
MAX_TRANSIENT_CHARS = 12_000
MAX_SAVED_CHARS = 2_000
_HIDDEN_TAGS = {"aside", "footer", "nav", "noscript", "script", "style"}


def _visible_text(node: Any) -> str:
    if node is None:
        return ""
    if node.tag in _HIDDEN_TAGS:
        return ""
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child.tag not in _HIDDEN_TAGS:
            parts.append(_visible_text(child))
    return " ".join(" ".join(parts).split())


def _section_heading(section: Any) -> str | None:
    if section is None:
        return None
    heading = next((node for node in _descendants(section)
                    if node.tag in {"h1", "h2", "h3", "h4"}), None)
    return _visible_text(heading) or None


def _paragraph_passages(body: Any) -> list[tuple[str, str | None, str | None]]:
    """Collect main-body paragraphs once, carrying their current section heading."""
    found: list[tuple[str, str | None, str | None]] = []

    def visit(node: Any, section_id: str | None = None,
              heading: str | None = None) -> tuple[str | None, str | None]:
        if node.tag in _HIDDEN_TAGS:
            return section_id, heading
        for child in node.children:
            if isinstance(child, str) or child.tag in _HIDDEN_TAGS:
                continue
            if child.tag == "section":
                visit(child, child.attrs.get("id") or section_id, None)
            elif child.tag in {"h1", "h2", "h3", "h4"}:
                heading = _visible_text(child) or heading
            elif child.tag == "p":
                text = _visible_text(child)
                if text:
                    found.append((text, section_id, heading))
            else:
                section_id, heading = visit(child, section_id, heading)
        return section_id, heading

    main = next((node for node in _descendants(body)
                 if node.tag == "main" or node.attrs.get("role", "").casefold() == "main"
                 or node.attrs.get("id", "").casefold() == "main"), None)
    visit(main or body)
    return found


def _bounded_result(source: Any, page: Any, product: Any, anchor: Any) -> dict[str, Any]:
    return {
        "status": "CANNOT_READ",
        "stop_reason": "invalid_request",
        "diagnostics": [],
        "coverage_scope": "documentation_passage_reading_only",
        "citation": {
            "source_id": getattr(source, "source_id", None),
            "product": product,
            "document_family": getattr(source, "document_family", None),
            "document_build": getattr(source, "document_build", None),
            "page": page,
            "anchor": anchor,
            "trust_class": getattr(source, "trust_class", None),
            "sha256_body": None,
        },
        "passages": [],
        "reading_texts": [],
        "uncovered": ["parameter_combinations", "full_script", "numerical_validity",
                      "engineering_suitability"],
        "applicability_status": "INSUFFICIENT",
        "_query_performed": False,
    }


def read_local_documentation(
    registration: Any,
    *,
    page: str,
    product: str,
    product_version: str,
    anchor: str | None = None,
    max_reading_chars: int = MAX_TRANSIENT_CHARS,
    task_context: str = "production",
) -> dict[str, Any]:
    """Read only bounded visible passages from a pinned, version-matched page."""
    source = registration
    if isinstance(source, (str, Path)):
        try:
            source = load_registration(source)
        except ValueError:
            source = None
    result = _bounded_result(source, page, product, anchor)

    def fail(reason: str, *, attempted: bool = False) -> dict[str, Any]:
        result["stop_reason"] = reason
        result["diagnostics"] = [reason]
        result["_query_performed"] = attempted
        return result

    if task_context not in {"production", "synthetic"}:
        return fail("task_context_invalid")
    if type(max_reading_chars) is not int or max_reading_chars < 1:
        return fail("max_reading_chars_invalid")
    max_reading_chars = min(max_reading_chars, MAX_TRANSIENT_CHARS)
    if source is None:
        return fail("registration_required")
    if source.trust_class == "synthetic" and task_context != "synthetic":
        return fail("synthetic_source_not_for_production")
    if source.trust_class == "official_local" and task_context != "production":
        return fail("official_source_requires_production_context")
    try:
        page = _safe_page_path(page, field_name="page")
    except (ValueError, TypeError):
        return fail("page_path_invalid")
    if product != source.product:
        return fail("target_product_mismatch")
    if product_version not in {source.document_family, source.document_build}:
        return fail("target_product_version_mismatch")
    if anchor is not None and (not isinstance(anchor, str) or not anchor.strip()):
        return fail("anchor_invalid")
    if page not in source.pages:
        return fail("page_not_registered")

    root = source.root_path.resolve()
    product_root = (source.root_path / source.product_subdir).resolve()
    path = (source.root_path / Path(*PurePosixPath(page).parts)).resolve()
    if not _is_relative_to(path, root) or not _is_relative_to(path, product_root):
        return fail("page_path_outside_registered_product_root")
    result["_query_performed"] = True
    try:
        body = path.read_bytes()
    except OSError:
        return fail("page_missing_or_unreadable", attempted=True)
    body_hash = hashlib.sha256(body).hexdigest()
    result["citation"].update(sha256_body=body_hash, checked_at=_now())
    if body_hash != source.pages[page]:
        return fail("page_hash_drift", attempted=True)
    try:
        parser = _DocumentParser()
        parser.feed(body.decode("utf-8"))
        parser.close()
    except (UnicodeError, ValueError):
        return fail("html_unreadable", attempted=True)
    family, build = _extract_metadata(parser)
    if family != source.document_family:
        return fail("document_family_mismatch" if family else "document_family_unreadable", attempted=True)
    if build != source.document_build:
        return fail("document_build_mismatch" if build else "document_build_unreadable", attempted=True)

    sections = _descendants(parser.root, "section")
    candidates: list[tuple[str, str | None, str | None]] = []
    if anchor is not None:
        anchor_id = anchor.lstrip("#")
        target = next((node for node in _descendants(parser.root)
                       if node.attrs.get("id") == anchor_id), None)
        if target is None:
            return fail("anchor_not_found", attempted=True)
        locator = target.attrs.get("id")
        section = next((node for node in sections
                        if node is target or target in _descendants(node)), None)
        heading = _section_heading(section)
        if target.tag == "dt":
            parent = next((node for node in _descendants(parser.root)
                           if target in node.children), None)
            if parent is not None:
                index = parent.children.index(target)
                definition = next((node for node in parent.children[index + 1:]
                                   if getattr(node, "tag", None) == "dd"), None)
                text = _visible_text(definition)
            else:
                text = ""
        elif target.tag == "section":
            text = _visible_text(target)
        elif target.tag in {"h1", "h2", "h3", "h4"}:
            text = _visible_text(target)
            parent = next((node for node in _descendants(parser.root)
                           if target in node.children), None)
            if parent is not None:
                index = parent.children.index(target)
                following = []
                for node in parent.children[index + 1:]:
                    if getattr(node, "tag", None) in {"h1", "h2", "h3", "h4"}:
                        break
                    if not isinstance(node, str):
                        value = _visible_text(node)
                        if value:
                            following.append(value)
                text = " ".join([text, *following]).strip()
        else:
            text = _visible_text(target)
        if text:
            candidates.append((text, locator or page, heading))
    else:
        body_node = next((node for node in _descendants(parser.root) if node.tag == "body"), parser.root)
        candidates = _paragraph_passages(body_node)
        if not candidates:
            candidates = [(_visible_text(section), section.attrs.get("id"), _section_heading(section))
                          for section in sections if _visible_text(section)]

    if not candidates:
        return fail("passage_not_found", attempted=True)

    passages: list[dict[str, Any]] = []
    reading_texts: list[dict[str, Any]] = []
    transient_total = 0
    saved_total = 0
    for text, locator, heading in candidates:
        transient_room = max_reading_chars - transient_total
        if transient_room <= 0:
            break
        transient_excerpt = text[:transient_room]
        transient_truncated = len(transient_excerpt) < len(text)
        transient = {
            "text": transient_excerpt,
            "truncated": transient_truncated,
            "original_char_count": len(text),
            "locator": locator or page,
        }
        reading_texts.append(transient)
        transient_total += len(transient_excerpt)

        saved_room = MAX_SAVED_CHARS - saved_total
        if saved_room <= 0:
            continue
        saved_excerpt = transient_excerpt[:saved_room]
        saved_total += len(saved_excerpt)
        passages.append({
            **transient,
            "text": saved_excerpt,
            "truncated": transient_truncated or len(saved_excerpt) < len(transient_excerpt),
            "sha256": hashlib.sha256(saved_excerpt.encode("utf-8")).hexdigest(),
            "heading": heading,
        })

    total_candidate_chars = sum(len(text) for text, _, _ in candidates)
    reading_truncated = total_candidate_chars > transient_total
    saved_text_truncated = saved_total < transient_total

    result.update({
        "status": "READ_WITH_LIMITS",
        "stop_reason": "bounded_passages_read",
        "diagnostics": ["registered_page_hash_matched", "document_version_matched"],
        "passages": passages,
        "reading_texts": reading_texts,
        "reading_truncated": reading_truncated,
        "saved_text_truncated": saved_text_truncated,
        "applicability_status": "LIMITED",
        "_query_performed": True,
    })
    if source.trust_class == "synthetic":
        result["diagnostics"].append("synthetic_source")
    if reading_truncated:
        result["diagnostics"].append("reading_text_budget_truncated_remaining_passages")
    return result
