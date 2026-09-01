# v0.1.0 — Read-only research kernel baseline

This release is an experimental, standard-library-only kernel for explicit
read-only research discovery and auditability.

Included:

- Read-only project adapters and a synthetic compatible workspace.
- Static Zotero source registration with five explicit READ operations.
- Sanitized snapshot validation with optional DOI normalization.
- Deterministic relation mapping and filesystem-native Run Ledger utilities.

Not included:

- Zotero CREATE/UPDATE/DELETE/MERGE or any write provider.
- Zotero credentials, private library state, or real research documents.
- FLAC3D/Itasca software or other proprietary assets.
- Automatic paper discovery/download, PaperQA2, LLM Wiki, or a background
  service.

Schema and API contracts may change in future releases.
