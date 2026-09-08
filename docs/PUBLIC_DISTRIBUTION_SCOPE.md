# Public distribution scope

This file defines the review boundary for a possible public v0.1.0
distribution. It is a scope statement, not a visibility, tag or Release
operation.

Included:

- the kernel source, public Python/CLI contracts, JSON schemas and tests;
- synthetic projects, fixture results and examples that contain no private
  workspace data;
- public documentation of implemented behavior, synthetic behavior and
  explicitly unimplemented capabilities;
- the read-only Zotero snapshot adapter and its sanitized fixture contract.
- the sanitized acceptance summary for the explicitly identified code
  baseline.

Excluded:

- credentials, tokens, cookies, databases, private snapshots, full-text
  libraries, original PDFs and private research conclusions;
- original project inputs and outputs, temporary trials, private test
  derivatives and local acceptance evidence;
- Host configuration, machine-specific paths, local registrations and local
  vendor documentation;
- FLAC3D/Itasca software, licenses and any claim that this repository bundles
  or installs them.

Capability labels used by the candidate:

- `real implemented`: ResearchStore, TaskState, routes, Run Ledger,
  Evidence/Verification, Research Map, Cognition views, completion checks and
  the version-bound documentation reader at its command-name-only boundary;
- `synthetic`: deterministic fixture workflow and fake execution paths;
- `user-provided`: applicable Itasca local documentation registration,
  sanitized Zotero snapshots and caller-injected read-only Zotero readers;
- `unimplemented`: production FLAC3D `static_check`, real FLAC3D execution and
  a complete `itasca-mcp` integration. The external provider is not bundled.

The local acceptance commands are relative to the repository root:

```powershell
python -B -m unittest discover -s tests -v
python -B mining_kernel.py --workspace examples/synthetic_workspace validate
```

The local candidate baseline and clean-checkout results are supplied by the
[public acceptance summary](ACCEPTANCE_SUMMARY.md). Public visibility, tag
creation and Release creation each remain independent decisions. No network,
installation, real FLAC3D run, real Zotero access or Host mutation is required
for this candidate scope.
