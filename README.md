# Mining Research Kernel

A small, filesystem-native kernel for Agent-assisted mining research: it
organizes research questions, routes, evidence, records, recovery and
auditable run ledgers. The runtime and offline public examples use only the
Python standard library. The complete test suite additionally needs the
development dependency listed in `requirements-test.txt`.

## Why this exists

Research automation needs a boundary between authoritative material, derived
artifacts, and claims about verification. This project makes that boundary
explicit. It discovers compatible workspaces and reports evidence; it does not
silently rewrite research files or turn metadata into experimental conclusions.

This is an early foundation for different Agents to call during mining
research. It keeps the research question, routes, evidence, failures and
recoverable records outside the chat window. FLAC3D is the first domain entry:
the kernel can route a project to version-matched documentation and record what
is known, missing or blocked. It is a research record and recovery kernel, not
an autonomous research system or a substitute for FLAC3D, Zotero or an
engineering reviewer.

## Start here

For a first run, use the [offline synthetic workflow](docs/R5_QUICKSTART.md).
It needs an empty user directory and shows the complete boundary: submit a
question and Claim, perform one bounded fixture action, inspect the final
TaskState from a separate process, and rebuild the Research Map. The fixture
execution is synthetic; the records, provenance and recovery are real kernel
operations.

Then choose the task you actually need:

- [Check an FLAC3D command name against applicable official documentation](docs/R1_DOCUMENTATION.md).
- [Record a task, evidence and bounded run](docs/R2_QUICKSTART.md).
- [Compare limited routes and preserve failures](docs/R3_QUICKSTART.md).
- [Review Cognition proposals and recover related failures](docs/R4_QUICKSTART.md).
- [Inspect the public acceptance boundary](docs/ACCEPTANCE_SUMMARY.md).

The R0–R8 labels are historical implementation and acceptance stages. They are
kept in [completion status](docs/COMPLETION_STATUS.md), rather than serving as
the user's task navigation.

## Repository layout

Start with the offline guide above and [mining_kernel.py](mining_kernel.py),
the CLI entry point. You do not need to read every directory to use the kernel.

| Path | Purpose |
|---|---|
| [docs/](docs/) | Usage guides, contracts, limitations and acceptance summaries. |
| [examples/](examples/) | Runnable examples and synthetic workspaces for learning the API. |
| [mining_research_kernel/](mining_research_kernel/) | Task, route, research record and Cognition services. |
| [workflows/](workflows/) | Domain-specific task routes and capability declarations. |
| [adapters/](adapters/) | Project and source discovery/inspection integrations. |
| [providers/](providers/) | Documentation and execution provider implementations, including disabled and synthetic execution. |
| [schemas/](schemas/) | JSON contracts for requests, records and derived views. |
| [tests/](tests/) | Automated checks for kernel behavior; mainly for contributors. |
| [fixtures/](fixtures/) | Fixed synthetic sample data used by tests; these are not private research files. |

Other top-level Python files provide CLI support, project setup, extension
registration, Run Ledger and Zotero snapshot utilities. The repository includes
development and test material as well as runtime code; running a normal research
task does not require running the test suite. Keep your own research inputs and
generated records in a separate project directory.

## Agent and Kernel roles

The Agent reads the question and available material, explains alternatives,
selects a bounded action and presents an interpretation. The Kernel validates
the request, records the Task/Route/Claim/Evidence/Run/Verification chain,
enforces applicable gates and budgets, preserves failures and exposes state
for a later process. Agents call it through the CLI or public Python API;
models, Host applications and user-provided resources remain outside the
repository.

A completed task or Run means that the declared workflow scope completed. It
does not establish that a hypothesis is true or that an engineering design is
fit for use. Model and session identifiers support provenance and comparison;
they do not create authority, and changing models or sessions is not by itself
an independent review.

## Current capabilities

- Portable blank FLAC3D project initialization and configuration-driven discovery.
- Two read-only project adapters for a compatible mining-research workspace.
- An explicit local HTML documentation check with source/version binding and
  command-name-only coverage; see the [documentation guide](docs/R1_DOCUMENTATION.md).
- The FLAC3D `static_check` gate is declared and enforced, but its real
  implementation is not included: a production `static_check` task is blocked
  with `static_check_unimplemented`. The synthetic fixture path remains usable.
- Task packets, persisted TaskState, bounded synthetic fake execution,
  RunReference/Verification records, Zotero-backed synthetic evidence and
  deterministic Research Map rebuild; see the [task and evidence guide](docs/R2_QUICKSTART.md).
- Bounded multi-route exploration with per-route budgets, durable
  reservations, write-set conflict blocking, parent/supersede relations and
  deterministic comparison archives; see the [route guide](docs/R3_QUICKSTART.md).
- File-native Core Cognition with mechanical evidence, bounded provisional
  admission, dependency invalidation, scoped structured conflicts, a deduplicated
  review queue and filtered failure recovery; see the [Cognition guide](docs/R4_QUICKSTART.md).
- Fresh-user subprocess acceptance and a second-domain synthetic workflow
  using the same TaskEngine, ResearchStore, Run Ledger, Verification and view
  rebuild path; see the [fresh-user guide](docs/R5_QUICKSTART.md).
- A persisted `task-complete` operation for closing a declared research scope
  after current Route, RunReference/Run, Verification, output, and Evidence
  records pass their association checks.
- A static `kind=source` Zotero adapter with only `discover`, `inspect`, and
  `read_only` capabilities.
- Sanitized Zotero snapshot validation and collection/item/attachment
  relation summaries.
- Optional normalized DOI matching before title/author fallback in
  `relation_map.py`.
- A filesystem-native five-stage Run Ledger with deterministic validation and
  stability diagnostics.
- A bounded local-material registration entry point that creates hashed
  Asset/Evidence records without copying source bytes; primary/original,
  project_record and derived_reading_note are kept distinct.
- A fully synthetic workspace example that runs without third-party packages;
  the complete test suite and schema checks require `jsonschema`.

The expanded v0.1.0 route and cognition loop is implemented through R5 in the
current working tree. See [completion status](docs/COMPLETION_STATUS.md) for
accepted stages and limits.
The kernel mechanisms listed above are real filesystem and record operations;
they are not fake results. Synthetic execution and static checking are fixture
implementations for demonstration and do not establish FLAC3D behavior. A
production user must provide an applicable Itasca local documentation source
registration. The implemented documentation check is version-bound and
limited to `command_name_only`; it does not establish parameters, scripts,
numerical validity or engineering suitability. Production FLAC3D `static_check`
and live Itasca execution remain unimplemented.

The external `itasca-mcp` integration is optional caller/provider territory;
this repository does not bundle it or provide a complete switch-on path. Any
future integration needs its own registration, authorization and engineering
verification.

## Capability classification

| Classification | Included behavior |
|---|---|
| Real kernel mechanisms | ResearchStore, TaskState, routes, Run Ledger, Evidence/Verification, Research Map, Cognition views and completion checks. |
| Synthetic | Fixture projects, deterministic fake execution and synthetic static checking. |
| User-provided resources | Version-matched Itasca local documentation and registration; sanitized Zotero snapshots or a caller-injected read-only Zotero reader. |
| Unimplemented | Production FLAC3D `static_check`, real FLAC3D execution and complete `itasca-mcp` integration. |

The [public acceptance summary](docs/ACCEPTANCE_SUMMARY.md) records the
versioned code baseline and separates these categories from validation claims.

## Cognition and research authority

Core Cognition is a rebuildable view over persisted observations, proposals,
failures and relations. A narrow allowlist of located mechanical facts may be
admitted as `provisional`; an Agent's requested status, role label or free-text
explanation cannot promote it. Other interpretations remain proposals until a
trusted Host review supplies the required evidence, scope and decision. The
CLI does not provide a complete promotion workflow, and the system does not
promise autonomous understanding or self-evolution. Failed, contested, stale
and missing-evidence states remain valuable records and can block only the
related work.

## Environment and dependencies

Python 3.14.2 on Windows is the only interpreter environment exercised for
this candidate. No lower or upper Python support bound is claimed here; other
versions require separate verification.

The runtime-only path does not import the test schema validator and can be
checked with an isolated interpreter:

```powershell
python -S -B mining_kernel.py --workspace examples/synthetic_workspace discover
python -S -B mining_kernel.py --workspace examples/synthetic_workspace validate
```

The complete tests include direct `jsonschema` imports for Draft 2020-12
validation. Prepare that dependency with the interpreter you will use:

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

This repository does not silently skip schema tests when `jsonschema` is
missing. Schema-file parsing, runtime output validation and scientific or
engineering validity are separate claims. This round did not install the
dependency.

## Quick start

From this repository root:

```powershell
python mining_kernel.py --workspace examples/synthetic_workspace discover
python mining_kernel.py --workspace examples/synthetic_workspace inspect flac3d_coal_roadway
python mining_kernel.py --workspace examples/synthetic_workspace discover-sources
python mining_kernel.py --workspace examples/synthetic_workspace inspect-source zotero_mcp_readonly --operation zotero_get_collections
python mining_kernel.py --workspace examples/synthetic_workspace validate
```

The last source inspection intentionally reports `CANNOT_VERIFY` because no
external Zotero reader is supplied by the example. A compatible application
may inject a reader for one allowed operation.

Publishing decisions are maintained separately in [release notes](docs/RELEASE_NOTES_DRAFT.md)
and are not implied by a successful local example.

## Developer validation

After preparing `requirements-test.txt`, run the complete test suite from the
repository root:

```powershell
python -m unittest discover -s tests -v
```

This is a development check with a third-party schema validator. It is kept
separate from the standard-library runtime examples above.

For an empty user-owned project directory:

```powershell
python mining_kernel.py init-flac3d-project path/to/new-project --project-id demo_project
python mining_kernel.py --workspace path/to/new-project discover
python mining_kernel.py documentation-check --help
```

The initializer refuses non-empty directories. Configure the project's actual
version and inputs before use; the empty baseline is not a ready model. The
documentation command requires a separate, explicitly selected Host source
registration described in the guide. It never treats a metadata index or
injected callback as sufficient official evidence.

For the complete synthetic task, evidence and rebuild loop, follow the
[R5 quick start](docs/R5_QUICKSTART.md). A second domain can use the shared
kernel through a separate portable fixture project:

```powershell
python mining_kernel.py init-synthetic-project path/to/synthetic-project --project-id synthetic_demo
```

Synthetic execution and synthetic static checking are deterministic fixture
implementations. They do not run FLAC3D or validate numerical or engineering
behavior. They also do not bundle or activate `itasca-mcp`. Production FLAC3D `static_check` remains an
applicable pending gate and is blocked until a real implementation is provided
or registered.

To persist completion for an existing task, provide every route in its packet
and the current records that prove each route is done. This is an independent
operation, not an automatic final step of the synthetic fixture example; the
IDs below must come from existing records inspected in that project and must
not be invented:

```powershell
python mining_kernel.py task-complete --project-root path/to/project task-id `
  --operation-id complete-1 --completion-json '@completion.json'
```

The completion JSON must contain `route_ids`, `run_reference_ids`,
`verification_ids`, `verification_gate_coverage`, `evidence_refs`, and
`output_refs`, keyed by route where appropriate. `verification_gate_coverage`
must list every currently applicable TaskPacket gate for every route and map
each gate to the Verification record IDs that cover it. The `verification_ids`
list for a route must be exactly the union of those coverage lists. The
coverage entry's `verification_gate_id` is a redundant copy of the current
Verification `gate_id`; both must equal the packet gate key.
operation checks the current Route/RunReference/Run, Verification,
ResearchStore relationships, and Run Ledger before appending a TaskState
revision. A later current PASS/PASS_WITH_NOTES Verification may resolve an
earlier pending or failed gate when its record and relation prove the declared
coverage. It rejects incomplete or unrelated evidence and never changes
cognition or upgrades command-name-only, numerical, physical, or engineering
verification.

For snapshot-only workflows:

```powershell
python mining_kernel.py validate-zotero-snapshot path/to/snapshot.json
python mining_kernel.py inspect-zotero-snapshot path/to/snapshot.json
```

For an explicitly selected local file, register only the material you are
authorized to use:

```powershell
python mining_kernel.py register-local-material --project-root path/to/project path/to/decision.md --material-kind project_record --source-documents-claim claim-id
python mining_kernel.py register-local-material --project-root path/to/project path/to/reading-card.md --material-kind derived_reading_note
```

The command reads the file to calculate its SHA-256 and writes only Asset,
Evidence and provenance records; it never copies or edits the source. The
material kind fixes its authority mapping: a derived reading note remains
`authority=derived` even when a caller supplies a stronger label. A relative
path must stay inside the project; an external file requires an explicit
absolute caller path and is persisted as a caller label rather than an
absolute path. This records provenance, not scientific, numerical or
engineering validity. Repeating the exact request is idempotent; changing its
citation or claim metadata is an explicit operation conflict.

## Workspace contract

The `--workspace` argument points to a user-owned compatible workspace. The
current project adapters expect relative paths under that root, including a
small `Workspace_Index/project_index.yaml` navigation file and the project
paths represented by the adapters. The repository ships only a synthetic
version of that layout; it does not ship a private workspace or research
documents.

## Zotero read-only boundary

The Zotero integration is deliberately a source read path, not a write
provider. The adapter contains no CREATE, UPDATE, DELETE, or MERGE operation
and holds no MCP credentials. A sanitized snapshot is a local input artifact;
a real-time reader is a separate caller-injected capability. Missing or failed
readers degrade to explicit diagnostics.

The five allowed operations are:

```text
zotero_get_collections
zotero_get_collection_items
zotero_get_item_metadata
zotero_get_item_children
zotero_get_item_fulltext
```

Original PDFs and other primary sources remain authoritative. Zotero metadata,
snapshots, OCR, Markdown, and MCP responses are rebuildable relation or
reading layers and must not be treated as experimental validation by
themselves.

Snapshot `doi` is optional. Exported DOI values are normalized to a lowercase
bare DOI, and relation mapping uses DOI when available before falling back to
title/author matching. DOI is metadata evidence; it does not prove source
identity, page-level support, or scientific validity.

## Safety and limitations

- No Zotero credentials, library database, full-text body, private item keys,
  or absolute attachment paths are included in this repository.
- The public snapshot and workspace are synthetic and are not a full-library
  example.
- The Zotero adapter is not a gateway, background service, downloader, or
  full-text index.
- FLAC3D/Itasca software and other proprietary products are not distributed or
  licensed by this repository.
- Schema and API contracts are version 1 and may change in a future release.

Future work such as a separately authorized Zotero Write Provider, automatic
discovery/download, OpenAlex/OAResolver, Docling, PaperQA2, or serviceization
is outside this release and requires a new scope and acceptance record.

## License

Mining Research Kernel is released under the Apache License 2.0. The license
applies only to code and documentation this repository is authorized to
publish. Zotero, FLAC3D/Itasca, and other third-party products retain their
own licenses; none are bundled here.
