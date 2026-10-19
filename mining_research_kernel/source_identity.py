"""Bounded, record-local identity matching for selected paper observations."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _doi(value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "http://dx.doi.org/"):
        if value.lower().startswith(prefix):
            value = value[len(prefix):]
            break
    return value.lower()


def paper_identity(asset: Mapping[str, Any], asset_ref: str | None = None) -> dict[str, Any] | None:
    """Return primary identity and match aliases for a saved paper Asset."""
    kind = asset.get("asset_kind")
    payload = asset.get("payload", {})
    if not isinstance(payload, Mapping):
        return None
    request = payload.get("request", {})
    if not isinstance(request, Mapping):
        return None

    if kind == "reading_observation":
        observation = request.get("observation", {})
        source = observation.get("source", {}) if isinstance(observation, Mapping) else {}
        if not isinstance(source, Mapping):
            return None
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            return None
        doi = _doi(source.get("doi"))
        keys = {("source_id", source_id)}
        if doi:
            keys.add(("doi", doi))
        # Preserve DOI-first labels for existing reports; source_id remains an
        # alias so a later DOI enrichment can match the preceding record.
        primary = ("doi", doi) if doi else ("source_id", source_id)
        return {"primary": primary, "keys": keys,
                "source_id": source_id, "doi": doi}

    if kind == "zotero_reading_capture":
        capture = request.get("capture", {})
        item = capture.get("item", {}) if isinstance(capture, Mapping) else {}
        if not isinstance(item, Mapping) or not isinstance(capture, Mapping):
            return None
        doi = _doi(item.get("doi"))
        instance = capture.get("instance_id")
        library = capture.get("library_id")
        item_key = item.get("key")
        zotero_key = ("zotero", instance, library, item_key)
        keys = {zotero_key}
        if doi:
            keys.add(("doi", doi))
            primary = ("doi", doi)
        else:
            primary = zotero_key
        return {"primary": primary, "keys": keys, "source_id": None, "doi": doi}

    return None


def primary_identity_label(asset: Mapping[str, Any], asset_ref: str | None = None) -> str:
    identity = paper_identity(asset, asset_ref)
    if identity:
        kind, *parts = identity["primary"]
        if kind == "source_id":
            return "paper:source:" + str(parts[0])
        if kind == "doi":
            return "paper:doi:" + str(parts[0])
        if kind == "zotero":
            return "paper:" + ":".join(str(value or "") for value in parts)
    return "asset:" + str(asset_ref)


def identities_match(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    """Match adjacent saved records by their current stable-ID/DOI aliases."""
    if (left.get("source_id") and left.get("source_id") == right.get("source_id")
            and left.get("doi") and right.get("doi") and left["doi"] != right["doi"]):
        raise ValueError("conflicting paper identity: stable source_id is associated with different DOIs: "
                         + str(left["source_id"]))
    return bool(set(left.get("keys", ())) & set(right.get("keys", ())))


def validate_distinct_papers(assets: Sequence[Mapping[str, Any]]) -> None:
    """Reject duplicate paper aliases and conflicting DOI claims for one stable ID."""
    identities = [identity for asset in assets if (identity := paper_identity(asset)) is not None]
    stable_dois: dict[str, set[str]] = {}
    for identity in identities:
        if identity["source_id"] and identity["doi"]:
            stable_dois.setdefault(identity["source_id"], set()).add(identity["doi"])
    conflicts = sorted(source_id for source_id, dois in stable_dois.items() if len(dois) > 1)
    if conflicts:
        raise ValueError("conflicting paper identity: stable source_id is associated with different DOIs: "
                         + ", ".join(conflicts))

    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for identity in identities:
        for key in identity["keys"]:
            if key in seen:
                raise ValueError("literature comparison requires at least two distinct paper identities")
        for key in identity["keys"]:
            seen[key] = identity
