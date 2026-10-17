# Compare selected literature for one question

Use this optional workflow when a question depends on differences between
studies: materials, loading conditions, methods, parameters, results or
applicability. The user chooses the question and intended delivery. The Agent
reads the selected material and explains the comparison; the Kernel preserves
its sources, page coverage, missing information and provisional status.

For a simple project handoff, ordinary Markdown is sufficient. This workflow
uses [optional research records](OPTIONAL_RESEARCH.md) when a comparison needs
durable, recoverable evidence.

For subsequent reading and judgment updates on the same question, use
[continuing research](CONTINUING_RESEARCH.md). It preserves the prior step and
can generate a readable report from the saved comparison.

## Select the reading scope

Read selected PDF pages with [Zotero reading](RESEARCH_SOURCES.md). Start with
at least two distinct paper identities, each with successful saved page
coverage. Repeated captures of the same paper do not count as another study.
Metadata or an abstract search result alone is not a page reading.

Choose pages that address the question. A cover page may contain no methods
or results; that is a reason to keep those cells unknown or propose further
reading within the user's scope. Paper identity is recorded by the selected
Zotero instance, library and item. Separate duplicate library items are not
automatically recognized as the same publication; inspect DOI/title identity
before interpreting them as independent studies.

Optionally select an existing [documentation observation](ITASCA_READING.md)
to clarify a software term or applicability condition. Documentation provides
its own coverage; it is not another experimental study.

## Start from the question

Use Asset IDs returned by source-reading commands. The IDs below are examples;
replace them with the actual selected records.

```powershell
$projectRoot = 'D:\replace-with-user-chosen\study'
python -B -X utf8 mining_kernel.py literature-start --project-root $projectRoot --task-id ae-comparison-01 --question "Under which reported conditions could these AE methods inform the proposed numerical study?" --asset-ref paper-a.asset.1 --asset-ref paper-b.asset.1 --dimension conditions --dimension methods --dimension applicability
```

If dimensions are omitted, the defaults are `materials`, `conditions`,
`methods`, `parameters`, `results` and `applicability`. Starting the task reads
saved observations, rather than reopening PDFs or launching a new study.
The response includes source overviews and `comparison_template`. Copy that
JSON object to an explicit UTF-8 file, such as `comparison.json`, and fill it
from the material actually read. Keep the exact question, selected sources
and requested dimensions.

For each source and dimension:

- Use `reported` for an interpretation with a concrete value and citations
  bound to that source. Paper citations identify the Evidence, PDF attachment
  and page range within successful saved reading coverage.
- Use `not_reported_in_read_scope` when the pages read do not establish that
  information. Keep its value null, give a short explanation and leave its
  citations empty. This does not assert that the whole paper omits it.

Describe differences with their relevant source references and explain what
would limit transfer to the proposed mining problem. Keep numerical values,
units, loading paths, geometry and software assumptions distinct. Similar
terminology does not establish equivalent experimental or numerical behavior.
Write a bounded summary, limitations and a next-step suggestion; do not turn
that suggestion into a user decision or automatically start it.

The returned template keeps `summary_cells` pointing to selected source and
dimension pairs. Each `differences` entry uses `dimension`, `explanation`,
`transferability` and `compared_cells`; the compared cells must belong to at
least two selected sources with reported information for that dimension.
When only one study provides that information in the pages read, explain the
uneven coverage in the summary and limitations rather than inventing a
two-study difference. Documentation citations use its Evidence ID and the
exact saved passage `locator`.

## Save and continue

```powershell
python -B -X utf8 mining_kernel.py literature-review --project-root $projectRoot --task-id ae-comparison-01 --operation-id ae-comparison-01.review-01 --comparison-file path/to/comparison.json
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task-id ae-comparison-01
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id <returned-decision-id> --section assessment
```

The saved Decision contains the comparison, bound source revisions, gaps and
next-step suggestion. Repeating the same operation and content returns the
same result; changing it under that operation ID is a conflict. Operation IDs
are unique within a project. If a source revision or payload changes after
the comparison starts, begin a new task using the intended source revision.

Program checks establish source association and captured page coverage. They
do not establish that a cited passage semantically supports the interpretation,
that two methods are comparable, or that a reported parameter fits a new model.
Judgments remain `PROVISIONAL_WITH_GAPS` or `INSUFFICIENT`; a comparison with no
reported cells remains insufficient. Source freshness, failed reads and
documentation coverage limits remain attached even when a comparison omits
them. No solver Run or engineering Verification is created.
