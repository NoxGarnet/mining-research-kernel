# Bring an existing project into a lightweight workflow

Use the project's existing files and entry points. No migration, new workspace,
FLAC3D configuration, or research ledger is required. `init-workspace` creates
a new or empty workspace; it must not be run against existing research files.

## Locate the current task

From the Kernel repository, point navigation at the selected project:

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-roadway-study'
python -B -X utf8 .\mining_kernel.py project-context --project-root $projectRoot
```

Replace the path with the actual project directory. This command reads entry
files and any existing configured Kernel records; it does not recursively
discover files or read the cited research inputs. If no `START.md` or `README.md`
exists, it reports that gap without creating either file. Read relevant entries
in full before relying on a truncated preview. See [navigation details](PROJECT_CONTEXT.md).

The Agent first recovers the user's current request and existing project
instructions. Locate only the files needed for that request, using paths the
user or entry supplies, then a focused search if necessary. Keep original
models, observations, literature, scripts, and existing outputs where they are.
A filename alone does not establish which case, revision, or software version
is relevant. Report missing or ambiguous inputs instead of guessing.

The user decides the goal, deliverable, boundaries, and completion or handoff
criteria. Recover settled decisions instead of asking again; ask about
consequential gaps as needed. Criteria need not all be known at the start.
Agent suggestions and pending decisions are separate from user agreement.
Continue authorized work that does not depend on an unresolved decision.

## Add only the missing entry

When authorized to establish continuity, update the existing authoritative
entry, or add a small `START.md` if no suitable entry exists. Preserve existing
instructions and content; do not replace `README.md` or `AGENTS.md` with starter
templates. If a decision log or Kernel record already owns a judgment, link to
it instead of keeping a second current version.

For example, after the user has requested a limited script review:

```markdown
# Roadway support review

## Current question
Check the supplied model's support installation sequence.

## Scope and decisions (as needed)
User-confirmed: deliver a file and documentation review with sources and limits.
Agent suggestion: a solver comparison could be a separate follow-up.
Pending decision: whether that follow-up is useful; it does not block this review.

## Tools and materials
Software version: not yet confirmed.
[Supplied script](model/main.dat)

## Current understanding and next step
The input location is recorded; its contents have not yet been reviewed.
Read the relevant script section and locate version evidence before checking
version-specific commands.
```

These are illustrative paths and user decisions, not facts to copy into a real
project. Use only notes relevant to the actual request; no field is mandatory.
No `inputs/`, `work/`, `results/`, or `knowledge/` directory is required.

## Do the work and write back

For FLAC3D, follow the [bounded review workflow](FLAC3D_FIRST_TASK.md). For other
tasks, use their applicable materials and checking method without claiming that
a folder or registered adapter provides execution support.

Keep a substantive result in the project, with source locations, what was
actually read or checked, conclusions and limits. A report is useful when those
details would overwhelm the entry; otherwise a short entry update is enough.
Update the entry with the current question, a short result and its authoritative
link, and the next action or delivery state within the user-confirmed scope.
Follow later user changes. Report gaps that prevent the agreed delivery;
unrelated or explicitly deferred findings can remain for handoff without
automatically becoming additional tasks. Ordinary lookups need no writeback.

The [anonymous FLAC3D example](../examples/flac3d_review/README.md) shows an
existing project after a limited review, including a source-backed report and
an entry for the next conversation. Its teaching input is not an engineering model.

## Continue in another conversation

Give the next Agent the entry path and the actual request, for example:

> Read this project's START.md and the linked review. Explain the user's current
> goal, confirmed decisions, findings and evidence, remaining limitations, and
> suggested next actions. Distinguish suggestions from user decisions. This
> request is read-only; do not run the model or change files.

The read-only scope above belongs to that example request; ordinary project
continuation follows the user's actual authorization. Recheck a source when a
new conclusion depends on its current contents. A saved report or navigation
preview does not prove that the underlying inputs remain unchanged.

## Optional workspace navigation

One project can use `project-context` directly. If projects already live under
`mining/projects/<name>/`, an explicit root `INDEX.md` can link to their entries;
keep project status in those entries, not in the index. `workspace-context`
recognizes `projects/<name>/START.md` or `README.md`; it does not discover arbitrary
external directories or choose the user's project.

If a separate lightweight entry refers to materials elsewhere, record their
actual location without moving them or creating symlinks to satisfy navigation.
`project-context` marks paths outside its explicit root as
`unsafe_path_not_followed`; it does not read them. Open only selected external
materials with ordinary reading tools within the user's task scope, or navigate
the original project directly. Do not claim the Kernel followed or verified them.
