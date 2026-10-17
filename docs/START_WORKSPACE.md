# Start a lightweight workspace

Create a new or empty directory from a real research question. The command
creates only `AGENTS.md`, `INDEX.md`, and `projects/<ID>/START.md`.

```powershell
$starterRoot = 'D:\replace-with-user-chosen\mining'
python -B -X utf8 .\mining_kernel.py init-workspace $starterRoot --project-id roadway-support --question "核查现有巷道支护模型的安装时序"
python -B -X utf8 .\mining_kernel.py workspace-context --workspace-root $starterRoot
```

Replace the example value with a new or empty directory you choose outside
this code repository. Do not point it at existing research material.
If you already have a project, use the [existing-project guide](EXISTING_PROJECT.md)
to preserve its files and add only missing continuity notes.

`--project-id` for a new project is a 2–64-character lowercase slug (for
example, `flac3d`, `pfc`, or `ae`). This creation rule does not limit existing
project folder names: `workspace-context` also supports safe names such as
`PFC`, `AE`, Chinese names, and names containing spaces.

The starter records the question as text. Software/version is unknown and
inputs have not yet been located; neither the command nor its templates imply
that any materials were analyzed. `workspace-context` reads only the bounded
root index, reports every recognized project candidate, and returns a
`project-context` argv for each. Run the one for the project you choose:

```powershell
python -B -X utf8 .\mining_kernel.py project-context --project-root (Join-Path $starterRoot 'projects\roadway-support')
```

The user decides what this task should deliver, its boundaries, and when to
finish or hand it off. First recover what they have already said in the
conversation or project entry. If a consequential point is unclear, ask a
short question such as "What should this task deliver?" or "Is anything
explicitly outside this task?" Completion criteria can be clarified later;
do not require an intake form or ask the user to repeat settled decisions.
Continue authorized work that does not depend on an unresolved decision.

Use the optional scope notes in `START.md` to distinguish user-confirmed
decisions, Agent suggestions, and pending questions. Add only relevant notes;
these are ordinary text, not mandatory fields or CLI prerequisites. For example,
after the user has confirmed a limited inspection:

```markdown
## Scope and decisions (as needed)
User-confirmed: deliver a report on the supplied script's installation sequence,
with sources and limits. This task covers file and documentation review.
Agent suggestion: consider a separate solver comparison if it would help later.
Pending decision: whether to pursue that comparison; it does not block this report.
```

An Agent can propose next steps and carry out authorized work, but its proposal
is not a user decision. Record later user changes and assess this task against
the agreed scope. Items outside that scope or explicitly deferred by the user
can remain in the handoff; finding them does not automatically expand the task
or add new completion requirements. Gaps that prevent the agreed delivery
remain open and must be reported.

After doing authorized work, write back ordinary text in that project's
`START.md`, for example:

```markdown
## Current understanding
The supplied model lists the installation sequence in `model/main.dat` (not yet independently checked).

## Gap and next step
FLAC3D version is unknown. Within the agreed inspection scope, identify it from
the supplied files or ask the user, then check the relevant command and parameter
against the matching official documentation.
```

Existing project entries can adopt these notes through an ordinary text edit
when needed; rerunning `init-workspace` is not an update or migration command.

Ordinary reading with no substantive change does not require a research record
or writeback. Existing user authorization continues within its stated scope.
Add further projects or knowledge links only when they exist. The index is
navigation; keep project status and evidence in the project. If persistent
questions and judgments are needed, [enable research records explicitly](OPTIONAL_RESEARCH.md).
Ordinary Markdown use does not require this step; existing FLAC3D kernel
configuration remains supported without migration.
The synthetic workflow demonstrates kernel mechanics only; it is not PFC, AE,
or a real FLAC3D solve.
