# General reading observations and continued research

[简体中文](READING_OBSERVATIONS.zh-CN.md) | **English** · [Home](../README.en.md)

Give the Agent your question and material locations. The Agent chooses an existing
browser, PDF, image or OCR tool, reads the material, and supplies a bounded observation.
The Kernel validates its structure and source associations, preserves scope and history,
and supports comparison, continuation and reports under one research question.
It does not download or parse papers, perform OCR, authenticate sources, attest actual
reading, or verify scientific interpretations. Existing [Zotero](RESEARCH_SOURCES.md)
and [documentation](ITASCA_READING.md) adapters remain available.

## Observation contract

See the [schema](../schemas/reading_observation.schema.json) and the
[Chinese guide's complete JSON example](READING_OBSERVATIONS.zh-CN.md).

- `source`: stable non-path `source_id`, title, optional normalized DOI, HTTP(S) URL,
  source version and file SHA-256; `source_kind` is `local_pdf`, `web_article` or `local_text`.
- `reader`: tool name and method (`text`, `visual`, `ocr`, `mixed`); `captured_at` is the
  actual UTC observation time. Do not copy the example timestamp into a real observation.
- `passages`: unique readable locator labels with `read` or `unavailable` status, a bounded
  excerpt, optional reading-text digest, and explicit limitations. PDF locators include
  one-based `start_page`/`end_page`; section, figure, table and line locators use meaningful labels.
- Unknown source versions/digests and OCR or visual-reading limits remain explicit.
  An unavailable passage has no excerpt/digest and cannot support a citation.

`source.authority` is a caller declaration (`original_publication`, `derived`, `unknown`).
The stored observation itself always has derived authority. Original-file, reading-text
and embedded-record hashes describe different objects; none proves source authenticity,
actual reading or scientific validity. Host absolute file paths stay outside observations.
Use `origin=agent_supplied` for actual observations; authored examples require
`origin=synthetic` and synthetic task context. Production research rejects synthetic inputs.

## Record and review

Run from the repository, keeping the project and observations outside it:

```powershell
python -B -X utf8 mining_kernel.py enable-research --project-root path/to/study --project-id study
python -B -X utf8 mining_kernel.py validate-reading-observation path/to/observation.json
python -B -X utf8 mining_kernel.py reading-record --project-root path/to/study --observation-id paper-a-read-01 --observation path/to/observation.json
```

`reading-record` returns `asset_ref` and `evidence_ref`. It saves an immutable observation
pair atomically; it does not create a research judgment. Identical requests replay safely;
a changed source version, coverage or interpretation requires a new observation ID.
The receipt explicitly says that no source query or revalidation occurred during import.

```powershell
python -B -X utf8 mining_kernel.py research-begin --project-root path/to/study --task-id compare-01 --question "How are parameter sources and validation reported?" --asset-ref <paper-a-asset> --asset-ref <paper-b-asset> --dimension parameters --dimension validation
```

Fill the returned `comparison_template`, then save with `literature-review --comparison-file`.
General observations cite `{"evidence_id":"<bound Evidence>","locator":"<exact saved label>"}`.
Only a successfully read locator in that source can support a reported comparison cell.
Zotero attachment/page citations and documentation locators keep their existing forms.
Repeated DOI identity, including mixed Zotero/general captures, cannot count as two papers.
Without a DOI the Agent must check the caller-declared identity and distinctness.

For one source or a narrative review, use `research-begin --mode sources` followed by
`research-review`. Narrative citation validation is at the Evidence level; it does not
provide comparison cells' per-locator checks. Keep the actual scope explicit in the note.

## Continue and recover

After the Agent reads more material with its chosen tool, record a new observation,
select all intended source Assets, and continue:

```powershell
python -B -X utf8 mining_kernel.py research-continue --project-root path/to/study --from-task compare-01 --task-id compare-02 --asset-ref <paper-a-asset> --asset-ref <paper-b-new-asset> --reason "Read the validation section and retain the earlier judgment"
python -B -X utf8 mining_kernel.py research-progress --project-root path/to/study --task-id compare-02
python -B -X utf8 mining_kernel.py research-report --project-root path/to/study --task-id compare-02 --output reports/research.md
```

The same ResearchQuestion is retained, with exact previous TaskState/Decision revisions.
Recovery and reports use saved observations, not the original import JSON, paper or reader.
This does not establish current source freshness. Reports are reproducible derived views,
not full-text paper archives. Judgments remain provisional or insufficient; no solver Run
or engineering Verification is created.

Try the [offline synthetic example](../examples/reading_observations/README.md) without
papers, connections or third-party runtime dependencies.
