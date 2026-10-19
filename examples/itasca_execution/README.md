# Offline external-execution records

This standard-library example authors synthetic MCP responses and two CSVs. It
does not start or call FLAC3D, a bridge or an MCP server. Its recorded completion
is a teaching observation, not a real solver result.

From the repository, choose a new or empty directory outside the code checkout:

```powershell
python -S -B -X utf8 examples/itasca_execution/demo.py --output path/to/new-teaching-study
```

The example prepares a bounded script snapshot, records a synthetic submission
and completion, captures two outputs, and uses the existing result comparison.
It then moves the original input and output paths and recovers both reports in
fresh CLI processes without modifying the research ledger. Existing nonempty
directories are rejected.

[简体中文指南](../../docs/ITASCA_EXECUTION.zh-CN.md) · [English guide](../../docs/ITASCA_EXECUTION.md)
