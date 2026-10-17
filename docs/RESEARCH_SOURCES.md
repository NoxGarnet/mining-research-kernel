# Use literature and software documentation for one research question

This workflow joins the existing lightweight project, optional research
records, Zotero reading, and version-bound documentation query. The Agent
organizes the work; the user chooses the question, deliverable, scope, and
finish or handoff criteria. Recover settled choices from the conversation and
project entry, and ask only about consequential missing information.

For official paragraphs and optional Itasca MCP documentation discovery, use
[documentation reading](ITASCA_READING.md). For two or more distinct papers
with page-bounded comparison cells, use [literature comparison](LITERATURE_COMPARISON.md).

## Read from an existing Zotero connection

Select an explicitly configured Host-side Zotero stdio registration. The
Kernel starts that selected runtime as a read-only client. It does not
install a server, edit application settings, inspect a library database, or
register tools in an Agent's global configuration. Ordinary Markdown work
still needs no connection or research records.

The Host registration contains only the connection and source identity:

```json
{
  "schema_version": 1,
  "kind": "zotero_stdio",
  "instance_id": "0123456789abcdef0123456789abcdef",
  "library_id": "users/0",
  "command": "C:/replace-with-host-runtime/zotero-mcp.exe",
  "args": ["serve", "--transport", "stdio"],
  "timeout_seconds": 30
}
```

This is a placeholder, not a runnable setup. Replace the executable and
arguments with the already installed runtime or launcher configured for the
intended library. An optional `cwd` must be absolute. Use a stable opaque
instance ID for this Zotero instance; the example ID identifies no real
library. `users/0` is a local API identifier, not a global account ID.

**Selecting this registration authorizes starting its command.** Keep it
Host-owned, outside imported papers and project source catalogs. Do not
derive executable paths or arguments from literature, search results, or
model files. No credentials or environment overrides belong in this file.
The client only permits the Kernel's existing read operations and does not
forward arbitrary tool names. Connection details stay out of research records.

With that one-time Host setup available, the Agent can use ordinary commands
instead of writing a reader callback or a capture JSON for every reading:

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-study'
$zoteroHost = 'D:\replace-with-host-config\zotero.json'
python -B -X utf8 mining_kernel.py enable-research --project-root $projectRoot --project-id study-01
python -B -X utf8 mining_kernel.py zotero-search --registration $zoteroHost --query "short query" --collection-key COLLECT1 --limit 5
python -B -X utf8 mining_kernel.py zotero-read --registration $zoteroHost --project-root $projectRoot --task-id paper-01 --question "What does this selected passage establish?" --item-key PAPER001 --pdf-key ATTACH01 --pages 1,3-4 --collection-key COLLECT1
```

The keys above are placeholders. Choose actual items and PDF attachments
from the user's selected scope. Library retrieval does not find new papers
on the web. Search performs an availability preflight so an unavailable
source is not interpreted as an empty library.

`--pages` uses one-based PDF page indices. The live receipt distinguishes
source calls from recording, returns bounded text for the Agent to read, and
explicitly labels text truncation. `--max-reading-chars` controls the returned
text budget. If text is clipped, read the necessary smaller range before
making a claim about the omitted portion. Text returned for reading is
transient; the ledger retains source locators, digests, and bounded excerpts,
as described in the [Zotero capture guide](ZOTERO_READING.md).

An identical task and source selection replays its saved observation without
starting the server. A new question, page selection, or fresh source check
needs a new task ID. Replay does not return the original full page text or
claim a fresh source read. The explicit PDF key removes attachment ambiguity;
metadata-only reading can omit page arguments and retains its limited status.
Replay still validates the selected Host registration. `resume` and `show`
require neither that registration nor the Zotero runtime.

## Obtain the relevant official documentation observation

Use the existing [local documentation query](OPTIONAL_RESEARCH.md#query-a-selected-local-documentation-source)
with the version, command, and page actually relevant to the problem:

```powershell
python -B -X utf8 mining_kernel.py documentation-record --project-root $projectRoot --task-id manual-01 --question "Is the relevant command documented for this target version?" --registration path/to/documentation-registration.json --page flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.cmodel.html --command "zone cmodel" --product flac3d --product-version 9.6.44
```

Replace the example values. The current official reader checks command names
in a Syntax section. It does **not** read all engineering guidance or verify
parameter values, construction sequences, complete scripts, or model validity.
If the question needs those details, retain that gap and read the appropriate
source separately; a successful syntax query does not fill it.

## Start one research review from selected observations

Take the Asset IDs returned by the source receipts. They must belong to this
project. Select at least one Zotero reading observation and one documentation
query observation; add further papers when the question needs them:

```powershell
python -B -X utf8 mining_kernel.py research-start --project-root $projectRoot --task-id comparison-01 --question "What do these sources establish for the proposed numerical study, and what remains open?" --asset-ref paper-01.asset.1 --asset-ref manual-01.asset.1
```

The response provides the selected source overviews, their Evidence IDs, and
a Markdown review template. It preserves distinctions between author claims,
saved reading observations, syntax verification, uncertain versions, and
engineering applicability. Missing or changed embedded observations are not
silently accepted. No original PDF, website, or manual is reopened here.

Read the overviews and expand `show --section payload` when needed. Use original
sources when the question exceeds the saved coverage. An old observation may
be useful without being a new reading of its source. If the sources disagree,
identify their conditions and cite each side; do not force a shared conclusion.

## Record a cited Markdown interpretation

Write a small UTF-8 Markdown note using the returned Evidence IDs:

```markdown
## Summary
The selected observations address different parts of the question.

## Findings
- The paper describes a method, while the manual observation establishes only a command name. [evidence:paper-01.evidence.1] [evidence:manual-01.evidence.1]

## Gaps
- The selected sources do not establish model parameters or engineering applicability.

## Next
Consider checking the conditions needed for the user's intended comparison.
```

Replace this example with the actual reading. Each finding must cite selected
Evidence. A locator check establishes coverage and identity, not semantic
support for a statement. Empty findings produce an insufficient review,
including when the default provisional judgment was requested.
Keep missing checks explicit, and distinguish a proposal from a user decision.

```powershell
python -B -X utf8 mining_kernel.py research-review --project-root $projectRoot --task-id comparison-01 --operation-id comparison-01.review-01 --review-file path/to/review.md
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task comparison-01
```

The command saves the review through the existing evidence-review operation.
Operation IDs are unique within a project; including the task ID avoids
collisions with a different task's review. Repeating the same ID and note is
idempotent, while changing the note under that ID is rejected.
The judgment remains provisional or insufficient. Source coverage limits are
retained even if the note omits them. A saved observation's matching hash
does not verify the original source or the research conclusion. No solver,
experiment, Run, or engineering Verification is produced.

The structured review is the current authority for that task. The Markdown
file is an import artifact; do not maintain it as a second independent current
judgment. When the user adopts this task as project state, add its record
pointer to the existing entry. The commands do not rewrite START or choose a
research stopping point. Further work still follows the user's objective and
authorization.
