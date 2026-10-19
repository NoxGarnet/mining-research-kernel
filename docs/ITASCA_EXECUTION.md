# External Itasca task observations

[简体中文](ITASCA_EXECUTION.zh-CN.md) | **English** · [Home](../README.en.md)

The Agent uses its existing Itasca tools to run an explicitly scoped task. The
kernel records the selected script, external task observations and bounded
outputs, then restores them from local records. These commands do not call an
engine, enable the unimplemented production static check, or establish numerical,
physical or engineering validity.

1. Use `itasca-run-prepare --project-root ... --run-id ... --script ... --metadata-file ...`
   to capture a project-relative UTF-8 Python entry script, at most 256 KiB.
   Metadata declares `software: "flac3d"`, `product_version`, `purpose`,
   `stop_conditions`, project-relative `output_root`, a host-selected
   `engine_session` label, and `origin: "provided_script"` or `"synthetic"`.
   Optional `question_id` binds an existing research question. The preparation
   receipt's `run_ref.id` is distinct from the external MCP task ID.
2. The Agent submits through its existing MCP under the project's authorization.
   With `itasca-run-record`, save the actual inner `ok/data` or `ok/error` response
   in an observation containing `schema_version: 1`,
   `kind: "itasca_execution_observation"`, `origin`, actual UTC `captured_at`,
   `phase: "submission"` or `"status"`, and `tool_result`. Submission checks the
   selected entry path and current script digest. Status observations retain
   `task_id`, `task_status`, bounded output and pagination. Entry snapshots do not
   capture dependencies or authenticate actual engine execution.
3. Reuse an operation ID only for an identical request. Wrong task associations,
   conflicts and terminal-state regressions are rejected. An uncertain submission
   remains uncertain; no automatic resubmission occurs. A timeout does not prove
   that execution did not start. CLI recording success means the observation was
   saved, not that the external run succeeded.
4. After a terminal observation, `itasca-output-import --path ... --kind csv|log|text`
   captures a selected UTF-8 file within the declared output root, at most 1 MiB.
   Failed/interrupted outputs are diagnostic. A completed run's captured CSV may
   feed `result-import --run-ref <run_ref.id>` when path, bytes and context match.
   The [existing CSV contract](RESULT_COMPARISON.md) still applies. This preserves
   a caller/tool association; matching digests alone do not prove that the engine
   produced the file from that script. SAV/binary imports are out of scope.
5. `itasca-run-progress` and `itasca-run-report --output reports/execution.md`
   restore saved records without contacting the engine or reopening originals.
   Project navigation exposes run progress/report commands. Recovery does not
   resume the solver, refresh status, restart a task or imply complete logs.

The [Chinese guide](ITASCA_EXECUTION.zh-CN.md) includes full JSON and CLI examples.
Keep real file paths, logs and model data in the selected private project.
Reports are derived views with protected output paths. The workflow creates no
engineering Verification and cannot close native execution gates by itself.

Synthetic plans, observations and results require the synthetic context and
cannot become production evidence. Try the [offline authored example](../examples/itasca_execution/README.md)
without an engine or MCP connection.
