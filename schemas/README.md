# Schemas

All contracts use `schema_version: 1`. The CLI rejects missing or unknown
versions. JSON schema parsing and runtime output conformance are separate
checks: a readable schema file does not prove that a generated packet or
record satisfies it. Runtime records are also checked by
`mining_kernel.validate_record` and the owning service validators.

`ResearchMap` and `CoreCognition` are rebuildable views. `CognitionProposal`,
`CognitionReview` and `Failure` records are validated at the ResearchStore
write boundary; the JSON views are never their source of authority.

The legacy `asset.schema.json` describes the original flat Asset contract.
ResearchStore transaction records use `research_asset.schema.json` and
`research_evidence.schema.json`; their runtime reference and authority rules
remain enforced by ResearchStore. The two contracts must not be conflated.

`task_completion.schema.json` describes the explicit route, run, verification,
gate-coverage, evidence, and output references accepted by `task-complete`.
`verification_gate_coverage` is keyed by route and current TaskPacket gate;
each value lists the current Verification records that cover that gate. Each
entry repeats the Verification record `gate_id` as `verification_gate_id`; the
runtime requires both IDs to equal the packet gate key.
Runtime checks against current records and the Run Ledger remain authoritative.
