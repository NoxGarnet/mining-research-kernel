# Start with read-only project navigation

For first-time use with existing files, see [bring an existing project](EXISTING_PROJECT.md).
It explains how an Agent can add or update an entry without migrating materials.
The command below remains read-only and never creates that entry itself.

For a question about an existing project, you do not need to register files or
create a Task first. From the repository directory:

```powershell
python -B -X utf8 mining_kernel.py project-context --project-root path/to/project
```

This accepts an ordinary directory without `flac3d_project.yaml` or a research
store. It reads at most 64 KiB each of `START.md` and `README.md`, displaying
short entry previews and extracting simple inline local Markdown links and
backtick-quoted relative file paths such as `docs/decisions.md` or `main.dat`. It
does not follow those links, inspect material bytes, hash sources, interpret
entry text as instructions, or scan the surrounding workspace. Missing entries
are reported; no purpose or next research action is invented.

For example, an existing project entry may contain:

```markdown
# Support study
Question: which evidence is sufficient for the next bounded comparison?
[Selected observations](inputs/observations.csv)
[Known limitations](notes/limitations.md#scope)
```

Navigation locators preserve the anchor where supplied; no page/line location
is guessed. Paths escaping the explicit root are not followed. Target existence
is not checked and target versions are not revalidated. A link is not evidence
that the file was read or its contents are true. Ordinary reading tools can
open the selected location when the Agent actually needs it.

An optional **existing, explicit** JSON material list can be passed:

```json
{"materials": [{"path": "inputs/observations.csv", "title": "Selected observations"}]}
```

```powershell
python -B -X utf8 mining_kernel.py project-context --project-root path/to/project --manifest materials.json
```

The manifest is project-relative and at most 128 KiB. This command does not
create a catalogue, convert other manifest formats, or discover manifests by
scanning. It is optional metadata for locating sources, not a new authoritative
research record. Only simple inline Markdown links are supported; reference
links, nested-parenthesis links, embedded HTML and external URLs are not crawled.
Backtick paths use a conservative suffix list (documents, tables, configuration,
DAT/FIS/Python files), contain only letters/numbers/underscore/dot/hyphen and
directory separators, and are deduplicated within each entry. Spaces, commands,
expressions, directories without filenames, absolute paths and parent traversal
are not recognized as inline material paths; use a Markdown link or explicit
manifest for other valid filenames. Fenced examples are excluded. `entry_line`
locates the mention in the entry, not a verified location inside the source.
Bare filenames are literal entry-relative candidates only: prose may describe a
filename used inside several case folders. No existence or contextual location
is inferred; inspect the entry's cited line before treating it as a source path.

## Projects with persisted kernel records

For a configured kernel project, the command reuses the validated transaction
reader and existing current/history/conflict selection from `resume`:

- Tasks expose their question preview, saved revision/state, current-judgment
  preview, historical/conflicting counts and exact `resume_argv`.
- Asset entries expose their recorded locator and an exact `show_argv`.
  Caller-labelled paths remain unresolved; the caller must supply a location.
- Failure entries are **project-wide candidates**, not automatically applicable
  blockers. Expand them and choose the relevant task before applying their scope.
- Decision entries remain inspectable; their existence or timestamp never makes
  them a project-wide current conclusion.

No task is automatically selected (`active_task` is null), even when only one
exists. The project question may be in entry text or individual task questions;
the tool does not synthesize a new project goal. Same-task competing judgments
remain explicitly conflicting. The `record_sequence` identifies the inspected
transaction snapshot, not a proof that source materials are still current.

The default page contains at most eight entries, with totals and `next_argv` for
remaining entries. Whole rows are moved to subsequent pages to target 4000
serialized Unicode characters. Use `--offset` and `--limit` (1–20), or execute the returned
argv array directly using a subprocess API. Arrays contain the current Python
interpreter, absolute CLI/project paths and UTF-8 mode; do not join them into an
unquoted shell string. Previews may be truncated and are explicitly marked.
Expand before relying on a judgment's detailed limitations or applicability.
A single unusually large entry may exceed the target and is explicitly flagged
as `oversized_single_entry`; it is not silently dropped or replaced with an
error. Existing `resume` keeps its separate character-budget contract.

The store accepts the optional neutral `research_project.json` configuration
or the existing `flac3d_project.yaml`; both together are rejected. See
[optional research records](OPTIONAL_RESEARCH.md) for explicit enablement and
documentation-query writeback. Embedded query snapshots expose a `show`
command rather than a filesystem target. Unconfigured `research/records` are
reported but not interpreted. Malformed
configuration or transactions cause an error rather than a healthy-looking
empty view. The saved Research Map is not read or rebuilt. Validated store
loading currently reads the transaction history; this is not a low-I/O index
or a semantic search service. No performance improvement is claimed.

## Read, then decide whether to record

1. Use `project-context` to find a task or source entry.
2. Use its `resume`/`show` argv for a stored judgment, or an ordinary reader for
   the specifically needed source. Expanding a record is not rereading a source.
3. Answer directly if nothing changed. Do not write just to document a lookup.
4. Persist only a substantive update that needs continuity. For **new materials**,
   register them explicitly, create a scoped task citing the old Decision, and
   save one evidence review containing the revised judgment. If that already
   records the final judgment, do not immediately duplicate it with an increment.
   For a **later judgment change within the existing task material scope**, use
   the short incremental update. Neither route provides scientific verification.

Project navigation creates no Task, Asset, Decision, Failure, Run, Verification,
reading-status update or file. Existing `resume`, `show`, `task-inspect` and
writeback contracts are unchanged. Use `-B` to suppress Python bytecode caches.
