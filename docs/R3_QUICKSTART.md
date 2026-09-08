# R3 bounded route exploration

R3 stores each route as a versioned `Route` record under
`research/records/`. A route must declare a non-empty `write_set` and a
per-route run budget. `route-reserve` persists the reservation before any
external work would be dispatched. A new process can inspect and finish that
reservation, so an interrupted agent does not silently spend a second run.

The project configuration has an optional `route_policy.max_active_routes`.
It defaults to 3 and may be set from 1 to 3. The route service rejects larger
values. The limit applies to active routes for one `ResearchQuestion`; budget
and write-set checks are independent stops. When a route carries a `task_id`,
its reservation also consumes the existing TaskState `max_runs`; reopening a
failed route or adding a child cannot reset that task budget.

With a project that already contains a `ResearchQuestion` record, propose two
routes:

```powershell
python mining_kernel.py route-propose --project-root path/to/project `
  --route-json '@route-a.json' --operation-id propose-route-a
python mining_kernel.py route-propose --project-root path/to/project `
  --route-json '@route-b.json' --operation-id propose-route-b
python mining_kernel.py route-reserve --project-root path/to/project route-a `
  --operation-id reserve-route-a
python mining_kernel.py route-finish --project-root path/to/project route-a `
  --reservation-id reserve-route-a --outcome cannot_verify `
  --operation-id finish-route-a --stop-reason official_source_missing
python mining_kernel.py route-reject --project-root path/to/project route-b `
  --operation-id reject-route-b --reason method_out_of_scope
python mining_kernel.py route-compare --project-root path/to/project `
  --question-id question-1 --comparison-id comparison-1 `
  --operation-id compare-1
```

`route-finish` accepts `completed`, `failed`, and `cannot_verify`. All three
consume the reservation's budget; the latter two remain explicit failure
states. `route-reject` closes a proposal or blocked route without making a
scientific assertion. `route-reopen` preserves prior reservations, outputs, and
`runs_used`. `route-supersede` records both the replacement and the retired
route plus a typed relationship. `route-compare` creates a deterministic
archive containing route status, budget use, outputs, and stop reason. The
archive is descriptive, keeps a common `claim_id` when supplied, and does not
create or accept a `Claim`.

R3 is a lifecycle and provenance mechanism. It does not execute FLAC3D,
contact Zotero, select an engineering winner, or infer scientific validity.
