# R4 Core Cognition quick start

R4 stores cognition proposals, reviews, mechanical observations and failures
as project-local ResearchStore transactions. `research/core_cognition.json`
is a disposable view.

After a real test or tool action has produced an observation, record that
observation. Put the actual captured value in `observation.json` and its real
location in `locator.json`; the placeholders below are not results to copy.

```powershell
python mining_kernel.py cognition-observe --project-root path/to/project `
  --operation-id observe-check-1 --observation-kind structured_test `
  --observation-json '@observation.json' --locator-json '@locator.json'
```

Submit a proposal with `cognition-propose`. A located Evidence reference and a
structured `fact_key`/`fact_value` pair are required for the narrow automatic
`provisional` path. `requested_status` is only a request. `accepted` requires
a trusted Host review boundary through the Python API; the CLI has no complete
promotion path and therefore fails closed. The lower-level ResearchStore also
rejects an accepted proposal unless the same transaction contains the review
record and typed review provenance. Free-text interpretation cannot become
authority automatically, and the Cognition view is rebuildable from records.

Rebuild the view, optionally filtering failures by route, task, object or
product version:

```powershell
python mining_kernel.py cognition-rebuild --project-root path/to/project
python mining_kernel.py cognition-rebuild --project-root path/to/project `
  --route-id route-a --version 9.6
```

`failure-record` preserves complete failure context. Failure records are
filtered into the view without treating a failed or `cannot_verify` attempt as
a success. Natural-language similarity is not a conflict rule; only the
structured key/value contract and explicit contradiction relationships affect
the corresponding proposals. Any free-text `expiry_conditions` field is kept
as context and is never used to invalidate a proposal; invalidation uses the
record revision, content hash and fixed conditions recorded by the service.

Before a related task or route proceeds, an Agent can run the mechanical
failure gate. An unresolved related failure returns `blocked` with its IDs;
an unrelated route returns `clear`.

```powershell
python mining_kernel.py cognition-failure-gate --project-root path/to/project `
  --route-id route-a --version 9.6
```
