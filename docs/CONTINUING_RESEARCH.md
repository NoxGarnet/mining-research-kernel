# Continue one research question

Give the Agent the question and material locations, or point it to an existing
task. For example:

> 继续上次的 AE 方法比较，补读第二篇的方法部分。保留原判断，说明新增依据改变了什么，并生成一份能继续使用的 Markdown 报告。

The Agent follows the work below within the user's agreed scope. The user
does not need to prepare CLI commands or comparison JSON. Ordinary Markdown
projects can continue using their existing entry; enable persistent records
only when they help the task.

For an offline first try, use the [two-session synthetic example](../examples/continuing_research/README.md).
It supplies small authored paper passages and demonstrates the complete loop
without installing a source connection or preparing comparison JSON.

## Agent workflow

1. Recover the question, selected task and latest recorded judgment. Use the
   project entry and existing authorization; ask only about material missing
   decisions. The user determines goals, boundaries and completion.
2. Identify the specific evidence gap. Use existing [Zotero reading](RESEARCH_SOURCES.md)
   or [documentation reading](ITASCA_READING.md) for the needed pages or sections.
   Record failures and unknown versions. An inherited observation is not a
   fresh source read.
3. Continue from the named reviewed task. Select the full active set of source
   observations for this step, including newly read captures and still-relevant
   earlier observations. A replacement capture of the same paper replaces that
   paper's selected capture for this step; the prior task retains its original.
4. Read the returned sources, write the comparison or cited interpretation,
   and save it through the existing review command. Preserve unknowns within
   reading scope and scientific/engineering limits. Explain changes in the new
   summary using its actual evidence, rather than assuming more pages imply
   a stronger conclusion.
5. Generate a readable report from the saved records. Keep the project entry
   short, pointing to the current task and derived report. Next actions remain
   suggestions until selected or already authorized by the user.

## Agent invocation examples

These commands are tools for the Agent. Source-reading setup remains in the
linked guides; this workflow does not install runtimes, configure a model or
run an engine.

Start a comparison from Asset IDs returned by actual reading commands:

```powershell
$projectRoot = 'D:\replace-with-user-chosen\study'
python -B -X utf8 mining_kernel.py research-begin --project-root $projectRoot --task-id ae-step-01 --question "Which methods and conditions are reported in these selected readings?" --asset-ref paper-a.asset.1 --asset-ref paper-b.asset.1 --dimension conditions --dimension methods
```

`research-begin` defaults to a [literature comparison](LITERATURE_COMPARISON.md)
of at least two distinct papers. Select `--mode sources` for a cited Markdown
review of one or more selected paper or documentation observations. The response
contains source overviews and the appropriate review template. The Agent fills
it from its reading and saves it with `literature-review` or `research-review`.

After recording that first judgment, read the additional pages through
`zotero-read` under a new reading task ID. Then continue the comparison:

```powershell
python -B -X utf8 mining_kernel.py research-continue --project-root $projectRoot --from-task ae-step-01 --task-id ae-step-02 --asset-ref paper-a.asset.1 --asset-ref paper-b-more.asset.1 --reason "补读第二篇方法页，核查上轮缺失的方法和试验条件"
```

Replace the example IDs with actual selected records. If `--asset-ref` is
omitted, the prior selection is reused without rereading it. The question,
review mode, dimensions and context are inherited; a changed research question
belongs in a separate beginning. A task from the earlier `literature-start` or
`research-start` workflow can also be continued.

The subsequent task shares the existing ResearchQuestion, binds its previous
TaskState/Decision revisions and preserves prior records. Repeating the same
request recovers the task without resetting a completed review; changing its
inputs under the same task ID is a conflict. The review itself remains an
explicit operation with a project-unique operation ID.

## Recover progress and generate a report

When starting a new conversation, give the Agent the project path and named task.
It can begin with `project-context` and `resume`, then follow the returned argv
to expand the selected question's progress or render its report. A pending
continuation has no new current judgment: its inherited Decision remains clearly
labelled historical context, with the exact revision bound when it was created.
Later independent revisions of that Decision do not replace this context.
Source-reading observations and sibling research steps do not become conflicting
current judgments just because the new task cites their records.

The Agent should expand the inherited scope and gaps before proposing a next
action. A suggested reading is not an agreed task, and a completed source review
does not establish that the overall research project is finished.

```powershell
python -B -X utf8 mining_kernel.py research-progress --project-root $projectRoot --task-id ae-step-02
python -B -X utf8 mining_kernel.py research-report --project-root $projectRoot --task-id ae-step-02
python -B -X utf8 mining_kernel.py research-report --project-root $projectRoot --task-id ae-step-02 --output results/ae-research.md
```

Progress and report rendering read saved records, without contacting sources
or creating transactions. The named task selects its own history; a sibling
continuation is not silently selected as the latest conclusion. A pending step
is shown as pending with its earlier recorded judgment distinguished.

The Markdown report presents the question, scoped judgment, comparison,
source citations and reading coverage, remaining gaps, history and changes,
and the user's next decision. Added or removed source IDs are mechanical
observations; the Agent's explanation of their meaning remains provisional.
Reports retain distinctions between official local documentation, community
MCP corpus material and the paper pages actually read.

Without `--output`, Markdown goes to stdout. An explicit output must be a
separate Markdown file inside the project. The writer preserves existing
project entries, registered materials and files it did not generate. Repeating
an export to this task's own generated file regenerates that derived view.
Use the authoritative records for later updates rather than editing the report
as a second current judgment. No solver Run or engineering Verification is
created by this workflow.
