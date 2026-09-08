# R0 implementation contract

Date: 2026-09-05. Design decisions for R1-R4, not implemented capability claims.
Scope: the revised v0.1.0 Completion Plan; local implementation only. No live
engine, real Zotero, installation, Git mutation or release action is authorized
by this document. R0 changes only the legacy record-type admission boundary,
its regression tests, this contract and the completion status.

## 1. Authority and record ownership

- Project configuration owns the selected project scope and declared inputs.
- Source files and run artifacts retain their original bytes. Evidence records
  identify a particular source revision and locator; a file's existence or hash
  never proves a scientific claim.
- A project-local `research/records/` directory will own immutable committed
  research transactions. Each transaction is one JSON document containing a
  sequence number, operation ID, producer, records and relationship changes.
  This is a bounded file store, not a general event framework.
- Questions, hypotheses, claims, routes, evidence, failures, decisions and
  review results have stable IDs and revisions. Updates append a new revision;
  relationships identify endpoint IDs/revisions and the evidence for the edge.
- Research Map and Core Cognition are derived outputs, never the sole home of
  a question, claim or support/contradiction edge. Deleting both must not erase
  research history. Reconstruction consumes committed records, referenced
  immutable artifacts, a policy version and an explicit evaluation time when
  time-based expiry is used.
- Existing Run Bundles remain the authority for their run contents. Research
  records reference a committed run revision/artifact digest instead of copying
  its body. A reconciliation step resumes an incomplete projection from that
  reference; a map file does not override a Run Bundle.

## 2. Validation and migration

Three separate results are required at each new write boundary:

1. Shape: known type/version, required fields and correctly typed values.
2. References: existing compatible project, scope and revision endpoints.
3. Policy: legal transition, sufficient evidence, budget and authorization.

R0 only fixes the legacy `validate_record` dispatcher. Its supported types
remain Project, Asset, Tool, Run and Verification. Other types, including a
future CognitionProposal, must report unsupported type instead of returning
an empty error list. A known explicit kind may still validate a legacy record
with no type; a conflicting declared type must fail. Malformed type/kind values
must return diagnostics, not an unhashable-value exception.

R1/R2 add dedicated validators as consumers are implemented. Merely adding a
schema must not advertise runtime support. Existing schemas with free-text
conditions or incomplete state enums are drafts until those boundaries exist.
No schema framework or blanket migration is introduced in R0.

New roles are planning_agent, execution_agent and acceptance_agent. The legacy
adapter maps sol by stage (planning for exploration/plan, acceptance for
acceptance). Actual model identity is separate. Model/role strings are audit
metadata, not authentication or proof of independent review.

## 3. Task and route semantics

A new Task Packet will always include state and next_action. Ready packets
contain action ID, input refs, expected outputs and typed preconditions.
Blocked/completed packets contain no executable action and include reason
and, for blocked tasks, resume conditions. A human-readable explanation is
additional context, not the machine gate.

Task states: proposed -> ready -> running -> completed; blocked and failed
preserve the reason and history. Resume is a validated transition with a new
attempt, not an overwrite. Route disposition is separate from execution result:
an executed route can still be rejected or have an unresolved claim.

Each Task has an approved max_runs budget. Each execution attempt reserves one
unit before any static/fake/live executor dispatch. A failed dispatch, timeout,
unknown execution outcome or retry consumes that reservation. Pure record
reads, documentation lookup and a preflight block before dispatch do not
consume an execution unit. Reference-agent action iteration is separately
bounded, so repeated document lookup cannot create an infinite loop.

Child and reopened routes charge the same Task total and cannot reset it.
Route max_runs also applies; satisfying only one of the Task/Route limits is
insufficient. One active route can run serially with another; the default
maximum of three active routes is a policy ceiling that a project can narrow.
Overlapping write sets serialize or block. No concurrent execution is required.

Initial machine predicates are limited to: evidence/reference available,
dependency revision matches, documentation coverage valid, applicable gate
passed, authorization scope covers action, and execution budget available.
Unknown predicates fail closed. Documentation-required actions stop on missing
or stale coverage; independent non-syntax work is not blocked by that failure.

## 4. Single writer and interrupted operations (R2 implementation)

- Acquire a project lock with exclusive creation before a mutation. Store an
  owner/operation identifier. Never automatically steal an apparently stale
  lock based on age alone; recovery must establish the writer has ended.
- Prepare one transaction in a temporary file, flush it, then atomically
  rename it to the committed record name on the same filesystem. Views update
  afterwards and may be rebuilt. Recovery ignores uncommitted temporary files
  and rejects duplicate sequence numbers or conflicting operation IDs.
- Persist attempt/reservation intent before calling an executor; persist its
  outcome afterwards. Repeating a completed operation ID returns its recorded
  result without another dispatch. A crash after dispatch but before an outcome
  yields an unknown outcome that requires reconciliation; do not auto-retry a
  possible side effect. A deliberate retry gets a new attempt and budget unit.
- The existing multi-file Ledger needs recoverable stage/manifest updates
  under the same single-writer discipline. Single-file atomic replace alone
  is not evidence of whole-operation atomicity. Test interruption between the
  stage update and manifest update, then reopen in a separate process.
- Claims of durability are bounded to the tested local filesystem process-
  interruption behavior; do not claim distributed or power-loss transactions.

## 5. Selected real documentation path (R1)

Implement an explicitly registered local Itasca HTML documentation root first.
No installation scan is required for production use. Use Python standard-library
HTML parsing; do not execute page JavaScript or fetch linked resources.

Read-only R0 observation found installed HTML with a document title identifying
Itasca Software 9.6 and an embedded documentation build of 9.6.44. This is
document metadata, not a runtime engine-version probe. The selected relative
smoke page is:

`flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html`

The page has an embedded DOCUMENTATION_OPTIONS version. Do not require a
separate documentation_options.js: the observed install references such a file
but does not contain it. The real source stays outside the repository; retain
only its metadata and digest in host-local smoke evidence, not its HTML body.

Trust registration is a host/user-controlled input separate from an Agent's
query payload. It binds source ID, a read-only root, provenance classification
and expected documentation family/build. A logo, self-reported source label,
or injected callback cannot register itself as official. This is a declared
local trust boundary, not cryptographic proof of publisher identity.

Version rules:

- Read family/build from the actual document and validate against registration.
- Require a non-unknown target product/version. A full build target must match
  the build; a declared family target must exactly match the document family.
- Do not infer that 9.6/9.6.44 applies to 9.0, or that a document build reports
  the installed executable version. Do not infer cross-family compatibility.
- Bind product scope to the registered documentation subtree and read context;
  a shared manual page alone cannot establish every product's applicability.

For the first bounded syntax check, a query identifies a documentation page,
an exact command syntax unit and, when needed, its anchor. An index may locate
the page but cannot supply verification. Read the HTML body, extract the
syntax section, bind coverage to its exact text/locator and return uncovered
parts explicitly. Do not validate an entire script by finding a command word
somewhere in a page, example, navigation bar or prose paragraph. Unsupported
FISH/parameter-combination checks stay CANNOT_VERIFY; full grammar validation
is not a first-path promise. Topic-only queries are discovery, not verification.

Citation records include source identity/trust class, relative page/anchor,
product, family/build, body digest, acquisition/read time, check time, query
syntax digest and coverage scope. Resolved reads must remain inside the
registered root. Missing pages, invalid locations, source mismatch, unknown
version or content drift cannot reuse a previous VERIFIED result.

Fixtures have an explicit synthetic trust class and can only satisfy synthetic
tasks. R1 acceptance requires both synthetic negative tests and a real local
HTML smoke with applicable and mismatched-version cases. R0 observation is
selection evidence only; the reader and production gate remain unimplemented.
Official-web and installed auto-discovery remain unavailable until implemented.

## 6. Cognition and review rules (R4 implementation)

Observations do not carry an authoritative free-text explanation. Fixed policy
rules may derive a low-risk project lesson from structured observations with
matching evidence and scope. Two matching runs alone are not sufficient.

Dependencies use record/asset ID plus revision or digest. Optional time expiry
uses an explicit evaluation time. Product version is a domain-specific
dependency, not a required field for every literature or experimental lesson.
An updated dependency marks a lesson stale; it does not delete historical
evidence or reverse a human decision without an explicit new record.

Conflict keys identify subject, predicate and applicable scope. Structured
incompatible observations or explicit contradiction edges mark contested;
natural-language contradiction detection creates a candidate only. Only
dependent actions block. Review queues deduplicate by claim/scope/evidence
revision; unadopted ordinary proposals do not demand human approval.

Human adoption requires evidence, scope, impact and a trusted Host review
channel. created_by/impact/requested_status are requests, not authority.
Same-filesystem arbitrary writes are outside the controlled-API guarantee.

## 7. R0 acceptance and next handoff

R0 exit: type admission regression passes, existing suite stays green, these
decisions select an actionable real-doc path, and status no longer treats old
Phase 1/2 PASS as proof of the revised requirements. Broader shape/reference/
policy checks, role migration and transactional implementation belong to R1/R2.

R1 write set is the documentation provider, its actual consumer/config boundary
and focused tests/examples. It must eliminate metadata-only VERIFIED before
any task consumer treats citations as permission. Keep the source documents
external, production/fake evidence distinct and execution disabled.
