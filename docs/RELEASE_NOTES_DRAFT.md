# v0.1.0 candidate release notes

Status: local candidate draft. Public visibility, tag and Release creation
remain separate decisions.

This candidate provides a filesystem-native research kernel with portable
project initialization, explicit task packets, bounded routes, append-only
research records, Run Ledger evidence, rebuildable Research Map/Core Cognition
views, read-only Zotero snapshot integration, and a second-domain synthetic
workflow using the shared TaskEngine.

The FLAC3D documentation path is real and version-bound at its stated
`command_name_only` scope. It does not verify full command grammar, scripts,
numerical behavior, physical behavior or engineering suitability. The
production FLAC3D `static_check` gate is applicable but unimplemented;
production requests return `blocked` with `static_check_unimplemented` and
`next_action.executable=false`. Synthetic static checking and fake execution
are fixture implementations and remain clearly marked synthetic.

ResearchStore, TaskState, routes, Run Ledger, Evidence/Verification,
Research Map, Cognition views and completion checks are real local kernel
mechanisms. Itasca documentation, Zotero snapshots and any live read-only
reader are user-provided resources. The repository does not bundle a complete
`itasca-mcp` integration.

Acceptance commands used for this candidate are relative to the repository
root:

```powershell
python -B -m unittest discover -s tests -v
python -B mining_kernel.py --workspace examples/synthetic_workspace validate
```

The 2026-09-09 clean local clone of code baseline
`35c141243e60f3386da1255530b17492f8e754e7` ran 209 tests: 208 passed,
one file-symlink test skipped because of Windows error 1314, and no failures.
All 18 offline CLI acceptance commands succeeded; 19 schema documents passed
schema checks, and six TaskPacket outputs passed their runtime schema.
Both synthetic project workflows recovered their completed state from a
separate process. The checkout remained clean.

This baseline fixes the two release-boundary findings: production
documentation results come from the trusted Host argument rather than
ordinary request/CLI JSON, and fixed records/runs paths reject junctions and
other reparse points. Task execution rejects a linked runs path before
reserving budget or dispatching the provider. Explicit ordinary external
output directories remain valid. Independent Astra acceptance of the final
preflight change passed 39 related tests and direct rejection/retry checks.

Host source registration remains trusted; this change adds no authentication,
signature system or sandbox, and does not revalidate historical TaskStates.
The file-symlink platform skip and the existing same-user concurrent-directory
swap exclusion remain explicit limits. These two reported paths have passed
bounded remediation acceptance; that does not establish a full security audit
or replace the separate publication decision.

The distribution scope includes source code, schemas, tests, synthetic
fixtures and public documentation. It excludes credentials, Zotero databases
and private snapshots, private research material, original research files,
local Host configuration, proprietary FLAC3D/Itasca software or local vendor
documentation, and temporary trial outputs. No dependency on bundled local
Itasca documentation is claimed.

Public visibility, a version tag and a GitHub Release require separate
decisions after this local candidate review.

See the [public acceptance summary](ACCEPTANCE_SUMMARY.md) for the sanitized
baseline results and [distribution scope](PUBLIC_DISTRIBUTION_SCOPE.md) for
included and excluded materials.

The included material/example work also makes the first-use path
task-oriented, explains the Agent/Kernel boundary, shows the post-run final
`task-inspect` result, and keeps Cognition observations tied to actual input
files. The current clean-clone acceptance includes isolated synthetic projects
and separate-process recovery; historical baseline test counts are kept
separate in the acceptance summary.
