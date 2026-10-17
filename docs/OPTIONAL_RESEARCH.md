# Opt in to research records and a documentation source

Ordinary Markdown navigation remains usable on its own. When a task needs
durable questions, evidence, decisions, and recovery, an existing project can
opt in to the same ResearchStore used by configured Kernel projects. This does
not require a model, database, external service, or a new directory layout.

## Enable records for the selected project

From the Kernel repository, choose an existing project outside the code repository:

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-study'
python -B -X utf8 mining_kernel.py enable-research --project-root $projectRoot --project-id study-01
```

This adds only `research_project.json`, containing a schema version and project
ID. It preserves the project's entry and materials; it does not create a model,
empty record files, or a Research Map. Records appear under `research/records/`
when an explicitly requested write operation commits its first transaction.

The same ID returns `already_enabled` without rewriting the file. An existing
`flac3d_project.yaml` is validated and reported as `legacy_present`, with its
existing ID; it is not converted. Conflicting configurations, a changed neutral
ID, or records without an owning configuration require explicit resolution.
Neither `project-context` nor an ordinary lookup enables records automatically.

The neutral configuration accepts optional `entry`, `research_map`, and
`route_policy` fields; see the [schema](../schemas/research_project.schema.json).
It identifies a research project, not an installed software product. It does
not infer a software version or enable execution.

## Use existing materials

The existing [material and evidence-review commands](R2_QUICKSTART.md#register-a-local-material)
also work with the neutral configuration. Register the selected input, then
pass the returned Asset and Evidence IDs to `task-start`. A neutral project's
default task is `evidence_review` in the `research` workflow, which has no
solver or model checks. Keep the user's question and intended claim explicit.

Use `task-record-evidence-review` to save the actual reading, a provisional
judgment, and its limits. A registration or matching hash alone does not mean
the material was substantively read. No synthetic product configuration is
needed for an ordinary research task.

## Query a selected local documentation source

The first source connection reuses the local official Itasca documentation
provider. It reads one registered HTML page and checks an exact command name.
It does not call an external MCP server, search the web, or execute FLAC3D.

The Host/operator selects and registers an established official copy, its
version, and page digest using the [local documentation guide](R1_DOCUMENTATION.md).
Keep that host-local registration outside shared research data. The query does
not create trust registrations or silently repin changed pages.

For example, after registering the applicable source:

```powershell
$registration = 'D:\replace-with-host-selected\config.local.documentation.json'
python -B -X utf8 mining_kernel.py documentation-record --project-root $projectRoot --task-id command-query-01 --question "Is zone cmodel a documented command name for this target version?" --registration $registration --page flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.cmodel.html --command "zone cmodel" --product flac3d --product-version 9.6.44
```

Replace the target version and page with the ones actually needed. A
documentation build is not evidence of the installed engine's version.
The operation obtains the result directly from the provider; it does not accept
a caller-supplied verification-result JSON as proof.

The returned `documentation_result` retains the provider's status, source ID,
document family/build, page/anchor, query and page digests, timestamps, coverage,
and unchecked scope. The CLI returns a receipt with those details and record
IDs, rather than echoing the entire transaction; use `show` for full records.
The Python function also returns full task and Decision data. The record transaction links the question, proposed claim,
route, derived query snapshot, evidence, provisional Decision, and task state.
The snapshot is embedded in an Asset's `payload`; official HTML and the Host's
registration/root paths are not copied into the records.

`VERIFIED` covers the exact command name only. It does not establish options,
command order, full-script validity, numerical behavior, or engineering
suitability. Synthetic registrations require `--task-context synthetic` and
can return only `SYNTHETIC_VERIFIED`; they cannot verify a production request.

`CANNOT_VERIFY` observations are saved with their reason and an `INSUFFICIENT`
judgment. The CLI exits 2 even though the observation was recorded. A completed
task here means that the bounded query observation was saved, not that the
source check passed. Successful observations still carry a provisional
research judgment and unresolved broader coverage. No Run or engineering
Verification record is created.

For a query without any writeback, continue using `documentation-check` from
the local documentation guide; that command remains read-only.

## Recover the observation

These commands read records without reopening the documentation source:

```powershell
python -B -X utf8 mining_kernel.py project-context --project-root $projectRoot
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task command-query-01
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id command-query-01 --section packet
```

Use the returned Decision ID with `show --section assessment` for the query,
source registration summary, full result, and coverage; use its Asset ID with
`show --section payload` for the embedded snapshot. Navigation identifies the
snapshot as an embedded record, not as a file it has inspected.

Repeating the same `documentation-record` request and task ID returns the
saved observation with `replayed=true` and `query_performed=false`. It does
not refresh the source or timestamps. A different request under the same ID
is rejected. Use a new task ID for a new query or a fresh source check.
`resume` and `show` do not need the original source or its registration.
Replaying the query command still needs the registration metadata to match
the saved request; it does not need the original HTML page.

A later scoped `evidence_review` task can explicitly cite the returned Asset,
Evidence, and Decision IDs. Its snapshot hash can be checked from the ledger,
but the original documentation is not thereby reread or revalidated. Saved
reading state and current source checks remain distinct.

## Keep one current authority

Enablement and queries do not rewrite `START.md`. When the user adopts a saved
task as the current research state, update the entry with its task ID and a
`resume` command or record pointer, keeping detailed judgments in the records.
Historical reports can remain linked as history. Do not maintain a second
editable copy of the same current judgment in the entry.

The user continues to decide goals, boundaries, and finish or handoff criteria.
Provider coverage limits describe what the query established; they do not
automatically add new work to the user's task. No external connector, account,
or solver is enabled by opting in to records.
