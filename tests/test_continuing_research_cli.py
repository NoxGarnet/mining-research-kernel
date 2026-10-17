"""Continue a question and regenerate a report from separate CLI processes."""
from __future__ import annotations

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


class ContinuingResearchCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="continuing-cli-", dir=REPO / "tests")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "研究 study"
        self.project.mkdir()
        self.entry = self.project / "START.md"
        self.entry.write_text("# Existing question\nUser decides the delivery and next action.\n", encoding="utf-8")
        enable_research(self.project, "continuing-cli-study")
        self.sources = [self.paper(1), self.paper(2)]

    def cli(self, *args, expected=0, markdown=False):
        run = subprocess.run([sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *args],
            cwd=self.project, capture_output=True, text=True, encoding="utf-8", timeout=45,
            env={**os.environ, "TEMP": self.temp.name, "TMP": self.temp.name, "TMPDIR": self.temp.name})
        self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
        return run.stdout if markdown else json.loads(run.stdout)

    def paper(self, number, *, more=False):
        value = capture()
        value["item"]["key"] = f"PAPER00{number}"
        value["item"]["title"] = f"Authored synthetic study {number}"
        value["pages"][0]["attachment_key"] = f"ATTACH0{number}"
        if more:
            value["pages"][0]["end_page"] = 14
        result = record_zotero_reading(self.project, task_id=f"paper-{number}" + ("-more" if more else ""),
            question="Read selected synthetic pages", capture=value, task_context="synthetic")
        return result["task_packet"]["asset_refs"][0]

    def review(self, started, *, second=False):
        value = started["comparison_template"]
        value["summary"] = "Additional selected reading describes a synthetic method." if second else "The initial selected readings leave the method unknown."
        value["next"] = "The user chooses whether another reading is needed."
        if second:
            row = value["sources"][1]
            source = next(item for item in started["sources"] if item["asset_ref"] == row["asset_ref"])
            row["dimensions"]["methods"] = {
                "status": "reported", "value": "An authored synthetic method for acceptance.",
                "interpretation": "A provisional reading, with scientific validity unchecked.",
                "citations": [{"evidence_id": source["evidence_refs"][0], "attachment_key": "ATTACH02",
                               "page_range": {"start_page": 14, "end_page": 14}}],
            }
        path = self.project / (started["task_id"] + ".json")
        path.write_text(json.dumps(value), encoding="utf-8")
        receipt = self.cli("literature-review", "--project-root", str(self.project), "--task-id", started["task_id"],
            "--operation-id", started["task_id"] + ".review", "--comparison-file", str(path))
        return receipt

    def test_two_steps_reports_pending_head_and_preserves_prior_records(self):
        original = self.entry.read_bytes()
        first = self.cli("research-begin", "--project-root", str(self.project), "--task-id", "step-01",
            "--question", "Which method is reported within the saved reading scope?",
            "--asset-ref", self.sources[0], "--asset-ref", self.sources[1],
            "--dimension", "conditions", "--dimension", "methods", "--task-context", "synthetic")
        self.assertEqual("step-01", first["task_packet"]["task_id"])
        self.assertEqual(first["question_id"], first["task_packet"]["input"]["research_question_id"])
        first_review = self.review(first)
        self.assertEqual("INSUFFICIENT", first_review["research_judgment_status"])
        before = {p.name: p.read_bytes() for p in (self.project / "research/records").glob("*.json")}
        extra = self.paper(2, more=True)
        args = ["research-continue", "--project-root", str(self.project), "--from-task", "step-01", "--task-id", "step-02",
                "--asset-ref", self.sources[0], "--asset-ref", extra, "--reason", "Read the methods page missing from the first step."]
        second = self.cli(*args)
        self.assertEqual(first["question_id"], second["question_id"])
        self.assertFalse(second["source_queries_performed"])
        pending = self.cli("research-report", "--project-root", str(self.project), "--task-id", "step-02", markdown=True)
        self.assertIn("The initial selected readings leave the method unknown.", pending)
        second_review = self.review(second, second=True)
        self.assertEqual("PROVISIONAL_WITH_GAPS", second_review["research_judgment_status"])
        progress = self.cli("research-progress", "--project-root", str(self.project), "--task-id", "step-02")
        self.assertEqual(["step-01", "step-02"], [item["task_id"] for item in progress["steps"]])
        self.assertEqual(first["question_id"], progress["question_id"])
        report_args = ["research-report", "--project-root", str(self.project), "--task-id", "step-02"]
        report = self.cli(*report_args, markdown=True)
        self.assertIn("Additional selected reading describes a synthetic method.", report)
        self.assertIn("ATTACH02", report)
        self.assertIn("14", report)
        exported = self.cli(*report_args, "--output", "results/research.md")
        self.assertEqual("derived", exported["authority"])
        content = (self.project / exported["output"]).read_bytes()
        count = len(list((self.project / "research/records").glob("*.json")))
        self.assertEqual(exported["sha256"], self.cli(*report_args, "--output", "results/research.md")["sha256"])
        self.assertEqual(content, (self.project / exported["output"]).read_bytes())
        self.assertEqual(count, len(list((self.project / "research/records").glob("*.json"))))
        self.assertTrue(self.cli(*args)["replayed"])
        self.assertEqual("completed", self.cli(*args)["state"])
        for name, raw in before.items():
            self.assertEqual(raw, (self.project / "research/records" / name).read_bytes())
        self.assertEqual(original, self.entry.read_bytes())
        self.assertFalse((self.project / "runs").exists())

    def test_report_writer_preserves_inputs_and_registered_views(self):
        from mining_kernel import _write_research_report
        original = self.entry.read_bytes()
        for output in ("START.md", "research/records/new.md", "Research/Records/new.md", "../outside.md"):
            with self.assertRaises(ValueError):
                _write_research_report(self.project, "task-01", output, "# Generated report\n")
        note = self.project / "notes.md"
        note.write_text("Original user note\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not this task"):
            _write_research_report(self.project, "task-01", "notes.md", "# Generated report\n")
        _write_research_report(self.project, "task-01", "report.md", "# Generated report\n")
        self.cli("register-local-material", "--project-root", str(self.project), "report.md", "--material-kind", "derived_reading_note")
        with self.assertRaisesRegex(ValueError, "registered material"):
            _write_research_report(self.project, "task-01", "report.md", "# Changed report\n")
        self.assertEqual("Original user note\n", note.read_text(encoding="utf-8"))
        self.assertEqual(original, self.entry.read_bytes())


if __name__ == "__main__":
    unittest.main()
