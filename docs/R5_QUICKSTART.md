# R5 fresh-user and extension acceptance

R5 verifies that a new user can complete a bounded synthetic research loop
from separate CLI processes, and that a second domain uses the same kernel
services. The examples use no network, Zotero library, FLAC3D installation or
private workspace data.

From the repository root:

```powershell
$project = Join-Path $PWD "r5-demo-project"
python mining_kernel.py init-flac3d-project $project --project-id r5_demo --template synthetic
$request = '{"task_id":"demo-task","question_statement":"Does the fixture produce a stable observation?","claim_statement":"The fixture produces a stable observation.","task_type":"mining_research_kernel.task.fake_execution","task_context":"synthetic","maturity":"exploratory","max_runs":1,"input":{"sample":"r5"}}'
python mining_kernel.py task-start --project-root $project --request-json $request
python mining_kernel.py task-inspect --project-root $project demo-task
python mining_kernel.py task-run-fake --project-root $project demo-task --operation-id demo-run --fixture-id fixture-r5
python mining_kernel.py research-map-rebuild --project-root $project
python mining_kernel.py cognition-observe --project-root $project --operation-id observe-r5 --observation-kind structured_test --observation-json '{"passed":true}' --locator-json '{"test":"r5"}' --scope-json '{"study":"r5"}' --task-id demo-task
```

The observation command returns an `Evidence` ID. Put that ID in a small
proposal JSON object and submit it with `cognition-propose`; a located,
structured low-impact fact may become `provisional`. Re-run
`cognition-rebuild` after deleting either `research/map.json` or
`research/core_cognition.json`; both are disposable views rebuilt from
`research/records/*.json`. `cognition-failure-gate` returns `blocked` for a
related unresolved failure and `clear` for an unrelated scope.

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

R5 does not replace the R1 official-document check. Production syntax work
still needs a matching, version-bound Itasca source registration; missing or
inapplicable documentation remains `CANNOT_VERIFY`. The optional
`itasca-mcp` provider remains disabled by default.
