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

## Resume only what is needed

If you have a project path but no Task ID, start with the read-only
[`project-context` navigator](PROJECT_CONTEXT.md). It also works for ordinary
project folders without initializing a kernel store. Reading does not require
registration or judgment writeback.

For a later task or process, use the compact read-only view first:

```powershell
python mining_kernel.py resume --project-root path/to/project --task task-demo
```

It shows the persisted research question, task state, relevant Decision
summaries, material/version statuses, related routes and failures, gaps,
candidate next actions, citations and exact expansion commands. The default
view targets 4000 Unicode characters. If the records exceed that budget, the
view reports overflow while retaining the judgment summary, key limitation
previews, version/material status and candidate action; repeated material rows
and expansion commands are compressed. The reported character count is the
count of the final serialized view. It never treats truncation as proof that a
limitation is absent. `resume` does not create a Task or Decision, rebuild the
Research Map, or re-hash source materials.

When several Decisions are related, `review_record_ref` and explicit lineage
references determine the current branch; inherited Decisions are reported as
history. Same-task branches without an inheritance link remain an explicit
`unresolved_current_conflict` instead of being selected by file order. The
`judgment_selection` block gives the current, historical and conflicting IDs,
and the listed `show` commands target the current branch.

Expand one persisted record or section only when needed:

```powershell
python mining_kernel.py show --project-root path/to/project --record-id task-demo --section packet
python mining_kernel.py show --project-root path/to/project --record-id decision-id --section judgment
```

When a continuation binds a historical Decision, use its returned expansion
argv or name the exact revision:

```powershell
python mining_kernel.py show --project-root path/to/project --record-id decision-id --revision 1 --section judgment
```

Omitting `--revision` retains the latest-record lookup. An unavailable explicit
revision is an error; it is never replaced with the latest one. Pending
continuations expose inherited context separately from a new current judgment.

The previous `task-inspect` command remains the complete TaskPacket contract
for callers that need every field. `resume` and `show` are projections over
the same transaction records, not a second authority.

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

For a read-only task that must use already registered materials, pass the
existing Asset and Evidence IDs explicitly. Save this as `request.json`,
replacing the example IDs with the registration result's `asset.id` and
`evidence.id` (do not invent IDs):

```json
{
  "task_id": "material-review-1",
  "question_statement": "Which registered material is available for review?",
  "claim_statement": "The task preserves material provenance separately from reading and verification.",
  "task_type": "mining_research_kernel.task.evidence_review",
  "maturity": "exploratory",
  "max_runs": 1,
  "task_context": "production",
  "asset_refs": ["asset.local.example"],
  "evidence_refs": ["evidence.local.example"]
}
```

```powershell
python -B -X utf8 mining_kernel.py task-start --project-root path/to/project --request-json '@request.json'
```

The resulting TaskPacket adds these IDs to `required_reads` and
`next_action.input_refs`, and exposes `material_reads` with locator,
registration, content-hash, reading and verification statuses. Project-relative
sources are re-hash checked; missing or changed bytes block the task without
consuming a Run. Caller-labelled external sources remain `not_reloaded` until
a Host supplies them again. This route does not select the FLAC3D
`static_check` gate. Use `mining_research_kernel.task.static_check` separately
when script/model static checking is required; production static checking
remains blocked while that capability is unimplemented.

After the Host has actually read the selected material, persist that bounded
read and its provisional judgment through the public operation below. The
assessment must cover every material, include a concrete line/field/table
locator and the observed registered hash, and must keep scientific validation
incomplete when no independent validation was performed:

### Complete first-review request

For an isolated offline example, run the following from the repository root.
It creates a new temporary project and one artificial text source; it does not
run a model or use a real research project. Retain the printed directory for
the following commands. The initializer's other placeholder files are not
research evidence and are not registered here.

```powershell
$projectRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('kernel-review-' + [guid]::NewGuid().ToString('N'))
python -B -X utf8 mining_kernel.py init-flac3d-project $projectRoot --project-id review_demo
if ($LASTEXITCODE -ne 0) { throw 'Project initialization failed' }
$sourcePath = Join-Path $projectRoot 'cases/observation.txt'
[System.IO.File]::WriteAllText($sourcePath, "Synthetic fixture: 8 detections in 10 observations.`nNo physical validation or independent replication.`n", [System.Text.UTF8Encoding]::new($false))
$registration = python -B -X utf8 mining_kernel.py register-local-material --project-root $projectRoot cases/observation.txt --material-kind project_record | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Material registration failed' }
$registration.asset.id
$registration.evidence.id
Get-Content -LiteralPath $sourcePath
$observedHash = python -B -X utf8 -c "import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())" $sourcePath
if ($LASTEXITCODE -ne 0) { throw 'Source hash read failed' }
if ($observedHash -ne $registration.asset.content_sha256) { throw 'Source changed; do not submit the review' }
$observedHash
$projectRoot
```

Use the task request above with those IDs and `--project-root $projectRoot`.
`task_context: production` describes the normal evidence-review path, not a
claim that this artificial source is real experimental data. Save the complete
JSON below as UTF-8 `assessment.json` in the current directory. Replace
`asset.local.example`, `evidence.local.example`, and `OBSERVED_SHA256` using
the registration result, TaskPacket and hash of the bytes actually read.
Use the contents below only for this fixture; for real materials supply your
actual reading, locators, interpretation and limitations.

```json
{
  "scope": "material_reading_and_evidence_synthesis_only",
  "material_reads": [
    {
      "asset_id": "asset.local.example",
      "evidence_refs": ["evidence.local.example"],
      "observed_sha256": "OBSERVED_SHA256",
      "reading_status": "READ",
      "verification_status": "NOT_VERIFIED",
      "locator": {"path": "cases/observation.txt", "kind": "lines", "value": "1-2"},
      "summary": "Read both lines: 8 detections in 10 observations; no physical validation or independent replication.",
      "numeric_check_status": "NOT_APPLICABLE",
      "scientific_validation_status": "NOT_VERIFIED",
      "gaps": ["Artificial fixture only", "No independent replication"]
    }
  ],
  "material_gaps": [],
  "judgment": {
    "status": "PROVISIONAL_WITH_GAPS",
    "summary": "The fixture reports 8 detections in 10 observations; this is not physical validation.",
    "supported_evidence": ["evidence.local.example"],
    "gaps": ["Artificial fixture only; no physical validation", "No independent replication"],
    "next_action": {"action": "Obtain independent observations before generalizing", "executable": false}
  }
}
```

For this one-material task, `material_reads` has exactly one entry. In a larger
task include each TaskPacket material once, with exactly its `evidence_refs`;
do not add unlinked materials or silently omit unread ones. This operation
does not accept `NOT_READ` as a reading result: finish the scoped reading or
report a material gap through an appropriate workflow instead of claiming a
read. A matching registered hash is not proof that the Host read the source.

| Field | Meaning and accepted values |
|---|---|
| `scope` | The literal string `material_reading_and_evidence_synthesis_only`, not an object. |
| `reading_status` | `READ`, `READ_WITH_LIMITS`, `READ_INSUFFICIENT`, or `REUSED_FROM_PERSISTED_RECORD`. For reuse, add a real `reused_from_decision` ID; do not call reuse a fresh read. |
| `locator`, `summary` | A concrete location and the bounded content actually read; identify uninspected portions in `gaps`. |
| `numeric_check_status` | `NOT_APPLICABLE`, `CONSISTENT`, `INCONSISTENT`, or `PARTIAL`. Copying source numbers is not a numerical consistency check. |
| `verification_status`, `scientific_validation_status` | `NOT_VERIFIED` or `PARTIALLY_VERIFIED`; this workflow cannot mark scientific validation complete. |
| `material_gaps` | Optional list; each item contains `asset_id`, `reason`, and `next_action`. It does not replace the required material reading entries. |
| `judgment` | A current summary, actual supporting Evidence IDs, nonempty limitations and a next-action object. Status is `PROVISIONAL_WITH_GAPS` or `INSUFFICIENT`. Use `executable: false` when the action is not authorized or its prerequisites are missing. |

```powershell
python -B -X utf8 mining_kernel.py task-record-evidence-review `
  --project-root $projectRoot material-review-1 `
  --operation-id review-1 --assessment-json '@assessment.json'
```

This appends a `Decision` and a `TaskState` revision only. It does not create a
Run or Verification and does not change Asset/Evidence provenance. A later task
can recover the judgment, not only the material list, by passing the Decision
ID in `refs.decisions`; the resulting TaskPacket exposes `recovered_decisions`.
When a new question reuses a prior read without reopening source bytes, use
`reading_status: "REUSED_FROM_PERSISTED_RECORD"` and provide
`reused_from_decision`; this remains distinct from a fresh Host read.

### Later judgment: inherited materials, replacement judgment fields

Use the short incremental route for a substantive later judgment change within
the existing task's material scope. For new materials, register them explicitly,
create a scoped evidence-review task referencing the old Decision, and save one
complete review. Do not immediately duplicate a completed review with an increment.

**An incremental request is not a JSON patch or an automatic text merge.**
It inherits material reading records and their revisions, and links the old
Decision as history. The following supplied values become the new current
judgment in full:

| Request field | New current value |
|---|---|
| `statement` | `judgment.summary` (the request field is named `statement`, not `summary`). |
| `status` | `judgment.status`. |
| `supported_evidence` | The complete supporting Evidence ID list for this current summary, not only newly cited IDs. |
| `gaps` | The complete remaining limitation list, including unchanged limitations. |
| `next_action` | The complete current next-action object, updated to reflect work already done. |

`change_kind: supplement` labels the relationship to the previous judgment; it
does not append text or union lists. `changed_fields` records what changed; it
does not control which fields are replaced. Even a supplied field not listed in
`changed_fields` is used. List changes accurately, but supply all required
judgment fields. `inherited_from` preserves lineage, not an automatically merged
current summary. The Kernel does not verify that the caller retained every
scientific limitation. Do not replace still-applicable observations or gaps with
"same as before" or "see previous Decision".

For this fixture, suppose a later interpretation expresses the already-read
8/10 count as a descriptive 80% and clarifies that it is not a calibrated rate.
No source changes or new materials are involved. The following `update.json`
retains the original observation and both limitations while adding that insight:

```json
{
  "base_decision_id": "decision.example",
  "base_revision": 1,
  "change_kind": "supplement",
  "status": "PROVISIONAL_WITH_GAPS",
  "statement": "The fixture reports 8 detections in 10 observations (80% descriptively), not a calibrated detection rate or physical validation.",
  "supported_evidence": ["evidence.local.example"],
  "gaps": ["Artificial fixture only; no physical validation", "No independent replication", "The descriptive fraction is not a calibrated detection rate"],
  "next_action": {"action": "The descriptive fraction is clarified; obtain independent observations before generalizing", "executable": false},
  "changed_fields": ["summary", "gaps", "next_action"]
}
```

Replace `decision.example` and `base_revision` with the actual current Decision
ID and revision from `resume`/`show`, not the TaskState revision. Replace the
Evidence ID as above. Old Decisions remain immutable; an update creates a new
Decision (normally revision 1) and advances the TaskState revision.

```powershell
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task material-review-1
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id ACTUAL_DECISION_ID --section judgment
python -B -X utf8 mining_kernel.py task-record-judgment-update `
  --project-root $projectRoot material-review-1 `
  --operation-id interpretation-1 --update-json '@update.json'
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task material-review-1
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id NEW_DECISION_ID --section judgment
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id material-review-1 --section operation_results
```

Replace `ACTUAL_DECISION_ID` before the update and `NEW_DECISION_ID` afterwards
with the returned IDs. Check that the new summary, all three limitations and
next action are visible; expand `show --section judgment` when `resume` reports
overflow. The old Decision should appear in history, material reading statuses
remain unchanged, and the operation result reports `run_created: false` and
`verification_created: false`. Use targeted judgment or operation-result
expansion before requesting the entire material packet.

If a write command's large output is truncated, inspect `resume` and
`show --section operation_results` before attempting another write. Reuse the
same operation ID only for the same request; do not create a second operation
just to recover its output. No substantive change means no update.

The request is limited to 2000 Unicode characters when serialized by
`json.dumps(update, ensure_ascii=False, indent=2)`, not merely the size of the
statement or the whitespace in the submitted file. It checks the base Decision
revision and Evidence IDs, and
appends one Decision plus one TaskState revision. It inherits material reads
and their recorded Asset/Evidence revisions, and never creates a Run or
Verification. The inherited `reading_status`, `content_status` and
`verification_status` are preserved; inheritance is not a new read or
verification. Project-relative source bytes are checked before inheritance;
missing or changed bytes require a new material revision.

Validation is completed before the single transaction is committed. Errors
name the input path, for example `update.base_revision`,
`update.next_action.action`, `update.supported_evidence[0]` or
`packet.material_reads[0].source`. `supported_evidence` must be a non-empty
list of Evidence IDs from the current task's material reads, and
`next_action` must contain a non-empty string `action` and boolean
`executable`. Unknown references, revision conflicts, stale/incorrect
inheritance, unrelated Evidence, verification promotion, changed source
bytes and conflicting reuse of an operation ID are rejected without a
partial write.

The `resume` view is the derived handoff for the new judgment: it exposes the
current Decision revision, inherited material revisions, limitations and next
action; `show` expands the immutable old/new records. No handoff file is
created or used to overwrite hand-written research text.

## Boundaries

R2 accepts only the bounded R2 record and relationship contracts. Unknown record
types, missing references, revision gaps, conflicting operation IDs and cross
project paths fail closed. The project writer is exclusive and interrupted
transactions are recovered without silently stealing a live lock.

The real Itasca HTML reader remains an independent R1 capability. R2 does not
turn a fake result into an FLAC3D result, and it does not enable `itasca-mcp`.
Real Zotero access, the production FLAC3D `static_check` implementation and
live Itasca execution remain outside this release stage.
