# Local official documentation checks

R1 provides a bounded command-name check against an explicitly registered local
HTML source. It does not run FLAC3D, fetch web pages or validate a complete
script. See COMPLETION_STATUS.md for the current acceptance result.

## What the check establishes

The reader must open the registered HTML page, verify its pinned digest, read
its documentation family/build and locate the requested command signature in
the Syntax section. A successful result covers only the command name. Options,
parameter combinations, FISH programs, numerical behavior and engineering
applicability remain outside that result.

Production success is VERIFIED. Synthetic success is SYNTHETIC_VERIFIED and is
never sufficient for a production task. Missing or inapplicable evidence gives
CANNOT_VERIFY. The CLI exits 0 for a success in its stated context and 2 for
an unverified request or invalid registration; callers must inspect status and
coverage, not just the exit code.

The future Task Engine must bind the task's requested syntax, source identity,
content/query digests and coverage to the returned citation. It must not turn a
command-name check into permission to modify an entire script. That integration
belongs to R2; R1 is directly usable through the CLI and Python API.

## Register a source once at the Host boundary

Select a local official documentation installation or other independently
established official copy. A Host/operator-owned registration binds its root,
product subtree, documentation family/build and specific page digests. A query
cannot establish publisher identity by returning a logo, URL, version string
or callback claiming to be official.

This is an explicit local trust boundary, not cryptographic publisher
authentication. An Agent with arbitrary filesystem access can also edit a
registration; use the Host's access controls if stronger isolation is needed.
Do not create trusted registrations automatically from search results or from
the query itself.

Save a JSON registration outside versioned project data (for example
`config.local.documentation.json`, ignored by this repository). Paths relative
to the registration file are resolved against its parent. An example shape:

```json
{
  "schema_version": 1,
  "source_id": "itasca.docs.local",
  "root": "<operator-selected documentation root>",
  "product": "flac3d",
  "document_family": "9.6",
  "document_build": "9.6.44",
  "trust_class": "official_local",
  "product_subdir": "flac3d",
  "pages": {
    "flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html": "<64 lowercase SHA-256 hex characters>"
  }
}
```

Replace both placeholders with values from the selected source. The example
family/build describe the source used for local acceptance, not a recommended
version and not the installed executable's version. A 9.0 target must not use
this 9.6 source as applicable evidence. For another source, inspect its actual
metadata and register that version instead.

To obtain a page digest in PowerShell, without changing it:

```powershell
(Get-FileHash -LiteralPath '<full path to the selected HTML page>' -Algorithm SHA256).Hash.ToLowerInvariant()
```

Digests detect later changes; they do not themselves prove official provenance.
A changed source needs reinspection and registration update at the trusted
boundary. Do not silently repin a page when a check reports a mismatch.

## Run the bounded check

From the repository root, with a completed registration:

```powershell
python mining_kernel.py documentation-check --registration config.local.documentation.json --page flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html --command "zone list" --product flac3d --product-version 9.6 --anchor command:zone.list
```

A family target must match the actual document family; a full build target must
match the actual build. Unknown or omitted target versions must not be inferred
from the document. The page path is relative to the registered source root and
must stay inside both that root and the registered product subtree.

Changing the target to 9.0 is an expected CANNOT_VERIFY result for the example
9.6 source. Omitting --command is a topic-only request and cannot verify syntax.
Adding unsupported arguments or a whole script to --command cannot pass merely
because its first words name a known command.

The reader does not execute embedded JavaScript or fetch images, fonts, scripts
or other linked resources. Embedded document version metadata is read as text.
An unavailable external documentation_options.js must not prevent parsing
equivalent embedded metadata.

## Python usage and compatibility

```python
from providers.documentation import load_registration, resolve_documentation

source = load_registration("config.local.documentation.json")
provider = resolve_documentation({"provider": "local"}, registration=source)
result = provider.verify_syntax(
    "flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html",
    "zone list",
    product="flac3d",
    product_version="9.6",
    anchor="command:zone.list",
)
```

Registration is a separate Host input, not a field accepted from the syntax
query. Citation metadata identifies the source, page/anchor, document version,
read/check times, body/query digests and coverage. It does not reproduce the
source HTML or distribute the official manual.

Legacy metadata-only indexes and injected official_lookup/installed_lookup
callbacks cannot return VERIFIED. Installed auto-discovery and official-web
transport are not implemented in R1. Existing project-relative documentation
configuration remains readable for compatibility, but it is not a trusted
source registration. The explicit CLI works independently of project setup.

## Synthetic and real-source acceptance

TaskEngine's constructor and the Python `task_start` function's separate
`documentation_result` argument are trusted Host integration points. The Host
must supply the result of its selected DocumentationProvider; it must not
forward Agent-controlled JSON into these arguments. A supplied Host result,
including a failed or empty result, takes precedence over request evidence.
This is an API trust boundary, not authentication or proof of official origin.

Production tasks do not use `request.documentation_result` as verification
evidence. The `task-start --documentation-result` CLI option supplies request
data only and overrides the same field in `--request-json`; it can support
synthetic tasks but cannot produce production VERIFIED. For production, use
the trusted Python Host integration after the documentation check. Persisted
TaskStates from earlier versions are not revalidated by this change.

Synthetic tests generate handmade HTML in temporary directories. A synthetic
registration requires --task-context synthetic and returns SYNTHETIC_VERIFIED;
the default production context rejects it. Public tests never need a real
Itasca installation, license or original documentation body.

Real-source acceptance is separate: an operator-selected external HTML source
must pass its applicable command-name request and reject a mismatched version.
Source location and detailed smoke output stay host-local. Public completion
evidence may record the version, relative page, digest, outcomes and limits.
Neither test category establishes execution, numerical or engineering validity.
