# Review a bounded FLAC3D script excerpt

[简体中文](FLAC3D_SCRIPT_REVIEW.zh-CN.md) | **English** · [Home](../README.en.md)

Keep selected script lines, the file hash, previously read official passages and authored findings in one recoverable task. Enable the existing optional research records only when this is useful; keep materials in their original locations.

Ask the Agent to review a named line range against a specified FLAC3D version. The user chooses the question, delivery scope and subsequent work. The Agent reads and interprets; the service validates citation and version bindings, rather than certifying the interpretation.

## Scope

This first entry targets complete, literal, single-line `zone cmodel assign` commands in one selected excerpt. It is not a complete parser. It cannot infer FISH/Python context, called files, continuation lines, expressions, range semantics or runtime state. Ambiguous cases remain gaps.

The current source-file limit is 2 MiB; select at most 200 lines and 32,000 characters. Larger inputs require a smaller selected input, without implying that the remaining source was reviewed.

Production review requires previously read **official local passages** matching the product and version. Command-name checks, discovery results and community MCP material do not satisfy this requirement. Follow [documentation reading](ITASCA_READING.md) for Host registration and bounded reading. Synthetic material is limited to explicitly synthetic tasks.

Each authored finding must cite a relevant captured command line and selected documentation Evidence. Those bindings do not prove that the passage supports the statement. Judgments remain provisional with gaps. No solver runs, source edits, Run or Verification records are created. The existing production `static_check` gate remains unimplemented.

## Agent procedure

Run from the repository, with user-selected material paths outside it. Skip enabling records if already enabled. Replace the version, page and anchor with the applicable registered source.

```powershell
$projectRoot = 'D:\replace-with-user-chosen\existing-study'
$registration = 'D:\replace-with-host-selected\documentation.local.json'
python -B -X utf8 mining_kernel.py enable-research --project-root $projectRoot --project-id study-01
python -B -X utf8 mining_kernel.py documentation-read --project-root $projectRoot --task-id assign-doc-01 --question "How does the official passage describe elastic model assignment?" --registration $registration --page flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.cmodel.html --anchor kwd:zone.cmodel.assign.elastic --product flac3d --product-version 9.6.44
```

Read the returned passage and coverage limits. Use its returned Asset ID:

```powershell
$docAsset = '<Asset ID returned by documentation-read>'
python -B -X utf8 mining_kernel.py script-review-start --project-root $projectRoot --task-id assign-review-01 --question "How does the selected assignment relate to the saved explanation?" --script work/model.dat --start-line 10 --end-line 20 --product-version 9.6.44 --documentation-asset-ref $docAsset
```

`--script` accepts a project-relative path or an explicitly selected external absolute path. External files stay in place; saved records contain a controlled label. Decoding defaults to strict `utf-8-sig`; choose a known encoding with `--encoding`. The complete file is hashed and only the selected lines are captured. Selected source text becomes part of project records, so choose shareable excerpts for public projects.

Inspect the returned lines, source bindings and review template. Write a JSON review file, replacing all example line numbers and Evidence IDs:

```json
{
  "summary": "A provisional comparison of the selected assignment and the saved elastic-model explanation.",
  "findings": [
    {
      "start_line": 12,
      "end_line": 12,
      "statement": "This line uses zone cmodel assign elastic; the read passage describes elastic constitutive-model assignment. Parameters and applicability remain unchecked.",
      "documentation_evidence_refs": ["<selected documentation Evidence ID>"]
    }
  ],
  "gaps": ["Material parameters, range and prior model state were not checked."],
  "next_action": "The user can decide whether to review parameters and range next."
}
```

Do not reuse the example interpretation without reading the actual sources.

```powershell
python -B -X utf8 mining_kernel.py script-review-record --project-root $projectRoot --task-id assign-review-01 --operation-id assign-note-01 --review-file 'D:\replace-with-user-chosen\assign-review.json'
python -B -X utf8 mining_kernel.py script-review-report --project-root $projectRoot --task-id assign-review-01 --output reports/assign-review-01.md
```

The report is a derived view. The existing report writer protects entries, registered materials and unrelated hand-written files. Update authoritative records rather than treating manual report edits as another current judgment.

## Resume later

Write the agreed scope, task ID, report path and pending decisions into the project `START.md`. Then:

```powershell
python -B -X utf8 mining_kernel.py script-review-progress --project-root $projectRoot --task-id assign-review-01
python -B -X utf8 mining_kernel.py script-review-progress --project-root $projectRoot --task-id assign-review-01 --script work/model.dat
python -B -X utf8 mining_kernel.py script-review-report --project-root $projectRoot --task-id assign-review-01
```

The first command recovers saved lines and judgments without reading original sources. The second explicitly compares the current file hash; an unchecked file must not be described as unchanged. Changed or missing files do not invalidate historical recovery, but findings remain bound to the original hash. A new file version or question needs a new task and selected evidence. Replaying an identical request recovers records without refreshing sources.

The [offline synthetic example](../examples/script_review/README.md) demonstrates recording and recovery without an official installation. Its authored sources are teaching material, not an actual model review.
