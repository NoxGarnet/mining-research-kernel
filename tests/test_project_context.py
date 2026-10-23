import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from flac3d_project import init_project
from mining_research_kernel.cognition import CoreCognition
from mining_research_kernel.project_context import project_context
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_start, task_record_evidence_review


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project with spaces"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob("*") if p.is_file()}

    def all_items(self):
        items, offset = [], 0
        while True:
            page = project_context(self.root, offset=offset, limit=20)
            if not page["budget"]["oversized_single_entry"]:
                self.assertLessEqual(len(json.dumps(page, ensure_ascii=False, indent=2)), 4000)
            items.extend(page["items"])
            offset = page["page"]["next_offset"]
            if offset is None:
                return items

    def initialize(self):
        self.root.rmdir()
        init_project(self.root, "context-fixture")
        source = self.root / "cases/source.txt"
        source.write_text("synthetic source only", encoding="utf-8")
        material = ResearchStore(self.root).register_local_material("cases/source.txt", "project_record")
        return source, material

    def task(self, name, material, refs=None):
        request = {"task_id": name, "question_statement": "Which bounded route should be examined?",
                   "claim_statement": "Synthetic evidence remains unverified.",
                   "task_type": "mining_research_kernel.task.evidence_review",
                   "maturity": "exploratory", "max_runs": 1, "task_context": "production",
                   "asset_refs": [material["asset"]["id"]],
                   "evidence_refs": [material["evidence"]["id"]]}
        if refs:
            request["refs"] = {"decisions": refs}
        return task_start(self.root, request)

    def complete(self, name, material):
        packet = self.task(name, material)
        reads = [{"asset_id": item["asset_id"], "evidence_refs": item["evidence_refs"],
                  "observed_sha256": item["content_sha256"], "reading_status": "READ_WITH_LIMITS",
                  "verification_status": "NOT_VERIFIED", "locator": {"kind": "line", "value": "1"},
                  "summary": "bounded synthetic reading", "numeric_check_status": "NOT_APPLICABLE",
                  "scientific_validation_status": "NOT_VERIFIED", "gaps": []}
                 for item in packet["material_reads"]]
        return task_record_evidence_review(self.root, name, "review-" + name, {
            "scope": "material_reading_and_evidence_synthesis_only", "material_reads": reads,
            "material_gaps": [], "judgment": {"status": "PROVISIONAL_WITH_GAPS",
                "summary": "Only a bounded synthetic observation, not validation.",
                "gaps": ["no engineering validation"],
                "next_action": {"action": "inspect missing evidence", "executable": False}}})

    def test_plain_entry_links_without_initialization_or_target_reads(self):
        (self.root / "START.md").write_text(
            "# Research question\n[Evidence](inputs/evidence.txt#table)\n"
            "[Missing](inputs/missing.txt)\n[Outside](../secret.txt)\n"
            "[Web](https://example.invalid/ignored)\n", encoding="utf-8")
        (self.root / "inputs").mkdir()
        source = self.root / "inputs/evidence.txt"
        source.write_text("SOURCE MUST NOT BE READ", encoding="utf-8")
        before = self.snapshot()
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path == source:
                raise AssertionError("source reopened")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            result = project_context(self.root)
        self.assertEqual("not_initialized", result["store_state"])
        self.assertEqual(3, result["counts"]["materials"])
        self.assertIn("unsafe_path_not_followed", json.dumps(result))
        self.assertIn("not_checked", json.dumps(result))
        self.assertNotIn("SOURCE MUST NOT BE READ", json.dumps(result))
        self.assertEqual(before, self.snapshot())
        self.assertFalse((self.root / "research").exists())

    def test_empty_project_and_explicit_manifest(self):
        result = project_context(self.root)
        self.assertEqual([], result["items"])
        self.assertTrue(result["warnings"])
        (self.root / "list.json").write_text(json.dumps({"materials": [
            {"path": "unknown.csv", "title": "selected data"}]}), encoding="utf-8")
        self.assertEqual(0, project_context(self.root)["counts"]["materials"])
        result = project_context(self.root, manifest="list.json")
        self.assertEqual(1, result["counts"]["materials"])
        self.assertEqual("not_checked", result["items"][0]["location"]["existence"])
        with self.assertRaises(ValueError):
            project_context(self.root, manifest="../list.json")
        (self.root / "list.json").write_text('{"materials":[{}]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"materials\[0\].path"):
            project_context(self.root, manifest="list.json")

    def test_malformed_link_warns_without_hiding_valid_materials(self):
        (self.root / "START.md").write_text(
            "[Broken](http://[)\n[Evidence](inputs/evidence.csv)\n`notes.txt`\n",
            encoding="utf-8")
        before = self.snapshot()
        view = project_context(self.root, limit=20)
        materials = [row for row in view["items"] if row["kind"] == "material"]
        self.assertEqual(["Evidence", "notes.txt"], [row["title"]["text"] for row in materials])
        self.assertTrue(any("START.md: malformed link ignored" in warning for warning in view["warnings"]))
        self.assertEqual(before, self.snapshot())

    def test_comments_do_not_become_materials_or_shift_visible_path_lines(self):
        text = (
            "<!-- [Old](old.csv)\n`hidden.txt` -->\n"
            "<!--\n```md\n[Archived](archived.csv)\n-->\n"
            "[Evidence](evidence.csv)\n`notes.txt`\n"
            "<!-- unfinished [Hidden](hidden.csv)\n`other.txt`\n"
        )
        (self.root / "START.md").write_text(text, encoding="utf-8")
        before = self.snapshot()
        view = project_context(self.root, limit=20)
        materials = [row for row in view["items"] if row["kind"] == "material"]
        self.assertEqual(["Evidence", "notes.txt"], [row["title"]["text"] for row in materials])
        self.assertEqual(8, materials[-1]["entry_line"])
        self.assertEqual(before, self.snapshot())

    def test_fenced_examples_do_not_become_materials(self):
        cases = (
            "```md\n[Example](inputs/example.csv)\n`hidden.txt`\n",
            "````md\n```\n[Example](inputs/example.csv)\n`hidden.txt`\n````\n",
            "~~~md\n```\n[Example](inputs/example.csv)\n`hidden.txt`\n~~~\n",
            "\t```md\n[Example](inputs/example.csv)\n`hidden.txt`\n",
        )
        entry = self.root / "START.md"
        for example in cases:
            with self.subTest(example=example):
                entry.write_text("[Evidence](inputs/evidence.csv)\n" + example, encoding="utf-8")
                view = project_context(self.root, limit=20)
                materials = [row for row in view["items"] if row["kind"] == "material"]
                self.assertEqual(["Evidence"], [row["title"]["text"] for row in materials])
        # Bounded reads can cut off the closing fence of an otherwise valid file.
        text = "[Evidence](inputs/evidence.csv)\n```md\n[Example](inputs/example.csv)\n```\n"
        entry.write_text(text, encoding="utf-8")
        with patch("mining_research_kernel.project_context.MAX_ENTRY_BYTES", len(text) - 4):
            view = project_context(self.root, limit=20)
        self.assertEqual(1, view["counts"]["materials"])
        self.assertTrue(any("only first" in warning for warning in view["warnings"]))

    def test_inline_link_examples_are_ignored_and_file_paths_keep_line_numbers(self):
        text = (
            "# Entry\n`[Example](inputs/example.csv)`\n"
            "``[Nested `example`](inputs/nested.csv)``\n"
            r"\[Escaped](inputs/escaped.csv)" + "\n"
            "[Evidence](inputs/evidence.csv)\n````md\n```\n`hidden.txt`\n````\n"
            "`notes.txt`\n"
            "``outer `nested.txt` example``\n"
            r"\`escaped.txt`" + "\n"
        )
        (self.root / "START.md").write_text(text, encoding="utf-8")
        materials = [row for row in self.all_items() if row["kind"] == "material"]
        self.assertEqual(["Evidence", "notes.txt"], [row["title"]["text"] for row in materials])
        self.assertEqual(10, materials[-1]["entry_line"])

    def test_configured_nested_entry_resolves_links_without_opening_sources(self):
        from research_project import enable_research
        enable_research(self.root, "nested-entry")
        (self.root / "research_project.json").write_text(json.dumps({
            "schema_version": 1, "project_id": "nested-entry", "entry": "notes/ENTRY.md"
        }), encoding="utf-8")
        (self.root / "notes").mkdir()
        (self.root / "notes/ENTRY.md").write_text(
            "[Material](source.txt)\n`other.txt`\n", encoding="utf-8")
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.suffix == ".txt":
                raise AssertionError("source opened")
            return original(path, *args, **kwargs)
        before = self.snapshot()
        with patch.object(Path, "open", guarded):
            result = project_context(self.root)
        self.assertEqual(1, result["counts"]["entries"])
        materials = [i for i in result["items"] if i["kind"] == "material"]
        self.assertEqual({str((self.root / "notes/source.txt").resolve()), str((self.root / "notes/other.txt").resolve())},
                         {i["location"]["path"] for i in materials})
        self.assertEqual(before, self.snapshot())

    def test_inline_paths_have_entry_lines_without_reading_sources(self):
        text = ("# Project\n```text\n`ignored.md`\n```\n"
                "- `docs/decisions.md`\n- `conclusion.md`\n"
                "- `docs\\notes.md`\n- `资料/说明.md`\n"
                "- `./docs/decisions.md`\n[Report](conclusion.md)\n")
        (self.root / "README.md").write_text(text, encoding="utf-8")
        (self.root / "conclusion.md").write_text("DO NOT OPEN", encoding="utf-8")
        before = self.snapshot()
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path.name == "conclusion.md":
                raise AssertionError("source opened")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            items = [i for i in self.all_items() if i["kind"] == "material"]
        self.assertEqual(4, len(items))
        decision = next(i for i in items if i["title"]["text"] == "docs/decisions.md")
        self.assertEqual(5, decision["entry_line"])
        self.assertEqual("not_checked", decision["location"]["existence"])
        self.assertEqual(before, self.snapshot())

    def test_inline_code_absolute_and_traversal_are_not_materials(self):
        tokens = ["recover surface", "slide on", "zone.state", "output_root", "1.0",
                  "python tool.py", "x=notes.md", "read('notes.md')", "dir/",
                  "../secret.md", "docs/../../secret.md", "/secret.md", "C:\\secret.md",
                  "https://host/secret.md", "$(secret.md)", "notes.md;rm", "*.md"]
        (self.root / "START.md").write_text("\n".join(f"`{v}`" for v in tokens), encoding="utf-8")
        self.assertEqual(0, project_context(self.root)["counts"]["materials"])

    def test_persisted_tasks_conflicts_and_no_source_read_or_map_write(self):
        source, material = self.initialize()
        first = self.complete("task-a", material)
        second = self.complete("task-b", material)
        self.task("task-c", material, [first["review_record_ref"], second["review_record_ref"]])
        CoreCognition(self.root).record_failure({"failure_id": "failure-one",
            "observable_failure": "version mismatch", "task_id": "task-a"}, "record-failure")
        before = self.snapshot()
        original = Path.open
        def guarded(path, *args, **kwargs):
            if path == source:
                raise AssertionError("source reopened")
            return original(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            view = project_context(self.root, limit=20)
            items = self.all_items()
        self.assertIsNone(view["active_task"])
        task = next(i for i in items if i["id"] == "task-c")
        self.assertEqual("unresolved_current_conflict", task["selection"])
        self.assertEqual(2, task["conflict_count"])
        self.assertEqual(1, view["counts"]["failures"])
        self.assertEqual(before, self.snapshot())
        # Returned argv works verbatim from a different current directory.
        run = subprocess.run(task["resume_argv"], cwd=self.temp.name, capture_output=True,
                             text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual("TaskResumeView", json.loads(run.stdout)["type"])

        # Follow compact pages: none of the tasks/materials/conflicts may vanish.
        self.assertEqual(3, sum(i["kind"] == "task" for i in items))
        self.assertTrue(any(i.get("conflict_count") == 2 for i in items))

    def test_pagination_cli_and_invalid_limits(self):
        (self.root / "START.md").write_text("\n".join(f"[source{i}](source{i}.txt)" for i in range(25)), encoding="utf-8")
        first = project_context(self.root, limit=3)
        self.assertEqual(26, first["page"]["total"])
        self.assertEqual(3, len(first["items"]))
        run = subprocess.run(first["page"]["next_argv"], cwd=self.temp.name,
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, run.returncode, run.stderr)
        self.assertEqual(3, json.loads(run.stdout)["page"]["offset"])
        for options in ({"offset": -1}, {"limit": 0}, {"limit": 21}):
            with self.assertRaises(ValueError):
                project_context(self.root, **options)

    def test_long_entry_and_corrupt_store_are_not_silent_success(self):
        (self.root / "START.md").write_text("x" * 70000, encoding="utf-8")
        view = project_context(self.root)
        self.assertTrue(view["items"][0]["entry_scan_truncated"])
        self.assertTrue(view["items"][0]["preview"]["truncated"])
        self.assertTrue(view["warnings"])
        (self.root / "flac3d_project.yaml").write_text("{}", encoding="utf-8")
        with self.assertRaises(ValueError):
            project_context(self.root)

    def test_metadata_symlink_escape_is_rejected(self):
        outside = Path(self.temp.name) / "outside.md"
        outside.write_text("not authorized", encoding="utf-8")
        try:
            (self.root / "START.md").symlink_to(outside)
        except OSError:
            self.skipTest("file symlink creation unavailable")
        with self.assertRaises(ValueError):
            project_context(self.root)

    def test_source_drift_stays_unverified_and_caller_path_is_not_guessed(self):
        source, material = self.initialize()
        self.complete("task-a", material)
        source.write_text("changed since registration", encoding="utf-8")
        external = Path(self.temp.name) / "external.txt"
        external.write_text("external", encoding="utf-8")
        ResearchStore(self.root).register_local_material(str(external), "project_record")
        assets = [i for i in self.all_items() if i["kind"] == "asset"]
        self.assertEqual(2, len(assets))
        self.assertTrue(any(i["location"]["status"] == "not_read_or_verified_this_call" for i in assets))
        caller = next(i for i in assets if "recorded_locator" in i["location"])
        self.assertNotIn("path", caller["location"])
        self.assertIn("supply location explicitly", caller["location"]["status"])


if __name__ == "__main__":
    unittest.main()
