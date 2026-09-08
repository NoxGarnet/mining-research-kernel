# v0.1.0 Completion Status

## Current candidate state — 2026-09-07

The current working tree is the code baseline
`72a2d6bcb80d6136c27d2aca61a0ce890f9ab9fd` plus uncommitted publication
material and reference-example edits. The code baseline is locally accepted at the
bounded scope recorded in [ACCEPTANCE_SUMMARY.md](ACCEPTANCE_SUMMARY.md): 200
tests run, 199 passed and 1 file-symlink test skipped; 10/10 applicable README
commands succeeded; 19 schema files parsed; and 2 representative
TaskPacket/inspect outputs passed runtime schema validation.

The runtime-only public examples use Python standard-library facilities. The
complete tests and Draft 2020-12 checks require `jsonschema==4.26.0`; Python
3.14.2 on Windows is the only exercised interpreter environment. No lower
Python support bound is claimed.

Current capability boundary:

- Real kernel mechanisms include ResearchStore, TaskState, routes, Run Ledger,
  Evidence/Verification, Research Map, Cognition views and completion checks.
- Synthetic behavior includes fixture projects, deterministic fake execution
  and synthetic static checking.
- User-provided resources include version-matched Itasca local documentation,
  source registration, sanitized Zotero snapshots and caller-injected
  read-only Zotero readers.
- Production FLAC3D `static_check`, real FLAC3D execution and a complete
  `itasca-mcp` integration remain unimplemented.

Remaining matters are separate: the file-symlink test lacks platform coverage;
the original R8 two-gate task remains incomplete; no scientific or engineering
validity is claimed; and the candidate has not been pushed or published.
Historical Private staging evidence applies to its own earlier commit and does
not represent remote acceptance of this baseline. This round did not rerun the
complete baseline suite after these documentation and example edits.

The technical acceptance result, the platform coverage gap and the unexecuted
publication decisions are intentionally reported as separate facts.

This file records local completion evidence for the revised v0.1.0 scope.
The 2026-09-05 revision supersedes the old Phase 1/2 acceptance interpretation.
Design decisions and implementation boundaries are in
[R0_IMPLEMENTATION_CONTRACT.md](R0_IMPLEMENTATION_CONTRACT.md).
Release remains blocked. No real engine/Zotero or release operation was run.

## Historical Phase 0 baseline (not the current working-tree state)

- Safety baseline: `main@a07cbf8d29e20d50b220113a7aeb0a7f5e281aa0`
- Baseline state: clean working tree, `HEAD` equals `origin/main`, no tags.
- Compatibility baseline: 48 existing unit tests, `compileall`, and
  `git diff --check` passed before Phase 1 changes.
- Historical release plan: retained as historical context; the Completion
  Plan is the active scope and release gate.
- Safety boundary: no visibility change, tag, Release, push, Private FLAC3D
  edit, Zotero write, or live Itasca operation is part of this work.

## Historical phase write sets (superseded by R0-R6)

| Phase | Primary write set | Exit gate |
|---|---|---|
| 0 | `docs/COMPLETION_STATUS.md` | Scope, baseline, compatibility, privacy and rollback are explicit. |
| 1 | `schemas/*` (new contracts), `adapters/flac3d.py`, `mining_kernel.py`, template files, Phase 1 tests | Blank/synthetic initialization and config-driven discovery pass; old 48 tests pass. |
| 2 | Documentation provider and FLAC3D workflow pack files/tests | Applicable official source is version-bound; unavailable documentation is `CANNOT_VERIFY`. |
| 3 | Task packet engine and reference-agent example/tests | A fresh host can obtain a bounded next action without chat history. |
| 4 | Research Map and route lifecycle files/tests | Parent/child routes, budgets, stops and evidence relationships are deterministic. |
| 5 | Cognition, admission policy, failure reload and review queue files/tests | Cognition rebuild is evidence-derived and agent self-promotion is rejected. |
| 6 | Zotero evidence bridge, fake executor and optional live-provider adapter/tests | Read-only Zotero and fake execution are connected; live capability remains disabled by default. |
| 7 | Fresh-user example, README and end-to-end tests | A fresh clone passes the synthetic workflow without private tools or data. |
| 8 | Audit evidence only | Full release audit passes; no Public/tag/Release action is automatic. |

## Rollback boundary

Preserve all pre-existing uncommitted Phase 1/2 files. R0 is limited to
`mining_research_kernel/core.py`, `tests/test_r0_record_validation.py`, this
status file and `docs/R0_IMPLEMENTATION_CONTRACT.md`. Reversing R0 must restore
only its changes against the pre-R0 working tree, not reset to a07cbf8 or
remove all untracked files. The historical commit does not contain the
pre-R0 package implementation.

## Historical pre-R0 status (acceptance claims superseded)

- Phase 0: PASS.
- Phase 1: PASS after independent Sol review.
- Phase 2: PASS after independent Sol review.
- Current evidence: 29 focused Phase 1/2, module-boundary and extension
  conformance tests; 77 full tests; `compileall`; `git diff --check`; exact
  plan initialization CLI; direct project-root discovery; and README source,
  validation and fail-closed smoke commands.
- Architecture evidence: generic core/registry/interfaces contain no concrete
  FLAC3D, Zotero, Itasca or future-provider dependency; production extension
  records use dot-namespaced IDs and the ten planned kinds; legacy IDs and
  capability restrictions remain isolated in the compatibility shim.
- Git boundary: local uncommitted changes only; no commit, push, visibility
  change, tag, or Release.

## Historical revised gate snapshot (prior acceptance records)

| Gate | Recorded status | Meaning |
|---|---|---|
| R0 | PASS (bounded scope) | Type-dispatch fix, contract decisions and independent local checks complete. |
| R1 | PASS (local command-name scope) | Registered local HTML reader and CLI verified; real filesystem-link escape covered on Windows. |
| R2 | PASS WITH NOTES (synthetic/local scope) | Task loop, TaskState persistence, Run recovery, synthetic provenance and map rebuild verified; live engine remains disabled. |
| R3 | PASS WITH NOTES (synthetic/local scope) | Bounded multi-route lifecycle. |
| R4 | PASS WITH NOTES (synthetic/local scope) | Mechanical evidence, bounded proposal admission, invalidation, local conflicts, trusted review boundary and failure reload. |
| R5 | PASS WITH NOTES (synthetic/local scope) | Fresh-user subprocess and second-domain shared-path acceptance. |
| R6 | 本机候选验收基本完成；R6 尚未闭合 | Four direct findings are remediated in the candidate branch; fresh-clone and Private staging readback are complete. The file-symlink test/validation scope remains open; same-filesystem malicious parent replacement is outside the v0.1.0 goal and is not an open release blocker. |

## Historical scope decision, 2026-09-06

The v0.1.0 trust boundary is a user-controlled, single-user local deployment
with a bounded API. External documents and Agent proposals remain untrusted
evidence, not commands or authority. Required controls still cover accidental
project overwrite and out-of-scope paths, legitimate explicit caller output
directories, atomic and recoverable persistence, evidence provenance, scoped
execution authorization, and cognition review; metadata alone is not proof and
Core Cognition cannot self-promote.

The product research loop does not include a malicious process that already
has arbitrary same-filesystem permission to edit files/configuration or race-
swap parent directories. Isolated hostile execution, multi-tenant services,
authentication services and privileged execution are also outside this scope.
The absence of a guarantee against that actor is not a v0.1.0 release defect
and does not claim a fix. This exclusion does not suppress ordinary CLI/API
boundary violations, untrusted-input behavior, accidental evidence corruption,
unintended writes, or credential/privacy leaks. Re-evaluate the boundary if
remote, multi-tenant or privileged execution is added.

At that historical point, the remaining R6 gate was the file-symlink
test/validation scope. The
latest historical run remains 172 tests run, 171 passed and 1 skipped; the
skipped file-symlink case is not automatically waived and does not support a
fully verified claim. Future support or testing of that case is an explicit
decision and does not require creating an OS sandbox. The next step is a small
research-workflow usability trial in a separate user task; publication remains
a separate decision.

The fixed `0dafaa4` candidate and `e7e1d0a` clean-clone/staging evidence remain
historical acceptance evidence. These documentation edits are local and
uncommitted; they were not pushed or tested remotely.

## R8 task completion operation, 2026-09-07

The candidate now exposes `task-complete` and `task_complete(...)`. The
operation accepts no caller-provided state; it requires an explicit completion
payload covering every route in the current Task Packet. It checks current
Route ownership and `completed` status, RunReference provenance and
`run_executes_route`, an accepted and valid Run Ledger, PASS/PASS_WITH_NOTES
Verification and `verification_checks_run`, and recorded output/Evidence
references. At least one Evidence reference per route must come from the
selected Run; source Evidence may also be included when it documents the
Route's target Claim. Extra current Route records for the Task cause a closed
request to be rejected, which is the conservative multi-route rule while the
packet has no required/optional route field.

Success appends one TaskState revision with an operation result and a
non-executable `next_action`; it preserves packet budgets, `runs_used`, Route,
RunReference, Run, Verification, Evidence, and Cognition records. Repeating an
operation ID with the same normalized references is idempotent; changing its
content is an operation conflict. The operation means that the declared
research scope is complete. It does not change Core Cognition or upgrade
command-name-only documentation into parameter, script, numerical, physical,
engineering, or real FLAC3D validation.

Focused acceptance covered 5 task-completion tests: valid persistence and
second-process recovery, missing/unlinked evidence and verification, an
unfinished required route, an additional unfinished route in the same Task
Packet, operation idempotence/conflict, and completion schema parsing. The
real R8 close was
performed in a new derived work directory using the existing Route, accepted
Run Ledger, RunReference, PASS_WITH_NOTES Verification, and recorded research
outputs; the old trial and close JSON remain byte-preserved.

The historical final acceptance counts are focused task-completion tests 5/5
and full regression 190 tests, 189 passed, 1 skipped, 0 failures/errors. The
single skip is the platform file symlink case. These are the historical R8
acceptance results for that dated record.

Old Phase 1 proves useful initialization and interface scaffolding only.
Old Phase 2 does not prove applicable official-document verification. Registry
call-shape tests are not end-to-end extension conformance. Future schemas
remain drafts until their runtime consumers exist; R4 CognitionProposal,
CognitionReview, Failure and Core Cognition view schemas now have runtime
consumers and bounded admission rules.

## R0 evidence, 2026-09-05

- Local pre-change HEAD and cached origin/main: a07cbf8; pre-existing dirty tree.
  No remote refresh was performed. Workspace doctor: no FAIL; unrelated GitHub
  authentication and tool-visibility warnings do not block this local work.
- Parent baseline: `python -B -m unittest discover -s tests -q` with
  PYTHONDONTWRITEBYTECODE=1: 77 tests passed before the R0 mutation.
- Execution subagent: gpt-5.6-luna, medium. Actual child turn_context metadata
  was inspected; the model was not inferred from its self-description.
- R0 decisions fix record ownership, derived views, three validation layers,
  generic role mapping, execution-attempt accounting, single-writer recovery
  and a concrete local official HTML reader scope for R1.
- Read-only source-format observation: installed Itasca HTML identifies the
  9.6 family and 9.6.44 documentation build, with a real command syntax anchor.
  This does not establish compatibility with a 9.0 project, an engine version,
  or a completed R1 provider. No source HTML was copied into this repository.
- Parent final verification: `python -B -m unittest discover -s tests -q` with
  PYTHONDONTWRITEBYTECODE=1: 85/85 passed (77 existing tests and eight new R0
  tests). The parent also independently exercised malformed explicit/declared
  type combinations, parsed the changed Python files with ast, checked local
  documentation links/whitespace, and ran `git diff --check`; all passed.
- Pre-R0 versus post-R0 file-digest comparison found exactly the four declared
  files changed/added, with no deletions and no changes to other pre-existing
  candidate files. Existing dirty-tree work was preserved. No commit or push.
- Acceptance is limited to R0. No fresh-clone release audit or new full security
  scan was performed in that stage; the subsequent R1 evidence is below.

## R1 evidence, 2026-09-05

Delivery: [local documentation guide](R1_DOCUMENTATION.md), explicit
`documentation-check` CLI, strict Host registration loader and an actual HTML
Syntax/signature reader. Coverage is `command_name_only`; parameters, parameter
combinations, full scripts and grammar remain explicitly uncovered. No Task
Engine syntax-modification authorization is implemented by this stage.

The provider reads the source bytes and verifies the registered digest and
actual document family/build. Legacy indexes and injected callbacks cannot
grant VERIFIED. Unknown trust classes, ambiguous version declarations, wrong
products/versions, malformed queries, missing locations and hash drift fail
closed. Synthetic input requires synthetic context and produces
SYNTHETIC_VERIFIED, never a production VERIFIED result. Capability output was
independently checked against the existing schema's required/allowed keys.

Execution models were checked in actual child turn_context metadata:
gpt-5.6-luna/high for the reader and gpt-5.6-luna/medium for the CLI. The parent
defined the boundary, reviewed both changes and performed final integration
acceptance. No model identity was inferred from a subagent's self-description.

Parent commands/results (repository root, PYTHONDONTWRITEBYTECODE=1):

- Initial integration: 103 run, 102 passed, one Windows symlink-permission skip.
  That gap was closed with a real directory-link escape test: native directory
  symlinks where supported, and a Windows directory-junction fallback. It
  verifies rejection before reading the escaped page and removes only the
  link itself after checking its target remains inside the temporary test root.
- Final `python -B -m unittest discover -s tests -q`: 103/103 passed, zero skips,
  failures or errors. Parent independently confirmed this Windows host actually
  exercised the directory-junction fallback. This does not claim native Windows
  symbolic-link creation was tested with elevated privileges.
- `python -B tmp/r1-real-doc-smoke/check_real_source.py`: eight actual-source CLI
  cases passed, including matching family/build, wrong family/build, unknown
  target, topic-only query, unsupported parameters and wrong anchor.
- `git diff --check`: passed. Changed Python AST, Markdown fences and real
  citation digest/anchor checks passed independently.

Real local source evidence (no HTML body in the repository):

- Relative page:
  `flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html`.
- Actual documentation family/build: 9.6 / 9.6.44; not an executable-version
  observation and not evidence for a 9.0 project.
- Page digest:
  `ef8b8ba024a73ca7e9e4acc40bee9617ba338e51d55b010a82e1c2153093b166`.
- Source bytes unchanged before/after checks. Host-local registration, runner
  and results are under ignored `tmp/r1-real-doc-smoke/`; the installed source
  stays outside the repository. Trust is explicit local-source registration,
  not cryptographic publisher authentication.

R1 write set: `providers/documentation.py`, `mining_kernel.py`,
`tests/test_phase2_documentation.py`, `tests/test_r1_documentation.py`,
`tests/test_r1_documentation_cli.py`, `README.md`, `docs/R1_DOCUMENTATION.md`
and this status file. Pre-R1 file digests confirmed no changes to other existing
candidate files and no deletions. Old metadata-VERIFIED test expectations were
replaced to match the corrected requirement; the original safety tests and R0
implementation were preserved.

## R2 evidence, 2026-09-05

Delivery: [R2 quick start](R2_QUICKSTART.md), public TaskEngine, project-aware
FLAC3D routing, disabled/fake execution providers, project-local authoritative
transactions, TaskState revisions, Run Ledger role/recovery updates, a
Zotero-backed synthetic evidence bridge, CLI commands and SDK-free reference
agent.

Parent acceptance results:

- `python -B -m unittest discover -s tests -q`: 133/133 passed, zero skips,
  failures or errors.
- `python -B -m unittest tests.test_r2_end_to_end -v`: 6/6 passed in separate
  CLI subprocesses. It covers task start/inspect, fake run, duplicate operation
  idempotence, operation conflict, map deletion/rebuild, Zotero snapshot plus
  local-source hashes, metadata-only rejection, missing item/source and
  production fake rejection.
- R2 focused suites together cover records, task engine, Run Ledger recovery
  and integration; their current total is 30 tests. The parent also reran the
  SDK-free reference agent in a fresh temporary project and confirmed
  `ready -> completed -> ResearchMap`, no temporary-project path leakage, AST
  parsing, Markdown fences and `git diff --check`.
- Run Ledger acceptance uses canonical `planning_agent`, `execution_agent` and
  `acceptance_agent` roles. Historical `sol` input remains a stage-scoped
  compatibility value and is never persisted as the new role.
- Project transactions are single-writer, atomic and operation-idempotent.
  Research Map excludes TaskState while retaining Asset, Evidence, Claim,
  Route, RunReference and Verification nodes. Evidence must have an exact
  Asset provenance edge. Deleting and rebuilding the view preserves content.
- Fake execution reserves its operation in a durable TaskState revision before
  dispatch. A competing or resumed call with that operation ID stops for
  reconciliation and does not dispatch a second time. RunReference manifest
  digests are validated as lowercase 64-character SHA-256 values.
- The combined local synthetic flow was independently exercised: Zotero
  snapshot item -> local source Asset -> document Evidence -> proposed Claim,
  then the same Task's route -> RunReference -> synthetic execution Evidence ->
  Verification. No Evidence was automatically linked as scientific support.

R2 limitations:

- Fake execution is deterministic fixture mechanics only and refuses production
  context or mutation. Its acceptance scope explicitly retains missing FLAC3D,
  numerical, physical and engineering validation risks.
- R2 transactions are file-native and local-process tested. They do not claim
  distributed locking, power-loss durability or protection from an actor with
  equal filesystem write permission.
- Literature snapshot/source inputs are required to be project-relative in the
  R2 bridge. The caller-selected request JSON itself may be outside the project,
  but it is read only and its path is not persisted as a project fact.
- Real Zotero, live itasca-mcp and full FLAC3D syntax/engine validation remain
  outside this stage. R4 Core Cognition remains open.

No installation, commit, push, fresh-clone release audit, new full security scan
or publication action was performed. Release remains blocked.

## R3 evidence, 2026-09-05

Delivery: `mining_research_kernel/routes.py`, the route lifecycle CLI, the
bounded `route_policy` configuration, the `RouteComparison` record and typed
question/Claim, parent/supersede/comparison relationships. The service uses
the existing ResearchStore writer, atomic transaction files and expected
revisions. A reservation is persisted before a route can be finished; a fresh
service instance can recover it, and replaying the same reservation operation
is idempotent. Task-bound routes consume the existing TaskState total budget.

The 10 R3 tests cover two routes for one question and Claim, project limits of
1–3, per-route and task-bound budget accounting, failed/`cannot_verify`/
rejected outcomes, write-set conflicts, reservation recovery, parent/child and
supersede relations, comparison archive determinism and the route CLI.
Comparison records retain status, `runs_used`, budget, outputs, write-set and
stop reason, and do not create a Claim or promote a scientific conclusion.

Parent acceptance results: `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest
discover -s tests -q` passed 143/143; the R2+R3 focused suites passed 16/16;
47 Python files compiled from source; `git diff --check` passed; and the
Route, RouteComparison and rebuilt ResearchMap outputs validated against their
JSON schemas. The actual Luna execution child was configured and observed as
`gpt-5.6-luna` with high reasoning effort; the parent performed the final
review and acceptance.

R3 remains synthetic/local scope. It does not execute FLAC3D, call Zotero or
an external provider, validate numerical or physical behavior, or provide
distributed locking against an actor with equal filesystem permissions.

## R4 evidence, 2026-09-06

Delivery: `mining_research_kernel/cognition.py`, runtime validation for
`CognitionProposal`, `CognitionReview` and complete `Failure` records, the
Core Cognition, review and derived-view schemas, and the cognition/failure CLI
commands.
Mechanical observations are restricted to fixed kinds and write an Asset,
Evidence and exact `evidence_derived_from_asset` relationship without entering
the human queue. Structured, low-impact, located evidence may be admitted as
`provisional`; free-text experience, domain rules, high-impact claims and
requested `accepted` status remain proposed or pending review.

The derived view recomputes dependency revision/hash invalidation, local
structured conflicts, deduplicated review keys and filtered failures from the
authoritative transactions. A trusted boundary must be injected by the Host
before any review can change a proposal to `accepted`; caller-supplied role,
model, reviewer text or requested status cannot grant that transition. Failure
records retain reproduction, versions, assets, scope, root-cause and
resolution fields, including `CANNOT_VERIFY` and blocked history. The
`failure_gate` preflight returns `blocked` for related unresolved failures and
`clear` for an unrelated scope.

Parent acceptance results: `python -B -m unittest tests.test_r4_cognition -v`
passed 15/15, and the full local suite passed 158/158. The R4 tests cover
mechanical evidence, provisional admission, self-promotion rejection, trusted
review, queue deduplication, dependency invalidation, scoped conflicts,
failure filtering, view deletion/rebuild, fresh-service recovery and
operation idempotence. No real FLAC3D, Zotero, network, installation,
commit, push, tag, Release or visibility operation was performed.

R4 remains synthetic/local scope. It provides a Host-injected review boundary
contract, not an authentication service, and cannot prevent an actor with
equal filesystem write permission from bypassing the public API.

## R5 evidence, 2026-09-06

Delivery: `workflows/synthetic.py`, the generic workflow-builder selection in
`mining_research_kernel/r2_workflow.py`, `init-synthetic-project`, the R5
acceptance suite and [R5 quick start](R5_QUICKSTART.md). The synthetic domain
has its own portable project envelope with `product: synthetic`; it supplies a
workflow pack and provider choice while using the existing TaskEngine,
TaskState, ResearchStore, Run Ledger, Verification and derived-view services.
No second engine or product-specific core import was added.

Parent acceptance results:

- `python -B -m unittest tests.test_r5_acceptance -v`: 5/5 passed in separate
  CLI subprocesses where the acceptance requires a process boundary.
- `PYTHONDONTWRITEBYTECODE=1 python -B -m unittest discover -s tests -q`: 163/163
  passed, including all R0–R4 regression tests.
- The fresh-user flow completed init, task start/inspect, fake execution, map
  rebuild, mechanical observation, provisional proposal, cognition rebuild and
  failure-gate inspection. Deleting both derived views and repeating the
  rebuild recovered them from authoritative records.
- The second-domain flow completed synthetic init, task start/inspect, fake
  execution, a new-process inspection and map rebuild. Its persisted records
  include the same TaskState, RunReference, Evidence and Verification types as
  the FLAC3D R2 path, with a synthetic workflow/method namespace.
- R5 also covers two routes with support/failure outcomes, budget stop,
  reservation recovery, provider replacement, invalid CLI input, provisional
  dependency staleness, review queue deduplication, failure scope filtering and
  legacy `discover` behavior. Temporary-project paths were not persisted.

R5 remains synthetic/local scope. R1 real official HTML evidence is reported
separately and is not part of this offline fixture result. No real FLAC3D,
Zotero, network, installation, `itasca-mcp`, commit, push, tag, Release or
visibility operation was performed. Numerical, physical, engineering and
fresh-clone R6 audit gates remain open.

## R6 evidence, 2026-09-06

The local release-qualification audit remains blocked. The standard Codex
Security scan completed with partial source coverage and four validated
low-severity findings:

- `stability.py:50-61`: `diagnose` can hash a caller-supplied path outside the
  workspace because it does not apply resolved containment before reading.
- `flac3d_project.py:143-171`: `init_project` resolves the target before its
  `is_symlink` check, so an existing directory link or junction can receive
  template writes.
- `zotero_export.py:87-90`, `relation_map.py:174-180` and
  `stability.py:162-166`: standalone artifact writers accept caller-selected
  destinations without the shared authorized-root and atomic-write policy.
- `mining_kernel.py:232-243`: `validate` returns an absolute checkout path in
  its JSON result.

The scan report is local host output, not a repository artifact. Its scope is
`github-candidate`, scan id `c9505f54-c3da-4391-86a2-68ca6c6de30f`, and its
coverage is explicitly `partial` because the bounded worker review and remote
private-staging readback were not available under this turn's constraints.
The scan found no reportable execution-provider, documentation-verification or
Zotero-write boundary issue; those controls remain subject to the documented
equal-filesystem-writer and caller-output limitations.

R6 release checks also found that `HEAD` and `origin/main` remain at the old
`a07cbf8` baseline while the R0-R5 implementation is untracked or modified in
the working tree. A fresh clone therefore cannot reproduce the accepted R0-R5
state. Reachable history contains two commits and no detected credential or
private-library material; unreachable local Git objects were not treated as
publishable history. Apache License 2.0 and the repository security policy are
present. No source remediation, real FLAC3D/Zotero/network operation,
installation, commit, push, tag, Release, visibility change or remote staging
readback was performed.

## R4/R5 correction and R6 remediation, 2026-09-06

The R4/R5 follow-up closed the two behavior gaps identified after the first
acceptance:

- Automatic provisional admission is now limited to `project_lesson`,
  `impact: low`, and explicit mechanical fact keys (`exists`, `sha256`,
  `return_code`, `passed` or `state`). Each referenced Evidence must still
  match its Asset's observation kind and canonical observation value. A
  mismatched observation such as `passed: false` with `fact_value: true`, an
  unsupported fact key, or `workflow_rule` remains a proposal or review item.
  Accepted cognition still requires the injected review boundary.
- `task-start` now loads the durable failure gate before committing the task
  packet. A new process started for a task or route with an open related
  failure receives a blocked packet; an unrelated task remains ready. The
  regression test records the failure in one CLI process and starts both tasks
  in later CLI processes.

The four original R6 direct paths were remediated locally:

- `stability.diagnose` rejects absolute, traversal and resolved link escapes;
  hash verification reads an opened descriptor and checks its actual Windows
  handle path when available.
- Project initialization checks the raw target and existing parent chain for
  symlink/junction reparse points before resolving it. Both CLI initializers
  now pass the unresolved user path into that boundary.
- Zotero, relation-map and stability artifact output share explicit caller
  destination semantics, reject linked output paths, and use same-directory
  temporary files with flush/fsync and atomic replacement. Explicit ordinary
  external output directories remain supported.
- `validate` reports fixture-relative identifiers rather than checkout paths.
- `TaskPacket` runtime fields are now represented by its schema, and the R2
  task-start route record now includes the required `route_id`.

Validation on 2026-09-06 is recorded by layer:

- Test runner: 172 run, 171 passed, 1 skipped. The skipped case is the file
  symlink output test; the three directory-link cases passed using the R1
  Windows junction fallback.
- README synthetic example: 1 command run, 1 passed; all three fixture
  results had zero errors.
- Schema documents: 16 JSON files parsed, 16 passed. This only checks that
  the schema documents are readable JSON.
- Representative serialized outputs: 10 generated or fixture outputs passed
  formal Draft 2020-12 validation with the host's `jsonschema` package. This
  separately covered project config, ResearchMap, CognitionProposal, Failure,
  CoreCognition, TaskPacket, Route, provider capability, Project and Zotero
  snapshot outputs; it is not a claim that every future extension output is
  formally checked.
- Python compilation passed and `git diff --check` passed with only existing
  line-ending warnings.

The independent remediation review recorded a concurrency limitation: directory
validation and final path replacement are rechecked and the temporary handle
is checked, but a hostile concurrent parent replacement cannot be fully
eliminated by the current cross-platform path API. The 2026-09-06 scope
decision supersedes its status as a v0.1.0 release qualification blocker; the
historical observation and its test evidence remain unchanged.

The README example `python -B mining_kernel.py --workspace
examples/synthetic_workspace validate` returned zero and reported no errors for
all three fixtures. Running `validate` against `--workspace .` is a separate
operation that treats the source checkout as a research workspace; missing
project materials in that mode are expected and do not invalidate the new-user
example.

The working tree is still dirty and contains the uncommitted R0-R5
implementation plus these local corrections. No source or test changes have
been committed; no real FLAC3D/Zotero/network operation, installation,
commit, push, tag, Release, visibility change or private-staging readback was
performed.

## Final R6 security recheck, 2026-09-06

The stable working-tree snapshot was independently rechecked with Codex
Security scan `b0a9fc64-ec22-4a73-b884-52451a977a78`. The completed report
covered 10 surfaces, found zero reportable findings, and emitted no snapshot
change warning. Coverage remains `partial` because the file-symlink runtime
test is unavailable on this host; fresh-clone and Private staging were
completed below.

The recheck confirms that the four original direct R6 paths are closed under
the current local trust boundary. A hostile concurrent replacement of an
output parent directory remains a documented residual limitation of the
cross-platform path API, but the 2026-09-06 scope decision excludes that
same-filesystem malicious-actor guarantee from v0.1.0 goals and blockers. The
repository has no source-backed remote service, cross-tenant ingress or
privilege boundary for that scenario.

Final local acceptance counts remain: 172 tests run, 171 passed, 1 skipped;
16 schema documents parsed; 10 representative generated or fixture outputs
passed formal Draft 2020-12 validation; the README synthetic validation
command returned zero with three fixture results free of errors. Scan token
usage was unavailable from the Codex rollout and is not estimated.

## Candidate and Private staging acceptance, 2026-09-06

The reviewed working tree was fixed locally as commit `0dafaa4` on branch
`candidate/v0.1.0`. The target repository visibility was read back as Private.
The staging branch `candidate/v0.1.0` was pushed and independently read back
through both `git ls-remote` and the GitHub branch API as commit
`0dafaa4313e1137ad64ded171e661ebe95db19ce`.

A clean clone from that Private staging branch had the same commit and a
clean working tree. In that clone, the full test runner reported 172 run, 171
passed and 1 skipped; the skipped case remained the file-symlink test. The
README commands for discover, inspect, discover-sources, inspect-source and
validate all returned successfully, with the synthetic validate command
reporting three fixtures without errors. The ten representative generated or
fixture outputs again passed formal Draft 2020-12 validation.

The only remaining R6 qualification item is the unavailable file-symlink
capability and its explicit testing/validation scope. Public visibility, tag
and Release decisions remain separate and were not performed.

## R7 focused correction, 2026-09-06

The real local-material trial exposed three usability defects. The candidate
now unions workflow-required and caller-requested documentation gates, so an
explicit documentation gate blocks a static-check task when no verified
version-bound result is supplied; ordinary tasks without that gate remain
unblocked. Production self-filled or synthetic documentation results do not
pass this gate.

`ResearchStore.register_local_material` and the matching CLI create stable
hashed Asset/Evidence records and their provenance edge for an explicitly
selected file. The material kind fixes the authority mapping, with
`derived_reading_note` always recorded as derived. Exact repeated requests are
idempotent and changed citation/Claim metadata is an explicit conflict.
Relative paths resolving outside the project are rejected; explicit external
absolute paths are stored as caller labels without copying source bytes.

The CLI `research-map-rebuild` now persists the configured map path by default;
the lower-level store call with `output=None` remains an in-memory pure view.

Targeted correction tests pass: documentation gate 5/5 and local material/Map
tests 4/4, alongside the directly affected R2 tests 25/25. The complete
standard-library regression reports 181 run, 180 passed and 1 skipped; the
skipped case remains the unavailable file-symlink runtime test. All 18 schema
documents parse, and 18/18 actual R7 task, map, cognition, route, failure,
proposal, Asset and Evidence outputs pass their applicable Draft 2020-12
schemas. Asset/Evidence also pass the ResearchStore runtime contract.

The final isolated trial is preserved in private acceptance evidence excluded
from distribution. It registered the same five authorized materials through
the new CLI, persisted the default Map
with 17 nodes and 21 edges, and recovered a blocked task, pending proposal and
failure gate in a second process. A preliminary trial with task budget 1
correctly blocked its second route; the final trial declared budget 2 so the
two bounded routes could be exercised without resetting budget. No FLAC3D,
real Zotero, installation, commit, push, tag, Release or visibility action is
part of R7.

## R8 Task lifecycle close audit, 2026-09-07

The R8 documentation trial's TaskPacket has top-level
`documentation_status=VERIFIED`, consistent with its applicable documentation
gate also being `VERIFIED`. The original source check remains preserved for
registered Itasca local FLAC3D 9.6.44 documentation: the source is the
registered `zone.list` page, and its coverage remains `command_name_only`.
The profile is the keyword hierarchy within that registered page; it is not a
separate page registration.

The actual read-only documentation Run is accepted and valid, its
RunReference is completed, and the documentation Verification is
`PASS_WITH_NOTES`. The covered scope is source registration, the command-name
gate, page reading and provenance. The R8 route is completed with one run;
the Map and Core views rebuild consistently. `command_name_only` does not
verify the complete profile parameter grammar, parameter combinations, full
scripts or engineering use.

The new R8 trial records Task `ready`, Route `completed`, Run `accepted`,
Verification `PASS_WITH_NOTES`, Cognition `pending_review`, and an independent
second-process recovery that reads the latest persisted state. The initial
Task snapshot and current state are unchanged: the existing Task API still
advertises a runnable `static_check`, while the completed documentation route
has no effective next run. `RouteLifecycle.finish` can close a Route, but no
public persisted production-documentation Task close operation exists;
therefore the lifecycle verdict is `CANNOT_CLOSE_WITH_EXISTING_TASK_API`.
This round records the minimal missing Task close operation and does not
promote Route completion to parent Task completion.

The previously reported full regression result of 185 passed and 1 skipped is
historical evidence only; this round did not rerun the full suite and does not
count 185/1 as a new test result. Close-only JSON, Task/Route/Run/Verification,
Map/Core and independent-recovery checks passed, with the old R8 trial files
left unchanged. Engineering, numerical, physical and real FLAC3D execution
remain outside this documentation result and unverified.

## R8 task-complete gate coverage correction, 2026-09-07

The completion boundary now derives the required gates from the current
persisted TaskPacket requirements and gate-status applicability. A completion
request must provide `verification_gate_coverage` for every current Route and
every applicable gate; its per-route `verification_ids` must exactly match the
coverage references. Each current Verification must still be PASS or
PASS_WITH_NOTES, belong to the project and task/route/run provenance, and be
linked to the selected RunReference. The operation result records each packet
gate alongside the referenced Verification ID, revision and record `gate_id`.
The packet gate, Verification record `gate_id` and redundant
`verification_gate_id` must be identical; `documentation_research` therefore
cannot qualify for the packet gate `documentation`.

Pending, failed or CANNOT_VERIFY packet snapshots are not permanent blockers:
a later current valid Verification can resolve the declared gate. A current
applicable gate without such coverage remains blocking. Engineering,
numerical, physical and real-FLAC3D gates marked NOT_APPLICABLE remain outside
the required set, and cannot be bypassed by relabeling an applicable gate.
Task idempotency/conflict behavior, multi-route closure rules, completed-task
non-executability, Run/Evidence/Route relations and Cognition persistence are
unchanged. Synthetic fixture tests document the contract separately from the
real R8 documentation records.

Targeted completion acceptance is 9/9 tests. The one complete regression after
the targeted pass is 194 tests run, 193 passed, 1 skipped and 0 failed; the
skip is the existing platform file-symlink case. The three affected schemas
(`task_completion`, `task_packet` and `verification`) each pass schema parse,
and separate runtime output validation passes for the new R8 operation.

The independent R8 derivative is preserved in private acceptance evidence
excluded from distribution. It starts from a ready TaskState revision 1 and
records the new operation
`task-complete-r8-gatefix-20260907-luna-20260907`, producing TaskState revision
2 with `next_action.executable=false`. Its documentation coverage points to
the existing `verification-r8-documentation-research` revision 1
`PASS_WITH_NOTES` record and preserves its `documentation_research` gate ID.
The independent recovery artifact confirms the completed Task, completed
Route, completed RunReference, unchanged Verification/Cognition boundaries
and seven total transactions. The old R8 trial and old task-close directory
were not written or used for idempotent completion.

## R8 strict Verification gate-id correction, 2026-09-07

Completion gate qualification is now strict: the packet gate key, the
current Verification record's `gate_id`, and the request's redundant
`verification_gate_id` must be identical. A Verification with
`gate_id=static_check` or `gate_id=documentation_research` is rejected when
the packet requires `documentation`, and the failed operation appends no
TaskState completion revision.

The new independent derivative is preserved in private acceptance evidence
excluded from distribution. It retains the existing
`verification-r8-documentation-research` record and
uses `ResearchStore.commit` to add the real
`verification-r8-documentation-gateid-strict` record with
`gate_id=documentation`, `PASS_WITH_NOTES`, scope/source references to the
actual `zone.list` page reading and source evidence, and a
`verification_checks_run` relation to the existing RunReference. The new
operation `task-complete-r8-gateid-strict-20260907-luna-20260907` appends
TaskState revision 2 from ready revision 1. Independent recovery confirms the
completed Task, non-executable next action, unchanged Route/RunReference and
Cognition, and the preserved old Verification.

Strict targeted acceptance is 10/10. The final complete regression after that
targeted pass is 195 tests run, 194 passed, 1 skipped and 0 failed. The skip
is the existing platform file-symlink case. Affected schema parse is 3/3 and
strict trial artifact JSON parse is 4/4; runtime output validation and
`git diff --check` pass. The old trial, old task-close and previous gatefix
derivative remain preserved and no commit, push, tag, Release, Public,
FLAC3D, Zotero, install or Host operation was performed.

## R8 original-scope supplemental acceptance, 2026-09-07

The original R8 Task Packet was independently derived with both applicable
gates, `documentation` and `static_check`, from ready TaskState revision 1.
It is distinct from the strict documentation-only derivative, whose
`static_check` gate was `NOT_APPLICABLE` and therefore cannot establish this
original scope.

The current FLAC3D workflow defines `static_check` as the
`mining_research_kernel.method.flac3d.static_check` method with a Task action
that expects a structured Run observation over the declared project entry and
baseline. The workflow API probe returned 0, but the method is absent from the
registered extension set; the CLI probe `python mining_kernel.py static_check
--help` returned 2 because no such command exists. The trace is in the new
derivative's `research/static_check/static_check_probe.json` and
`cli_probe.txt`; the gate remains `CANNOT_VERIFY`.

The supplemental records are
`verification-r8-original-scope-documentation` with `gate_id=documentation`
and status `PASS_WITH_NOTES`, limited to the registered FLAC3D 9.6.44
`zone.list` page, original query, source evidence and `command_name_only`, and
`verification-r8-original-scope-static-check` with `gate_id=static_check` and
status `CANNOT_VERIFY`. The earlier
`verification-r8-documentation-research` record and its history remain
unchanged.

The new completion operation
`task-complete-r8-original-scope-20260907-luna` returned 2 and was rejected
because the static gate was not a passing Verification. No completion
operation transaction or TaskState revision 2 was appended; independent
recovery reads TaskState revision 1, `ready`, with an executable static-check
next action. Engineering, numerical and physical validation, and real FLAC3D
execution are outside this documentation research scope and remain
unverified; they are not represented as required by this document gate. This
round did not rerun the full test suite and does not alter historical test
numbers.

## Historical v0.1.0 candidate boundary (72a2d6b code baseline)

The 72a2d6b code baseline kept the FLAC3D `static_check` gate applicable and
unfinished. The workflow declared its capability as `available=false`, with
the stable reason `static_check_unimplemented` and a recovery condition to
provide or register a real implementation. A new production FLAC3D
`static_check` task is therefore `blocked`, its `next_action.executable` is
`false`, and its `gate_statuses.static_check` remains `applicable=true` and
`status=PENDING`. No checker, parser, scheduler or framework was added.

The generic TaskEngine consumes workflow-declared capability status and does
not contain a FLAC3D product branch. The synthetic workflow declares its
fixture `static_check` capability available, so synthetic static tasks and
documentation-only tasks continue to work. A current `task-inspect` view can
project an older packet onto current capability status: it preserves the
historical `next_action` under `historical_next_action` and makes the current
action non-executable when the capability is now unavailable. Persisted old R8
records remain unchanged, including the original documentation and
`static_check` gates and their separate historical outcomes.

`task-complete` rejects an unavailable required capability before it can close
a task. The candidate does not claim a real FLAC3D static check, full script or
engineering validation. The version-bound documentation path remains limited
to `command_name_only`; synthetic evidence remains synthetic.
