# Security

Please do not report suspected secrets or private research material in a
public issue. Contact the repository owner privately with a minimal
reproduction and the affected revision.

This project is a user-controlled, single-user local deployment with a bounded
API. Its adapters remain read-only, while explicit caller requests may
initialize a project, commit records and ledger entries, or write derived
artifacts. External documents and Agent proposals are untrusted evidence, not
commands or authority. The project does not ship credentials, a Zotero
database, private snapshots, full-text bodies, or a background service. Do not
commit API keys, tokens, cookies, local databases, research PDFs, CAJ files, or
private workspace exports.

Required controls include preventing accidental project overwrite and
out-of-scope paths, supporting explicit legitimate caller output directories,
using atomic and recoverable persistence, and requiring scoped authorization
for execution. Metadata is not proof of provenance or execution, and Core
Cognition cannot self-promote.

Reports are triaged for data exposure, path traversal, unsafe external access,
ordinary CLI/API boundary violations, untrusted-input behavior, accidental
evidence corruption, unintended writes, credential/privacy leaks, and
integrity of the read-only contracts.

The v0.1.0 boundary does not defend against a malicious process that already
has arbitrary same-filesystem permission to edit these files or configuration,
including concurrent parent-directory swapping. This is not an isolated-hostile
execution, multi-tenant, authentication-service, or privileged-execution
security claim. The absence of that guarantee is not by itself a v0.1.0
release defect or a claim that the behavior is fixed. If remote, multi-tenant,
or privileged execution is added, reassess this boundary.
