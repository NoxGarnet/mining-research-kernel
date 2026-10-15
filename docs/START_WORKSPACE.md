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

After doing authorized work, write back ordinary text in that project's
`START.md`, for example:

```markdown
## Current understanding
The supplied model lists the installation sequence in `model/main.dat` (not yet independently checked).

## Gap and next step
FLAC3D version is unknown. Confirm it, then check the relevant command and parameter against the matching official documentation.
```

Ordinary reading with no substantive change does not require a research record
or writeback. Existing user authorization continues within its stated scope.
Add further projects or knowledge links only when they exist. The index is
navigation; keep project status and evidence in the project. Existing FLAC3D
kernel configuration and the generic record system remain optional later
steps, with compatibility to be addressed before generic records are enabled.
The synthetic workflow demonstrates kernel mechanics only; it is not PFC, AE,
or a real FLAC3D solve.
