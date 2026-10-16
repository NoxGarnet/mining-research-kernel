# FLAC3D file review example

This is a small, anonymous demonstration of an existing project after its
entry and inputs have been located. All project names and input content here
are fabricated for documentation review; they contain no private model,
geometry, measurements, or engineering conclusions.

The bounded example checks one command spelling in
[`cases/sequence_review.dat`](cases/sequence_review.dat) against the official
FLAC3D 9.6.44 command reference. The completed report is
[`reports/command-review.md`](reports/command-review.md), and the short project
state and next-session handoff are in [`START.md`](START.md). The command
reference locator is recorded in the report; no official documentation text is
copied here.

The `.dat` file is an authored text fixture for file reading only.
It is not a runnable project model, and no solver or FISH execution was
performed. Nothing in this example is a FLAC3D result.

From the repository root, the read-only navigation command is:

```powershell
python -B -X utf8 mining_kernel.py project-context --project-root examples/flac3d_review
```

It reads the project's `START.md` and `README.md` as navigation entries and
lists their explicitly linked report and input paths. It does not open or
verify the linked source files; follow the report links to read the evidence.
