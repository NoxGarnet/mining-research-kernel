"""Exercise the new reading/comparison entries across separate CLI processes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mining_research_kernel.zotero_records import record_zotero_reading
from research_project import enable_research
from tests.test_zotero_records import capture

REPO = Path(__file__).resolve().parents[1]
PAGE = "flac3d/zone/doc/manual/zone_commands/itasca_reading_fixture.html"


class ReadingComparisonCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="reading-cli-", dir=REPO / "tests")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "研究 study"
        self.project.mkdir()
        self.entry = self.project / "START.md"
        self.entry.write_text("# Existing project\nUser chooses the next action.\n", encoding="utf-8")
        enable_research(self.project, "reading-cli-study")
        self.page = self.base / "docs" / PAGE
        self.page.parent.mkdir(parents=True)
        self.page.write_bytes((REPO / "tests/fixtures/itasca_manual.html").read_bytes())
        self.registration = self.base / "host-docs.json"
        self.registration.write_text(json.dumps({
            "schema_version": 1, "source_id": "synthetic.docs.local", "root": str(self.base / "docs"),
            "product": "flac3d", "document_family": "9.6", "document_build": "9.6.44",
            "trust_class": "synthetic", "product_subdir": "flac3d",
            "pages": {PAGE: hashlib.sha256(self.page.read_bytes()).hexdigest()},
        }), encoding="utf-8")

    def cli(self, *args, expected=0):
        run = subprocess.run([sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *args],
            cwd=self.base, capture_output=True, text=True, encoding="utf-8", timeout=45,
            env={**os.environ, "TEMP": str(self.base), "TMP": str(self.base), "TMPDIR": str(self.base)})
        self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def documentation_args(self):
        return ["documentation-read", "--project-root", str(self.project), "--task-id", "passage-01",
                "--question", "What does the selected explanation say?", "--registration", str(self.registration),
                "--page", PAGE, "--anchor", "kwd:zone.cmodel.assign.elastic", "--product", "flac3d",
                "--product-version", "9.6.44", "--task-context", "synthetic"]

    def test_reading_receipt_replay_recovery_and_version_failure(self):
        original = self.entry.read_bytes()
        receipt = self.cli(*self.documentation_args())
        self.assertEqual("READ_WITH_LIMITS", receipt["documentation_result"]["status"])
        self.assertTrue(receipt["source_read_performed"])
        self.assertTrue(receipt["reading_texts"])
        self.assertFalse(receipt["run_created"])
        self.page.unlink()
        replay = self.cli(*self.documentation_args())
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["query_performed"])
        self.assertEqual([], replay["reading_texts"])
        resumed = self.cli("resume", "--project-root", str(self.project), "--task-id", "passage-01")
        self.assertIn("passage-01", json.dumps(resumed))
        failed_args = self.documentation_args()
        failed_args[failed_args.index("passage-01")] = "wrong-version"
        failed_args[failed_args.index("9.6.44")] = "9.0"
        failed = self.cli(*failed_args, expected=2)
        self.assertEqual("INSUFFICIENT", failed["research_judgment_status"])
        self.assertFalse(failed["source_read_performed"])
        self.assertEqual(original, self.entry.read_bytes())

    def test_comparison_template_writeback_and_resume(self):
        original = self.entry.read_bytes()
        selected = []
        for index in (1, 2):
            paper = capture()
            paper["item"]["key"] = f"PAPER00{index}"
            paper["pages"][0]["attachment_key"] = f"ATTACH0{index}"
            paper["item"]["title"] = f"Authored synthetic study {index}"
            result = record_zotero_reading(self.project, task_id=f"paper-{index}",
                question="Read selected pages", capture=paper, task_context="synthetic")
            selected.extend(result["task_packet"]["asset_refs"])
        args = ["literature-start", "--project-root", str(self.project), "--task-id", "comparison-01",
                "--question", "Which methods are stated in the selected pages?", "--dimension", "methods",
                "--task-context", "synthetic"]
        for aid in selected:
            args.extend(["--asset-ref", aid])
        started = self.cli(*args)
        wrong_note = self.base / "wrong-review.md"
        wrong_note.write_text("## Summary\nA generic note cannot replace a structured comparison.\n", encoding="utf-8")
        wrong = self.cli("research-review", "--project-root", str(self.project), "--task-id", "comparison-01",
                         "--operation-id", "wrong-review", "--review-file", str(wrong_note), expected=2)
        self.assertIn("literature-review", wrong["error"])
        comparison = started["comparison_template"]
        first = comparison["sources"][0]
        source = next(item for item in started["sources"] if item["asset_ref"] == first["asset_ref"])
        covered = source["coverage"]["read_page_ranges"][0]
        first["dimensions"]["methods"] = {
            "status": "reported", "value": "A synthetic method described for acceptance.",
            "interpretation": "Provisional reading; no scientific validation was performed.",
            "citations": [{"evidence_id": source["evidence_refs"][0],
                           "attachment_key": covered["attachment_key"],
                           "page_range": {"start_page": covered["start_page"], "end_page": covered["end_page"]}}],
        }
        comparison["summary"] = "One saved reading describes a method; the other remains unknown in this scope."
        comparison["next"] = "Consider further reading only if it addresses the user's chosen goal."
        path = self.base / "comparison.json"
        path.write_text(json.dumps(comparison, ensure_ascii=False), encoding="utf-8")
        review_args = ["literature-review", "--project-root", str(self.project), "--task-id", "comparison-01",
                       "--operation-id", "comparison-01.review-01", "--comparison-file", str(path)]
        receipt = self.cli(*review_args)
        self.assertEqual("PROVISIONAL_WITH_GAPS", receipt["research_judgment_status"])
        self.assertEqual(receipt["decision_id"], self.cli(*review_args)["decision_id"])
        self.assertEqual("completed", self.cli(*args)["state"])
        assessment = self.cli("show", "--project-root", str(self.project), "--record-id", receipt["decision_id"],
                              "--section", "assessment")
        self.assertIn("not_reported_in_read_scope", json.dumps(assessment))
        self.assertIn(comparison["summary"], json.dumps(assessment))
        self.assertIn("NOT_PERFORMED", json.dumps(assessment))
        self.assertIn("comparison-01", json.dumps(self.cli("resume", "--project-root", str(self.project),
                                                           "--task-id", "comparison-01")))
        self.assertFalse((self.project / "runs").exists())
        self.assertEqual(original, self.entry.read_bytes())

    def test_saved_excerpt_and_read_budget_have_distinct_truncation_flags(self):
        html = self.page.read_text(encoding="utf-8").replace(
            "Use the save command after establishing the model state.",
            "A bounded synthetic explanation. " * 150)
        self.page.write_text(html, encoding="utf-8")
        registration = json.loads(self.registration.read_text(encoding="utf-8"))
        registration["pages"][PAGE] = hashlib.sha256(self.page.read_bytes()).hexdigest()
        self.registration.write_text(json.dumps(registration), encoding="utf-8")
        args = self.documentation_args()
        args[args.index("passage-01")] = "bounded-passage"
        args[args.index("kwd:zone.cmodel.assign.elastic")] = "model-save"
        receipt = self.cli(*args, "--max-reading-chars", "3000")
        result = receipt["documentation_result"]
        self.assertTrue(result["reading_truncated"])
        self.assertTrue(result["saved_text_truncated"])
        self.assertEqual(3000, sum(len(item["text"]) for item in receipt["reading_texts"]))
        self.assertEqual(2000, sum(len(item["text"]) for item in result["passages"]))


if __name__ == "__main__":
    unittest.main()
