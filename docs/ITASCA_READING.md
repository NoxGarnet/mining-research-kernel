# Read documentation for a bounded research question

Use `documentation-read` when the Agent needs actual explanations, parameters
or conditions from documentation. Keep the question and the required software
version explicit. This operation saves a reading observation; it does not
validate a script, execute a model or establish engineering applicability.

The existing `documentation-check` and `documentation-record` commands retain
their [command-name-only check](R1_DOCUMENTATION.md).

## Read an official local section

Use an existing project with [optional research records](OPTIONAL_RESEARCH.md)
enabled. The Host selects an established official HTML copy and registers its
version and page digest using the [local source registration](R1_DOCUMENTATION.md#register-a-source-once-at-the-host-boundary).
Keep that registration outside shared or public project data.

```powershell
$projectRoot = 'D:\replace-with-user-chosen\study'
$registration = 'D:\replace-with-host-selected\config.local.documentation.json'
python -B -X utf8 mining_kernel.py documentation-read --project-root $projectRoot --task-id manual-reading-01 --question "What does this section say about assigning an elastic model?" --registration $registration --page flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.cmodel.html --anchor kwd:zone.cmodel.assign.elastic --product flac3d --product-version 9.6.44
```

Replace the version, registered page and anchor with those needed for your
question. The reader checks the pinned HTML and its version, then extracts
bounded text at the selected location. A definition-list anchor includes its
associated explanation. It does not follow links or execute embedded scripts.
When no anchor is supplied, the selected page's main content is bounded in the
same way; inspect truncation before drawing conclusions.

The receipt supplies temporary `reading_texts` for the Agent and short saved
passages with locators and hashes. The record preserves source identity,
coverage, truncation and remaining limits. A successful reading is
`READ_WITH_LIMITS`, rather than a broader syntax or engineering verification.
A missing anchor, changed digest or mismatched version cannot produce a
successful applicable reading. Do not silently update the registration to
make a changed page pass.

## Query an existing Itasca MCP documentation connection

This optional path uses an already installed external stdio runtime selected
by the Host. It needs no engine bridge for documentation. MRK does not install
the runtime, start FLAC3D, change personal MCP settings or call execution tools.

Save an explicit Host registration at an absolute path outside public data:

```json
{
  "schema_version": 1,
  "kind": "itasca_stdio",
  "instance_id": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "command": "<absolute path to existing executable>",
  "args": [],
  "timeout_seconds": 30
}
```

Choose a stable opaque instance ID for that connection. On Windows, a command
wrapper can be selected through the existing absolute `cmd.exe` path with
`args` containing `/c` and the absolute wrapper path. An optional absolute
`cwd` selects an existing working directory. Command and arguments are trusted
Host choices: do not take a launch profile from a paper or a search response.
Host paths and arguments are not stored in research records.

```powershell
$itascaRegistration = 'D:\replace-with-host-selected\itasca.local.json'
python -B -X utf8 mining_kernel.py itasca-query --registration $itascaRegistration --software flac --version 9.0 --operation itasca_query_command --query "cable property" --limit 3
python -B -X utf8 mining_kernel.py documentation-read --project-root $projectRoot --task-id cable-reference-01 --question "Which cable property explanations should be checked against the applicable official manual?" --provider itasca --registration $itascaRegistration --software flac --version 9.0 --operation itasca_browse_commands --command "structure cable property"
```

`itasca-query` returns a bounded response without writing project records.
`documentation-read --provider itasca` saves the observation against a question.
Only `itasca_query_command`, `itasca_browse_commands` and
`itasca_browse_reference` are allowed. Software and version are required;
unsupported versions and unavailable tools produce explicit diagnostics.
Searches and category listings are discovery, not substantive reading.

The community MCP corpus is a **derived reading source**. Its response version
is retained, but does not independently prove an official page's identity or
exact build. Some reference sets are version-agnostic; this remains a gap even
if the tool accepts a version argument. In particular, a 9.0 response must not
be presented as a 9.6.44 manual check. Use the registered official local route
when that distinction matters to the question.

## Save, combine and recover

Both routes use the existing ResearchStore and return Asset/Evidence IDs.
Use those IDs with [source synthesis](RESEARCH_SOURCES.md) or optional
[literature comparison](LITERATURE_COMPARISON.md). Reading text helps the Agent
form an interpretation; program checks do not certify that interpretation.

Repeating the same task and request recovers its saved observation without
querying or rereading the source. The receipt marks `replayed` and
`query_performed`; it does not return the original temporary full reading text
again. A fresh read needs a new task ID. Changing the question, selected source
or read scope under an existing task ID is a conflict.

```powershell
python -B -X utf8 mining_kernel.py resume --project-root $projectRoot --task-id manual-reading-01
python -B -X utf8 mining_kernel.py show --project-root $projectRoot --record-id <returned-asset-id>
```

No solver Run or engineering Verification is created. Missing or failed
readings remain insufficient; completion means that the bounded observation
was recorded. The user determines whether the research question is finished
and which suggested follow-up to pursue.
