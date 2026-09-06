# Security

Please do not report suspected secrets or private research material in a
public issue. Contact the repository owner privately with a minimal
reproduction and the affected revision.

This project exposes a bounded local API. Its adapters remain read-only, while
explicit caller requests may initialize a project, commit records and ledger
entries, or write derived artifacts. It does not ship credentials, a Zotero
database, private snapshots, full-text bodies, or a background service. Do not
commit API keys, tokens, cookies, local databases, research PDFs, CAJ files, or
private workspace exports.

Reports are triaged for impact on data exposure, path traversal, unsafe
external access, and integrity of the read-only contracts.
