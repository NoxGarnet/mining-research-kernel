# Reusable FLAC3D review workflow

Use this for one bounded question inside an existing project. It supports
ordinary Markdown project entries and files; it does not require a form,
database, CLI, FLAC3D installation, MCP, or model execution. It does not imply
that a complete model or engineering decision has been checked.

1. **Recover the task.** Read the project `START.md` and relevant entry or
   handoff. Identify the user's question, intended delivery, boundaries, and
   finish or handoff criteria. The user keeps decision authority. Do not make
   an intake form mandatory or ask them to repeat settled decisions. Keep
   user-confirmed decisions, Agent suggestions, and pending decisions
   distinguishable in ordinary prose. A newly noticed issue outside the agreed
   scope is a suggested follow-up, not an automatically added task. Continue
   authorized work within scope without requiring each step to be reconfirmed.
2. **Locate the evidence.** Identify the specific input file(s) and the
   FLAC3D version from project evidence or the user. Record project-relative
   paths and what established the version. If a path or version is unknown,
   say so; do not fill gaps from memory or imply an input was read when only
   its path was found.
3. **Match official documentation.** Find the official Itasca material for
   that product version and the exact command, keyword, or concept in scope.
   Prefer the local official documentation when it matches. Record the
   product/documentation version, page title, stable page or section locator,
   and the specific point read. If the matching source cannot be identified
   or does not resolve the question, make that limit explicit. The optional
   [R1 local documentation check](R1_DOCUMENTATION.md) can check a command
   name against a registered local HTML source. Its result covers command
   names only, not options, ordering, execution, or engineering applicability;
   manual source reading does not require a registration or research ledger.
4. **Do one bounded check.** Choose one check that advances the agreed task,
   such as comparing a command line or sequence in a named file against the
   matching reference. State exactly what was inspected. Keep static file
   reading, documentation review, automated checks, and a real solver run as
   separate evidence types. A registered adapter does not prove a tool is
   available; a solver run needs a suitable environment and task-specific
   authorization.
5. **Write an auditable report.** Link each finding to an input path and line
   or other locator, and to the documentation page/section. Separate direct
   observations, interpretations or inferences, and unchecked items. Record
   whether any solver or other runtime validation occurred. Keep original
   inputs intact. Never present synthetic fixtures as model results.
6. **Write back and hand off.** Update the project's `START.md` with a short
   current status, the agreed scope, the report link, and only the gaps or
   decisions relevant to continuation. Keep detailed findings in the report
   so the entry does not duplicate them. For a new session that receives only
   the project entry, a short continuation prompt can help: read the entry,
   open its linked report and named input, preserve the stated boundaries, and
   ask the user only about consequential unresolved decisions. Assess delivery
   against the agreed scope. Label optional follow-ups as suggestions; items
   outside scope or explicitly deferred do not become completion requirements.
   Report any gap that still prevents the agreed delivery.

An end-to-end, file-only example is in
[`examples/flac3d_review/`](../examples/flac3d_review/README.md). It shows a
completed static command check against local FLAC3D 9.6.44 documentation; it
does not claim a solver result.
