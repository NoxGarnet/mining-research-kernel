# v0.1.0 candidate acceptance summary

This is a public, sanitized summary for the code baseline
`72a2d6bcb80d6136c27d2aca61a0ce890f9ab9fd`. It records the earlier clean
checkout acceptance of that code baseline. Later documentation and reference
example changes are uncommitted and are not represented by this baseline hash.

The corresponding acceptance environment was Windows with Python 3.14.2 and
`jsonschema` 4.26.0 available. Only that environment was exercised; this does
not establish a general Python compatibility range.

| Layer | Result | Meaning |
|---|---:|---|
| Complete test suite | 200 run; 199 passed; 1 skipped; 0 failed | Code regression result for the identified baseline. |
| README applicable commands | 10/10 succeeded | CLI and initialization examples returned successfully in the clean checkout. |
| JSON schema files | 19 parsed | The schema documents were readable JSON; this does not validate generated output. |
| Runtime output validation | 2 outputs passed `task_packet.schema.json` | Representative `task-start` and `task-inspect` outputs matched the applicable schema. |
| File symlink coverage | 1 test skipped | The environment could not create file symlinks; this is platform coverage, not a pass. |

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
