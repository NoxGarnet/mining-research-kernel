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
- bounded Zotero reading capture validation, caller-injected read collection,
  and explicit capture writeback, with authored synthetic examples only;
- an explicit Host-selected read-only Zotero stdio client and a cited Markdown
  review that combines saved literature and documentation observations;
- bounded official HTML passage reading, a Host-selected documentation-only
  Itasca MCP client, and question-oriented literature comparison with page
  citations; all test sources remain authored synthetic material;
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
  version-bound command-name checking, bounded documentation reading and
  cited literature comparison (interpretations remain provisional);
- `synthetic`: deterministic fixture workflow and fake execution paths;
- `user-provided`: applicable Itasca local documentation registration,
  sanitized Zotero snapshots, read-only Zotero readers and an existing
  documentation-only Itasca MCP runtime selected by the Host;
- `unimplemented`: production FLAC3D `static_check`, real FLAC3D execution and
  Itasca execution integration. The documentation-only connection is optional;
  the external runtime is not bundled.

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
