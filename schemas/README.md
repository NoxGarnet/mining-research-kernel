# Schemas

All contracts use `schema_version: 1`. The CLI rejects missing or unknown
versions. JSON schema parsing and runtime output conformance are separate
checks: a readable schema file does not prove that a generated packet or
record satisfies it. Runtime records are also checked by
`mining_kernel.validate_record` and the owning service validators.

`ResearchMap` and `CoreCognition` are rebuildable views. `CognitionProposal`,
`CognitionReview` and `Failure` records are validated at the ResearchStore
write boundary; the JSON views are never their source of authority.
