# Mining Research Kernel

A small, filesystem-native kernel for read-only research discovery, explicit
contracts, source snapshots, deterministic relation mapping, and auditable run
ledgers. It uses only the Python standard library and does not require a
database, network access, Zotero, or commercial research software for its
public examples.

## Why this exists

Research automation needs a boundary between authoritative material, derived
artifacts, and claims about verification. This project makes that boundary
explicit. It discovers compatible workspaces and reports evidence; it does not
silently rewrite research files or turn metadata into experimental conclusions.

## Current capabilities

- Two read-only project adapters for a compatible mining-research workspace.
- A static `kind=source` Zotero adapter with only `discover`, `inspect`, and
  `read_only` capabilities.
- Sanitized Zotero snapshot validation and collection/item/attachment
  relation summaries.
- Optional normalized DOI matching before title/author fallback in
  `relation_map.py`.
- A filesystem-native five-stage Run Ledger with deterministic validation and
  stability diagnostics.
- Standard-library-only tests and a fully synthetic workspace example.

## Quick start

From this repository root:

```powershell
python -m unittest discover -s tests -v
python mining_kernel.py --workspace examples/synthetic_workspace discover
python mining_kernel.py --workspace examples/synthetic_workspace inspect flac3d_coal_roadway
python mining_kernel.py --workspace examples/synthetic_workspace discover-sources
python mining_kernel.py --workspace examples/synthetic_workspace inspect-source zotero_mcp_readonly --operation zotero_get_collections
python mining_kernel.py --workspace examples/synthetic_workspace validate
```

The last source inspection intentionally reports `CANNOT_VERIFY` because no
external Zotero reader is supplied by the example. A compatible application
may inject a reader for one allowed operation.

For snapshot-only workflows:

```powershell
python mining_kernel.py validate-zotero-snapshot path/to/snapshot.json
python mining_kernel.py inspect-zotero-snapshot path/to/snapshot.json
```

## Workspace contract

The `--workspace` argument points to a user-owned compatible workspace. The
current project adapters expect relative paths under that root, including a
small `Workspace_Index/project_index.yaml` navigation file and the project
paths represented by the adapters. The repository ships only a synthetic
version of that layout; it does not ship a private workspace or research
documents.

## Zotero read-only boundary

The Zotero integration is deliberately a source read path, not a write
provider. The direct write tool was not exposed during the upstream approval
test, so the write-approval path remains `CANNOT_VERIFY`; no write capability is
approved in this release. The adapter contains no CREATE, UPDATE, DELETE, or
MERGE operation and holds no MCP credentials. Its transport is injected by the
caller, and missing or failed readers degrade to explicit diagnostics.

The five allowed operations are:

```text
zotero_get_collections
zotero_get_collection_items
zotero_get_item_metadata
zotero_get_item_children
zotero_get_item_fulltext
```

Original PDFs and other primary sources remain authoritative. Zotero metadata,
snapshots, OCR, Markdown, and MCP responses are rebuildable relation or
reading layers and must not be treated as experimental validation by
themselves.

Snapshot `doi` is optional. Exported DOI values are normalized to a lowercase
bare DOI, and relation mapping uses DOI when available before falling back to
title/author matching. DOI is metadata evidence; it does not prove source
identity, page-level support, or scientific validity.

## Safety and limitations

- No Zotero credentials, library database, full-text body, private item keys,
  or absolute attachment paths are included in this repository.
- The public snapshot and workspace are synthetic and are not a full-library
  example.
- The Zotero adapter is not a gateway, background service, downloader, or
  full-text index.
- FLAC3D/Itasca software and other proprietary products are not distributed or
  licensed by this repository.
- Schema and API contracts are version 1 and may change in a future release.

Future work such as a separately authorized Zotero Write Provider, automatic
discovery/download, OpenAlex/OAResolver, Docling, PaperQA2, or serviceization
is outside this release and requires a new scope and acceptance record.

## License

Mining Research Kernel is released under the Apache License 2.0. The license
applies only to code and documentation this repository is authorized to
publish. Zotero, FLAC3D/Itasca, and other third-party products retain their
own licenses; none are bundled here.
