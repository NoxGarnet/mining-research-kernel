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

Current working-tree results: targeted capability, documentation-gate,
completion and material/map tests: 28 passed. The final clean-checkout result,
full test run/skip counts, schema parse count and representative runtime schema
count are recorded after the candidate commit in the acceptance handoff. Any
platform skip is reported separately from tests that ran and passed.

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

The current uncommitted material/example work also makes the first-use path
task-oriented, explains the Agent/Kernel boundary, shows the post-run final
`task-inspect` result, and keeps Cognition observations tied to actual input
files. It has been checked in an isolated synthetic project with separate
process recovery; the baseline test counts above are not being reused as a new
full regression result.
