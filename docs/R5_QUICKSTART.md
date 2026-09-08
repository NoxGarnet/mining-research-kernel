# R5 fresh-user and extension acceptance

R5 verifies that a new user can complete a bounded synthetic research loop
from separate CLI processes, and that a second domain uses the same kernel
services. The examples use no network, Zotero library, FLAC3D installation or
private workspace data. They exercise synthetic fixture implementations only.
The kernel records, persistence, Run Ledger and recovery are real local
operations; only the domain execution result is synthetic.

From the repository root:

```powershell
$project = Join-Path $PWD "r5-demo-project"
python mining_kernel.py init-flac3d-project $project --project-id r5_demo --template synthetic
$request = '{"task_id":"demo-task","question_statement":"Does the fixture produce a stable observation?","claim_statement":"The fixture produces a stable observation.","task_type":"mining_research_kernel.task.fake_execution","task_context":"synthetic","maturity":"exploratory","max_runs":1,"input":{"sample":"r5"}}'
python mining_kernel.py task-start --project-root $project --request-json $request
python mining_kernel.py task-inspect --project-root $project demo-task
python mining_kernel.py task-run-fake --project-root $project demo-task --operation-id demo-run --fixture-id fixture-r5
python mining_kernel.py task-inspect --project-root $project demo-task
python mining_kernel.py research-map-rebuild --project-root $project
```

The first `task-start` output is the initial packet. The second
`task-inspect`, run after the fixture action, is the recoverable final state;
expect `state=completed` and a non-executable `next_action`. The Map contains
the question, Claim, Route, RunReference, Evidence and Verification records;
TaskState remains persisted but is intentionally outside the Map view.

If an actual observation was produced during the run, record that observation
with `cognition-observe` and use its returned Evidence ID in a proposal. Do not
copy a hand-written `passed=true` value as research evidence. A located,
structured low-impact fact may become `provisional`. The two derived views
have separate recovery commands:

```powershell
python mining_kernel.py research-map-rebuild --project-root $project
python mining_kernel.py cognition-rebuild --project-root $project
```

`research-map-rebuild` restores `research/map.json` and `cognition-rebuild`
restores `research/core_cognition.json`; both rebuild from the preserved
`research/records/*.json` and neither requires deleting the source records.
`cognition-failure-gate` returns `blocked` for a related unresolved failure and
`clear` for an unrelated scope.

`research-map-rebuild` persists the returned `nodes`/`edges` view to the
project's configured `research/map.json` by default. The lower-level store
method remains pure when called without an output path. A selected local file
can be registered with `register-local-material`; a derived reading note stays
derived and is not an automatic Cognition authority.

This quick start deliberately stops after the completed fixture workflow. Do
not attach `task-complete` to it by inventing Route, RunReference, Verification
or Evidence IDs. Use the independent completion contract only when those
records already exist and satisfy its documented association checks.

The independent second-domain path is:

```powershell
$synthetic = Join-Path $PWD "r5-synthetic-project"
python mining_kernel.py init-synthetic-project $synthetic --project-id r5_synthetic
$syntheticRequest = '{"task_id":"synthetic-task","workflow_id":"synthetic","question_statement":"Does the synthetic workflow produce a stable observation?","claim_statement":"The synthetic workflow produces a stable observation.","task_type":"mining_research_kernel.task.fake_execution","task_context":"synthetic","maturity":"exploratory","max_runs":1,"input":{"sample":"synthetic"}}'
python mining_kernel.py task-start --project-root $synthetic --request-json $syntheticRequest
python mining_kernel.py task-inspect --project-root $synthetic synthetic-task
python mining_kernel.py task-run-fake --project-root $synthetic synthetic-task --operation-id synthetic-run --fixture-id synthetic-fixture
python mining_kernel.py research-map-rebuild --project-root $synthetic
```

`workflow_id: synthetic` selects `workflows/synthetic.py`; it does not select a
second TaskEngine. The shared path still writes TaskState, RunReference,
Evidence and Verification records, while TaskState remains intentionally
excluded from ResearchMap. The synthetic provider is a deterministic fixture
and does not establish FLAC3D, numerical, physical or engineering validity.
The production FLAC3D `static_check` capability is separately declared
unimplemented and remains blocked; it is not silently satisfied by this
synthetic path. The optional external `itasca-mcp` integration is not bundled
or made complete by this example and remains caller/provider territory.

R5 does not replace the R1 official-document check. Production syntax work
still needs a matching, version-bound Itasca source registration; missing or
inapplicable documentation remains `CANNOT_VERIFY`. The user-provided
documentation path is limited to `command_name_only` coverage and does not
verify full parameters, scripts or engineering behavior. A sanitized Zotero
snapshot is also a user-provided input; it is separate from a caller-injected
live read-only Zotero reader. The external `itasca-mcp` provider is not bundled
or made complete by this quick start.
