# v0.1.0 candidate acceptance summary

This is a public, sanitized summary for the code baseline
`35c141243e60f3386da1255530b17492f8e754e7`, accepted on 2026-09-09.
The tests ran in a new local Git clone without shared objects or hardlinks,
with an initially clean checkout that remained clean after acceptance.
The later acceptance-record commit changes documentation only.

The corresponding acceptance environment was Windows with Python 3.14.2 and
`jsonschema` 4.26.0 available. Only that environment was exercised; this does
not establish a general Python compatibility range.

| Layer | Result | Meaning |
|---|---:|---|
| Complete test suite | 209 run; 208 passed; 1 skipped; 0 failed | Code regression result for the identified baseline. |
| Offline CLI acceptance | 18/18 succeeded | Standard-library isolated discovery/validation, read-only fixture inspection, help, and both R5 synthetic project workflows. |
| JSON schema files | 19 passed schema checks | The schema documents passed Draft 2020-12 schema validation; this is separate from output validation. |
| Runtime output validation | 6 outputs passed `task_packet.schema.json` | Start, pre-run inspect and separate-process post-run inspect for both fixture workflows. |
| File symlink coverage | 1 test skipped | The environment could not create file symlinks; this is platform coverage, not a pass. |

Both fixture workflows recovered `state=completed` and a non-executable next
action from a separate process, then rebuilt their Research Map. Generated
projects and logs were outside the clone. The commands and outputs are held
in the local acceptance handoff; none requires a live Zotero reader.

The security changes reserve production documentation evidence for trusted
Host injection. Ordinary request/CLI JSON cannot supply production VERIFIED
or override a Host result. Fixed records and runs paths reject pre-existing
symlinks/junctions before resolving them; explicit ordinary external output
directories remain supported. The task run path checks before reserving a
run or dispatching a provider, so rejection does not consume its budget.

An independent Astra review of the final preflight change passed 39 relevant
tests without skips and directly checked junction rejection, same-operation
retry after removing the link, and idempotent replay. The fresh-clone suite
includes all nine new security regression tests. This is bounded verification
of the two reported findings, not a new full-repository security audit.

Trusted Host registrations remain an integration responsibility. Historical
VERIFIED TaskStates are not automatically revalidated. Malicious same-user
filesystem changes and concurrent directory swapping remain outside the
v0.1.0 boundary described in SECURITY.md. File-symlink creation failed with
Windows error 1314, so that platform branch remains explicitly unverified.

The earlier `72a2d6bcb80d6136c27d2aca61a0ce890f9ab9fd` acceptance recorded
200 tests (199 passed, one skipped). Those historical counts are not reused
as results for the current baseline.

The acceptance did not run FLAC3D, validate a full FLAC3D script, establish
numerical, physical or engineering validity, access a real Zotero library, or
validate a complete `itasca-mcp` integration. The production FLAC3D
`static_check` capability remained unimplemented and blocked; synthetic
execution and synthetic static checking remained fixture paths.

ResearchStore, TaskState, routes, Run Ledger, Evidence/Verification,
Research Map, Cognition views and completion checks are real local kernel
mechanisms. They must be distinguished from synthetic domain results and from
user-provided Itasca documentation or Zotero resources.

This summary excludes local paths, raw logs, private research materials,
official vendor documentation, Host configuration and credentials. Public
visibility, tag creation and Release creation were not part of this
acceptance.
