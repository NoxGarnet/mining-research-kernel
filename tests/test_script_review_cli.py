"""Process-boundary tests for script review, recovery and protected export."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mining_research_kernel.documentation_reading import record_documentation_reading
from mining_research_kernel.project_context import project_context
from mining_research_kernel.records import ResearchStore
from research_project import enable_research

REPO = Path(__file__).resolve().parents[1]
PAGE = "flac3d/teaching.html"


class ScriptReviewCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project with spaces"
        self.root.mkdir()
        enable_research(self.root, "script.cli.test")
        (self.root / "START.md").write_text("# Project entry\n", encoding="utf-8")
        self.script = self.root / "model.dat"
        self.script.write_text("; authored test input\n; no solver\nzone cmodel assign elastic\n", encoding="utf-8")
        self.original = self.script.read_bytes()
        self.document = self.base / "docs" / PAGE
        self.document.parent.mkdir(parents=True)
        self.document.write_text('<html><head><title>Synthetic fixture: Itasca Software 9.6 documentation</title>'
                                 "<script>DOCUMENTATION_OPTIONS = {VERSION: '9.6.44'};</script></head>"
                                 '<body><main><section id="elastic"><h1>Teaching text</h1>'
                                 '<p>Synthetic passage describing zone cmodel assign elastic.</p>'
                                 '</section></main></body></html>', encoding="utf-8")
        self.registration = self.base / "registration.json"
        self.registration.write_text(json.dumps({
            "schema_version": 1, "source_id": "synthetic.script.cli", "root": str(self.base / "docs"),
            "product": "flac3d", "document_family": "9.6", "document_build": "9.6.44",
            "trust_class": "synthetic", "product_subdir": "flac3d",
            "pages": {PAGE: hashlib.sha256(self.document.read_bytes()).hexdigest()},
        }), encoding="utf-8")
        reading = record_documentation_reading(
            self.root, task_id="manual", question="Read synthetic passage", registration=self.registration,
            page=PAGE, anchor="elastic", product="flac3d", product_version="9.6.44", task_context="synthetic")
        self.doc_packet = reading["task_packet"]
        self.assertEqual("READ_WITH_LIMITS", reading["documentation_result"]["status"], reading["documentation_result"])

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
                                 *args, "--project-root", str(self.root)], capture_output=True,
                                text=True, encoding="utf-8", cwd=self.base)
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def start(self, **kwargs):
        return json.loads(self.cli("script-review-start", "--task-id", "review", "--question", "Compare saved lines",
            "--script", "model.dat", "--start-line", str(kwargs.get("start_line", 3)), "--end-line", "3",
            "--product-version", "9.6.44", "--documentation-asset-ref", self.doc_packet["asset_refs"][0],
            "--task-context", "synthetic", expected=kwargs.get("expected", 0)))

    def test_all_commands_fresh_process_recovery_and_protected_report(self):
        started = self.start()
        self.assertEqual("review", started["task_packet"]["task_id"])
        review_file = self.base / "authored review.json"
        review_file.write_text(json.dumps({
            "summary": "A bounded authored interpretation.",
            "findings": [{"start_line": 3, "end_line": 3, "statement": "Selected line uses elastic assignment.",
                          "documentation_evidence_refs": self.doc_packet["evidence_refs"]}],
            "gaps": ["Synthetic teaching source; parameters and context unverified."],
            "next_action": "User decides whether to read official sources next.",
        }), encoding="utf-8")
        recorded = json.loads(self.cli("script-review-record", "--task-id", "review", "--operation-id", "note",
                                        "--review-file", str(review_file)))
        self.assertEqual("completed", recorded["task_packet"]["state"])
        self.assertEqual(self.original, self.script.read_bytes())
        before = {p.name: p.read_bytes() for p in (self.root / "research/records").glob("*.json")}
        self.script.unlink()
        self.document.unlink()
        progress = self.cli("script-review-progress", "--task-id", "review")
        self.assertIn("zone cmodel assign elastic", progress)
        self.assertIn("A bounded authored interpretation", progress)
        report = self.cli("script-review-report", "--task-id", "review")
        self.assertIn("Selected line uses elastic assignment", report)
        self.assertIn(hashlib.sha256(self.original).hexdigest(), report)
        output = json.loads(self.cli("script-review-report", "--task-id", "review", "--output", "reports/review.md"))
        self.assertEqual("reports/review.md", output["output"])
        self.cli("script-review-report", "--task-id", "review", "--output", "START.md", expected=2)
        self.assertEqual("# Project entry\n", (self.root / "START.md").read_text(encoding="utf-8"))
        self.assertTrue(self.start()["replayed"])
        after = {p.name: p.read_bytes() for p in (self.root / "research/records").glob("*.json")}
        self.assertEqual(before, after)
        types = {record["type"] for tx in ResearchStore(self.root).list_transactions() for record in tx["records"]}
        self.assertTrue(types.isdisjoint({"Run", "RunReference", "Verification"}))
        items, offset = [], 0
        while True:
            context = project_context(self.root, offset=offset)
            items.extend(context["items"])
            offset = context["page"]["next_offset"]
            if offset is None:
                break
        row = next(item for item in items if item["kind"] == "task" and item["id"] == "review")
        self.assertIn("script-review-progress", row["script_review_progress_argv"])
        self.assertIn("script-review-report", row["script_review_report_argv"])
        self.assertNotIn("research_progress_argv", row)

    def test_rejects_invalid_line_window_without_creating_task(self):
        before = ResearchStore(self.root).list_transactions()
        self.start(start_line=0, expected=2)
        self.assertEqual(before, ResearchStore(self.root).list_transactions())
        self.assertEqual(self.original, self.script.read_bytes())

    def test_offline_example_uses_only_standard_library_and_preserves_existing_directory(self):
        output = self.base / "independent demo"
        args = [sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "examples/script_review/demo.py"), str(output)]
        result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", cwd=self.base)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["synthetic"])
        self.assertTrue(receipt["fresh_process_recovery"])
        self.assertTrue(receipt["source_unchanged"])
        before = {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()}
        repeated = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", cwd=self.base)
        self.assertEqual(2, repeated.returncode)
        self.assertEqual(before, {p.relative_to(output).as_posix(): p.read_bytes() for p in output.rglob("*") if p.is_file()})

    def test_source_change_at_commit_cannot_change_review_provenance(self):
        from mining_research_kernel.script_review import record_script_review
        self.start()
        store = ResearchStore(self.root)
        asset_id = self.doc_packet["asset_refs"][0]
        original_commit = ResearchStore.commit
        injected = False

        def race_commit(selected_store, operation_id, *args, **kwargs):
            nonlocal injected
            if operation_id == "race-note" and not injected:
                injected = True
                changed = store.latest_record(asset_id, "Asset")
                old_revision = changed["revision"]
                changed["revision"] += 1
                changed["status"] = "changed_after_source_validation"
                original_commit(store, "concurrent-source-update", {"role": "test", "model": "race"},
                                [changed], expected_revisions={asset_id: old_revision})
            return original_commit(selected_store, operation_id, *args, **kwargs)

        review = {"summary": "This review must not commit with changed provenance.",
                  "findings": [{"start_line": 3, "end_line": 3, "statement": "A bounded observation.",
                                "documentation_evidence_refs": self.doc_packet["evidence_refs"]}],
                  "gaps": ["Synthetic source; semantics unverified."], "next_action": "User chooses the next scope."}
        with patch.object(ResearchStore, "commit", race_commit):
            with self.assertRaisesRegex(ValueError, "revision"):
                record_script_review(self.root, task_id="review", operation_id="race-note", review=review)
        self.assertTrue(injected)
        state = store.latest_record("review", "TaskState")
        self.assertEqual("ready", state["state"])
        self.assertNotIn("race-note", state.get("operation_results", {}))
        self.assertEqual(self.original, self.script.read_bytes())

    def test_source_change_at_start_commit_does_not_create_a_task(self):
        from mining_research_kernel.script_review import start_script_review
        store = ResearchStore(self.root)
        asset_id = self.doc_packet["asset_refs"][0]
        original_commit = ResearchStore.commit
        injected = False

        def race_commit(selected_store, operation_id, *args, **kwargs):
            nonlocal injected
            if operation_id == "task-start.review" and not injected:
                injected = True
                changed = store.latest_record(asset_id, "Asset")
                old_revision = changed["revision"]
                changed["revision"] += 1
                changed["status"] = "changed_during_start"
                original_commit(store, "concurrent-start-update", {"role": "test", "model": "race"},
                                [changed], expected_revisions={asset_id: old_revision})
            return original_commit(selected_store, operation_id, *args, **kwargs)

        with patch.object(ResearchStore, "commit", race_commit):
            with self.assertRaisesRegex(ValueError, "revision"):
                start_script_review(self.root, task_id="review", question="Compare saved lines", script="model.dat",
                                    start_line=3, end_line=3, product_version="9.6.44",
                                    documentation_asset_refs=[asset_id], task_context="synthetic")
        self.assertTrue(injected)
        self.assertIsNone(store.latest_record("review", "TaskState"))
        self.assertEqual(self.original, self.script.read_bytes())

    def test_project_relative_review_replays_after_relocation_without_rereading(self):
        from mining_research_kernel.script_review import start_script_review
        original = self.start()
        relocated = self.base / "relocated project"
        shutil.copytree(self.root, relocated)
        before = {p.name: p.read_bytes() for p in (relocated / "research/records").glob("*.json")}
        with patch("mining_research_kernel.script_review._read_script", side_effect=AssertionError("must not reread")):
            replay = start_script_review(relocated, task_id="review", question="Compare saved lines",
                script="model.dat", start_line=3, end_line=3, product_version="9.6.44",
                documentation_asset_refs=self.doc_packet["asset_refs"], task_context="synthetic")
        self.assertTrue(replay["replayed"])
        self.assertEqual(original["script_snapshot"], replay["script_snapshot"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in (relocated / "research/records").glob("*.json")})


if __name__ == "__main__":
    unittest.main()
