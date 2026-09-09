# Mining Research Kernel v0.1.0

Repository-local copy of the v0.1.0 release notes, published 2026-09-09.
The canonical public copy is the
[v0.1.0 GitHub Release](https://github.com/NoxGarnet/mining-research-kernel/releases/tag/v0.1.0);
keep this file in sync when a new version is released.

Mining Research Kernel v0.1.0 is a small, filesystem-native kernel for
Agent-assisted mining research: research questions, routes, evidence,
records, recovery, audit trails and rebuildable derived views, with explicit
boundaries between authoritative material, derived artifacts and claims about
verification. It runs on the Python standard library; the test suite
additionally needs `jsonschema`.

This release fixes the two release-boundary security findings found before
publication:

- Production documentation evidence is accepted only from the trusted Host
  `documentation_result` argument. Ordinary request/CLI JSON can no longer
  fabricate production `VERIFIED` or override a Host result; synthetic
  contexts remain supported.
- Fixed project records and run paths reject junctions and other reparse
  points before reading, locking or writing, preventing accidental writes
  outside the project. Task execution checks the linked runs path before
  reserving budget or dispatching a provider. Explicit ordinary external
  output directories remain valid.

The 2026-09-09 clean local clone of the tested code baseline
`35c1412` ran 209 tests: 208 passed, one file-symlink test skipped
(Windows error 1314, platform coverage only), zero failures. All 18 offline
CLI acceptance commands succeeded; 19 schema documents passed schema
checks; six TaskPacket outputs passed their runtime schema. Both synthetic
project workflows recovered their completed state from a separate process.
The tagged revision `c87960d` adds only acceptance and release
documentation on top of the tested code baseline.

The FLAC3D documentation path is real and version-bound at its stated
`command_name_only` scope; it does not verify full command grammar, scripts,
numerical behavior, physical behavior or engineering suitability. The
production FLAC3D `static_check` gate remains applicable but unimplemented;
production requests return `blocked` with `static_check_unimplemented`.
Synthetic static checking and fake execution are fixture implementations and
remain clearly marked synthetic.

ResearchStore, TaskState, routes, Run Ledger, Evidence/Verification,
Research Map, Cognition views and completion checks are real local kernel
mechanisms. Itasca documentation, Zotero snapshots and any live read-only
reader are user-provided resources; this repository does not bundle a
complete `itasca-mcp` integration, credentials, Zotero databases, private
research material or proprietary vendor documentation.

Trusted Host source registration remains a caller integration boundary. This
release adds no authentication, signature system or sandbox. Historical
VERIFIED TaskStates are not revalidated, and the same-user
concurrent-directory-swap exclusion remains outside the v0.1.0 boundary.
These two reported paths passed bounded remediation acceptance; that is not
a full security audit or an engineering validity claim.

See [docs/ACCEPTANCE_SUMMARY.md](docs/ACCEPTANCE_SUMMARY.md) for the
sanitized baseline results and [docs/PUBLIC_DISTRIBUTION_SCOPE.md](docs/PUBLIC_DISTRIBUTION_SCOPE.md)
for included and excluded materials. The pre-publication candidate draft is
archived in [docs/archive/v0.1.0-release-candidate.md](docs/archive/v0.1.0-release-candidate.md).
