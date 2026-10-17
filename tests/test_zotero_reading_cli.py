"""CLI integration for explicit capture import and cross-process recovery."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


class ZoteroReadingCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zotero-cli-", dir=REPO / "tests")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project = self.base / "文献 study"
        self.project.mkdir()
        self.entry = self.project / "START.md"
        self.entry.write_text("# User-chosen study\n", encoding="utf-8")
        self.capture = json.loads((REPO / "examples/zotero_reading/capture.synthetic.json").read_text(encoding="utf-8"))
        self.capture_file = self.base / "capture.json"
        self.save()

    def save(self):
        self.capture_file.write_text(json.dumps(self.capture), encoding="utf-8")

    def cli(self, *args, expected=0):
        env = {**os.environ, "TEMP": str(self.base), "TMP": str(self.base), "TMPDIR": str(self.base)}
        run = subprocess.run([sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *args],
                             cwd=self.base, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(expected, run.returncode, run.stdout + run.stderr)
        return json.loads(run.stdout)

    def enable(self):
        self.cli("enable-research", "--project-root", str(self.project), "--project-id", "reading-study")

    def record(self, *extra, expected=0):
        return self.cli("zotero-record", "--project-root", str(self.project), "--task-id", "reading-01",
                        "--question", "What does the selected page describe?", "--capture", str(self.capture_file),
                        "--task-context", "synthetic", *extra, expected=expected)

    def test_import_replay_and_recover_without_capture_or_source(self):
        before = self.entry.read_bytes()
        validated = self.cli("validate-zotero-reading", str(self.capture_file))
        self.assertTrue(validated["valid"])
        self.assertFalse((self.project / "research").exists())
        self.enable()
        finding = [{"statement": "Fabricated matching conditions.", "citation": {
            "attachment_key": "ATTACH01", "start_page": 1, "end_page": 1}}]
        receipt = self.record("--findings-json", json.dumps(finding))
        self.assertEqual("ZoteroReadingRecordReceipt", receipt["type"])
        self.assertFalse(receipt["query_performed"])
        self.assertFalse(receipt["source_revalidated"])
        self.assertFalse(receipt["replayed"])
        self.assertEqual("READ_WITH_FINDINGS", receipt["reading_status"])
        self.assertLess(len(json.dumps(receipt)), 4000)
        replay = self.record("--findings-json", json.dumps(finding))
        self.assertTrue(replay["replayed"])
        self.capture_file.unlink()
        recovered = self.cli("resume", "--project-root", str(self.project), "--task", "reading-01")
        self.assertIn("reading-01", json.dumps(recovered))
        payload = self.cli("show", "--project-root", str(self.project), "--record-id", receipt["asset_refs"][0],
                           "--section", "payload")
        self.assertIn("ATTACH01", json.dumps(payload))
        self.assertEqual(before, self.entry.read_bytes())
        self.assertFalse((self.project / "runs").exists())

    def test_invalid_or_synthetic_production_capture_writes_no_records(self):
        self.enable()
        bad = copy.deepcopy(self.capture)
        bad["credential"] = "must be rejected"
        self.capture_file.write_text(json.dumps(bad), encoding="utf-8")
        self.cli("validate-zotero-reading", str(self.capture_file), expected=2)
        self.assertFalse((self.project / "research").exists())
        self.save()
        self.cli("zotero-record", "--project-root", str(self.project), "--task-id", "bad-context",
                 "--question", "q", "--capture", str(self.capture_file), expected=2)
        self.assertFalse((self.project / "research").exists())

    def test_failed_capture_is_recorded_but_exit_is_not_success(self):
        self.enable()
        self.capture["metadata_status"] = "unavailable"
        self.capture["item"].update({"title": "", "item_type": "", "version": None})
        self.capture["pages"] = []
        self.capture["diagnostics"] = [{"code": "source_unavailable", "message": "Source could not be read."}]
        self.save()
        receipt = self.record(expected=2)
        self.assertEqual("INSUFFICIENT", receipt["research_judgment_status"])
        self.assertEqual([], receipt["page_ranges_read"])
        self.assertIn("reading-01", json.dumps(self.cli("resume", "--project-root", str(self.project),
                                                       "--task", "reading-01")))


if __name__ == "__main__":
    unittest.main()
