# Read selected Zotero literature and keep research continuity

For direct CLI reads through an existing Host connection, followed by a
literature/documentation review without per-reading capture JSON, start with
the [research source workflow](RESEARCH_SOURCES.md). The capture/import APIs
below remain useful for external readers and offline observations.

Choose the research question and useful collection or items with the user.
Existing Markdown projects can keep their layout. Enable
[optional research records](OPTIONAL_RESEARCH.md) when durable reading and
recovery are useful; ordinary literature lookup needs no ledger.

## Find and select materials

Use the Host's installed Zotero MCP tools through the read-only source adapter.
The repository does not install Zotero, register a server, or hold credentials.
The Python adapter accepts a caller-injected `reader(operation, params)`.

For retrieval within an existing library, use `zotero_search_items` with a
short query and a user-selected collection when appropriate. Use
`zotero_get_collection_items` with an explicit limit to browse that collection;
follow its pagination when further results are needed. This is library
retrieval, not discovery or downloading of papers from the web. Search results
and abstracts alone do not mean a paper has been read.

Confirm availability before interpreting an empty result. Some external tools
return connection failures as ordinary text rather than protocol errors.
An unavailable source is not an empty library. A collection limit or one page
of results also does not establish that the library has been searched fully.

## Capture a bounded reading

Read the selected item's metadata and locate its PDF attachment. Select PDF
page ranges appropriate to the question. Page numbers in this flow are
**one-based PDF page indices**, which may differ from printed page labels.
There is no required number of papers or pages to finish a research task.

The Python collection helper supports an external reader:

```python
from mining_research_kernel.zotero_reading import collect_reading

capture = collect_reading(
    reader,  # Host-owned callable returning the actual external tool response
    instance_id=opaque_instance_digest,
    library_id="users/0",
    item_key=selected_item_key,
    collection_key=selected_collection_key,
    pages=[{"attachment_key": selected_pdf_key, "start_page": 1, "end_page": 1}],
)
```

`instance_id` is a stable opaque identifier for the selected Zotero instance,
represented as 16–64 lowercase hexadecimal characters. Keep its Host mapping
outside the public repository. `users/0` is a local API library identifier,
not a globally unique account ID: combine it with the instance identifier.
For groups use the actual `groups/<id>` library. The helper checks returned
metadata identity and attachment parentage before reading requested pages.

Metadata-only reading uses `pages=[]`. A successful page observation retains
the attachment identity/version, requested page indices, a short excerpt,
and a SHA-256 of the complete decoded page-range text with surrounding
whitespace trimmed. **This digest is not
the original PDF's hash.** Unknown versions remain unknown; a reported zero
does not establish freshness or reliable incremental synchronization.

The capture keeps bounded excerpts and source locators rather than a full
paper or library dump. Source responses and OCR are reading aids. The original
paper remains authoritative. The helper's resource limits bound an individual
call; they do not decide the user's research scope.

The helper uses the already installed external reader. A capture saved by the
Host can also be imported later. Its `origin="external_mcp"` describes its
claimed source, not trusted attestation: importing caller-supplied JSON never
proves that a live source was checked. Synthetic captures must explicitly use
`origin="synthetic"` and a synthetic task context.

The JSON Schema checks field structure. `validate_capture` additionally checks
related page bounds, reading-state requirements, and normalized source fields;
use the runtime validator before import.

## Record an observation and optional interpretations

Save the validated capture as UTF-8 JSON in the user's project or private
working area. Keep library keys, excerpts, and real research outside this
public code repository. From the Kernel repository:

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-study'
python -B -X utf8 mining_kernel.py enable-research --project-root $projectRoot --project-id study-01
python -B -X utf8 mining_kernel.py validate-zotero-reading path/to/reading-capture.json
python -B -X utf8 mining_kernel.py zotero-record --project-root $projectRoot --task-id reading-01 --question "What does the selected material establish for this question?" --capture path/to/reading-capture.json
```

The last two commands read the capture file; **they do not contact Zotero**.
The record receipt reports `query_performed=false`, `source_revalidated=false`,
the capture timestamp, identities, page ranges, and saved record IDs.
Record creation time and source observation time are separate.

Optionally add `--findings-json @path/to/findings.json`:

```json
[
  {
    "statement": "An interpretation written after reading the selected pages.",
    "citation": {"attachment_key": "ATTACH01", "start_page": 1, "end_page": 1}
  }
]
```

Replace the example key and pages with the actual successful reading location.
Findings are interpretations, not user decisions or automatically verified
claims. The importer checks that cited pages are within recorded successful
reading coverage; it does not establish semantic support or scientific
validity. Metadata-only captures cannot supply PDF page findings.

A single existing ResearchStore transaction associates the question, proposed
claim, route, embedded capture Asset, Evidence, provisional Decision, and task
state. It creates no solver run or engineering Verification. Missing metadata,
failed pages, unexamined scope, and uncertain versions remain visible.
Metadata-only captures and captures without successfully read PDF pages retain
an `INSUFFICIENT` literature-reading judgment, and the
CLI exits 2 even though it retained the failed observation. A completed task
means the observation was saved, not that the research question was resolved.

For an offline software example, use the
[synthetic capture](../examples/zotero_reading/README.md) with
`--task-context synthetic`. It contains no real paper or library data.

## Recover and continue

```powershell
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task reading-01
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id reading-01 --section packet
```

Use the returned Asset ID with `show --section payload` for source capture
details, and the Decision ID with `show --section assessment` for the recorded
interpretations and gaps. These commands need neither Zotero nor the original
capture file. Reimporting the identical request is idempotent. Reusing the task
ID for changed material, question, or findings is rejected; use a new task ID
for a new observation.

A later `task-start` can explicitly cite the saved `asset_refs`, `evidence_refs`,
and Decision through `decision_refs`. Matching the embedded snapshot hash
establishes snapshot integrity only. Later tasks begin with that material
unread in the new task; the original PDF and Zotero state are not revalidated.

When the user chooses this task as the current project state, add a record
pointer to the existing project entry. The commands do not rewrite it or
choose a stopping point. The user continues to decide goals, finish criteria,
and follow-up work.
