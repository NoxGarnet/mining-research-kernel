# R2 task and evidence quick start

R2 is the first usable Agent/Kernel loop. The Agent supplies a structured
research request; the Kernel loads the configured project, selects the FLAC3D
workflow, validates the request, stores a TaskState transaction, and returns a
Task Packet. A later process can inspect that packet without chat history.

The R2 example uses a synthetic fake executor. It demonstrates state,
provenance and recovery mechanics. It does not run FLAC3D and does not prove
numerical, physical or engineering validity.

The production FLAC3D `static_check` action is currently unimplemented. Its
gate remains applicable and `PENDING`, while a new production task is blocked
with `static_check_unimplemented`. Synthetic fixture tasks use their declared
synthetic capability and remain runnable.

## Start a task

Create an initialized project first:

```powershell
python mining_kernel.py init-flac3d-project path/to/project --project-id demo_project
```

Create a request JSON file. The minimum useful request is:

```json
{
  "task_id": "task-demo",
  "question_statement": "Does the bounded synthetic route complete?",
  "claim_statement": "The kernel workflow mechanics complete for this fixture.",
  "task_type": "mining_research_kernel.task.fake_execution",
  "maturity": "exploratory",
  "max_runs": 1,
  "task_context": "synthetic"
}
```

Run and inspect it from separate processes:

```powershell
python mining_kernel.py task-start --project-root path/to/project --request-json @request.json
python mining_kernel.py task-inspect --project-root path/to/project task-demo
```

The JSON Task Packet's `state`, `next_action`, `stop_conditions`,
`allowed_tools`, `verification_gates`, `prohibitions` and `writeback_targets`
tell the Host Agent what it may do. A blocked packet has no executable
`next_action` and includes a resume condition. The request is read only; values
entering authoritative records are reduced to project-relative paths or caller
labels.

## Run the synthetic route

Only a synthetic task may use the R2 fake executor:

```powershell
python mining_kernel.py task-run-fake --project-root path/to/project task-demo --operation-id fake-op --fixture-id fixture-a
```

The Kernel reserves one run before dispatch, writes a five-stage Run Bundle,
records a RunReference, synthetic-result Asset, Evidence and a Verification,
then appends a new TaskState revision. Repeating the same operation and fixture
returns the recorded result without dispatching again. Reusing the operation ID
with another fixture is rejected. An unknown execution outcome remains failed
and is not automatically retried.

The acceptance record is scoped to `kernel_workflow_only` and retains unresolved
risks for missing FLAC3D execution, numerical, physical and engineering checks.

## Add synthetic Zotero-backed evidence

For a source task, add `literature_evidence` to the request with project-relative
paths for a sanitized snapshot and a separately retained local source:

```json
{
  "snapshot_path": "snapshot.json",
  "source_path": "source.txt",
  "item_key": "ITEM1",
  "locator": {"kind": "paragraph", "value": "p1"},
  "question_statement": "Does the bounded synthetic route complete?",
  "claim_statement": "The kernel workflow mechanics complete for this fixture."
}
```

The exact snapshot item is checked, and both snapshot and local-source hashes
are recorded. Metadata identifies a source; it does not support a Claim by
itself. The bridge creates document Evidence linked to a derived Asset and a
proposed Claim, with a source locator and no automatic scientific conclusion.

## Rebuild the Research Map

```powershell
python mining_kernel.py research-map-rebuild --project-root path/to/project
```

The CLI command writes the rebuilt map to the project's configured map path
(normally `research/map.json`) and returns the same `nodes`/`edges` view. The
map is rebuilt from immutable transactions. It contains the question,
claim, route, assets, evidence, run reference and verification relationships.
Deleting the configured derived map and running the command again reproduces
the same content. TaskState is persisted but intentionally excluded from the
research graph view.

The lower-level Python call `ResearchStore.rebuild_research_map()` keeps a
pure in-memory return when called without an output path; pass a relative path
when a library caller wants to persist a non-default view.

## Register a local material

Use the public `ResearchStore.register_local_material` method or the matching
CLI for an explicitly selected file. Choose `primary/original`,
`project_record`, or `derived_reading_note`. The method creates stable hashed
Asset/Evidence records and their `evidence_derived_from_asset` relationship;
an optional existing Claim can receive a `source_documents_claim` edge. A
derived reading note is always recorded as derived. The records preserve
provenance and do not establish scientific or engineering validity.

The SDK-free example performs the same calls directly:

```powershell
python examples/reference_agent.py --project-root path/to/project
```

## Boundaries

R2 accepts only the bounded R2 record and relationship contracts. Unknown record
types, missing references, revision gaps, conflicting operation IDs and cross
project paths fail closed. The project writer is exclusive and interrupted
transactions are recovered without silently stealing a live lock.

The real Itasca HTML reader remains an independent R1 capability. R2 does not
turn a fake result into an FLAC3D result, and it does not enable `itasca-mcp`.
Real Zotero access, the production FLAC3D `static_check` implementation and
live Itasca execution remain outside this release stage.
