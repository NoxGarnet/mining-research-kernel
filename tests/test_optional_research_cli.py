"""Exercise opt-in, material review, and documentation records as CLI clients."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from test_r1_documentation import html_page, PAGE


REPO = Path(__file__).resolve().parents[1]


class OptionalResearchCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=REPO)
        self.base = Path(self.temp.name)
        self.project = self.base / "已有项目 with spaces"
        self.project.mkdir()
        self.entry = self.project / "START.md"
        self.entry.write_text("# Existing question\nKeep the existing entry.\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args, expected=0):
        env = {**os.environ, "TEMP": str(self.base), "TMP": str(self.base),
               "TMPDIR": str(self.base)}
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), *args],
            cwd=self.base, env=env, capture_output=True, text=True, encoding="utf-8",
        )
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def enable(self):
        return self.cli("enable-research", "--project-root", str(self.project),
                        "--project-id", "existing-study")

    def registration(self):
        source = self.base / "source"
        page = source / PAGE
        page.parent.mkdir(parents=True)
        body = html_page()
        page.write_bytes(body)
        registration = self.base / "registration.json"
        registration.write_text(json.dumps({
            "schema_version": 1, "source_id": "example.docs.synthetic",
            "root": str(source), "product": "flac3d", "document_family": "9.6",
            "document_build": "9.6.44", "trust_class": "synthetic",
            "product_subdir": "flac3d", "pages": {PAGE: hashlib.sha256(body).hexdigest()},
        }), encoding="utf-8")
        return registration, page

    def test_plain_material_review_and_recovery_without_flac_config(self):
        source = self.project / "observation.txt"
        source.write_text("A bounded, fabricated observation.\n", encoding="utf-8")
        original = {p.name: p.read_bytes() for p in (self.entry, source)}
        self.assertEqual("enabled", self.enable()["status"])
        self.assertFalse((self.project / "research").exists())
        registered = self.cli("register-local-material", "--project-root", str(self.project),
                              "observation.txt", "--material-kind", "project_record")
        request = {
            "task_id": "plain-review", "question_statement": "What does the observation say?",
            "claim_statement": "The supplied file contains the observation.",
            "asset_refs": [registered["asset"]["id"]],
            "evidence_refs": [registered["evidence"]["id"]],
        }
        packet = self.cli("task-start", "--project-root", str(self.project),
                          "--request-json", json.dumps(request))
        self.assertEqual("mining_research_kernel.workflow.research", packet["workflow_id"])
        self.assertEqual("ready", packet["state"])
        assessment = {
            "scope": "material_reading_and_evidence_synthesis_only",
            "material_reads": [{
                "asset_id": item["asset_id"], "evidence_refs": item["evidence_refs"],
                "observed_sha256": item["content_sha256"], "reading_status": "READ_WITH_LIMITS",
                "verification_status": "NOT_VERIFIED", "locator": {"kind": "line", "value": "1"},
                "summary": "Read the fabricated observation.",
                "numeric_check_status": "NOT_APPLICABLE",
                "scientific_validation_status": "NOT_VERIFIED", "gaps": [],
            } for item in packet["material_reads"]],
            "material_gaps": [],
            "judgment": {"status": "PROVISIONAL_WITH_GAPS", "summary": "Observation recovered.",
                         "gaps": ["No scientific validation."],
                         "next_action": {"action": "Await the user's next question.", "executable": False}},
        }
        review = self.cli("task-record-evidence-review", "--project-root", str(self.project),
                          "plain-review", "--operation-id", "record-review",
                          "--assessment-json", json.dumps(assessment))
        self.assertEqual("completed", review["state"])
        resumed = self.cli("resume", "--project-root", str(self.project), "--task", "plain-review")
        self.assertIn("Observation recovered.", json.dumps(resumed))
        self.assertFalse((self.project / "flac3d_project.yaml").exists())
        self.assertFalse((self.project / "cases").exists())
        self.assertEqual(original, {p.name: p.read_bytes() for p in (self.entry, source)})

    def test_documentation_check_is_read_only_and_record_is_explicit(self):
        registration, page = self.registration()
        args = ["--registration", str(registration), "--page", PAGE,
                "--command", "zone list", "--product", "flac3d",
                "--product-version", "9.6", "--task-context", "synthetic"]
        before = self.entry.read_bytes(), page.read_bytes()
        checked = self.cli("documentation-check", *args)
        self.assertEqual("SYNTHETIC_VERIFIED", checked["status"])
        self.assertEqual(["START.md"], sorted(p.name for p in self.project.iterdir()))
        record = ["documentation-record", "--project-root", str(self.project),
                  "--task-id", "document-query", "--question", "Is zone list documented?", *args]
        self.cli(*record, expected=2)
        self.assertFalse((self.project / "research").exists())
        self.enable()
        recorded = self.cli(*record)
        self.assertEqual("DocumentationRecordReceipt", recorded["type"])
        self.assertNotIn("transaction", recorded)
        self.assertNotIn("task_packet", recorded)
        self.assertLess(len(json.dumps(recorded, ensure_ascii=False, indent=2)), 4000)
        self.assertEqual("SYNTHETIC_VERIFIED", recorded["documentation_result"]["status"])
        self.assertFalse(recorded["replayed"])
        replay = self.cli(*record)
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["query_performed"])
        resumed = self.cli("resume", "--project-root", str(self.project), "--task", "document-query")
        self.assertIn("command", json.dumps(resumed).lower())
        failed = self.cli("documentation-record", "--project-root", str(self.project),
                          "--task-id", "wrong-version", "--question", "Check a mismatched version.",
                          *["9.0" if part == "9.6" else part for part in args], expected=2)
        self.assertEqual("CANNOT_VERIFY", failed["documentation_result"]["status"])
        self.cli("resume", "--project-root", str(self.project), "--task", "wrong-version")
        self.assertEqual(before, (self.entry.read_bytes(), page.read_bytes()))

    def test_recorded_snapshot_can_feed_another_task_without_the_original_page(self):
        registration, page = self.registration()
        self.enable()
        recorded = self.cli(
            "documentation-record", "--project-root", str(self.project),
            "--task-id", "first-query", "--question", "Is zone list documented?",
            "--registration", str(registration), "--page", PAGE, "--command", "zone list",
            "--product", "flac3d", "--product-version", "9.6", "--task-context", "synthetic",
        )
        page.unlink()
        request = {
            "task_id": "follow-up", "question_statement": "What can the saved observation support?",
            "claim_statement": "The saved observation has limited historical scope.",
            "asset_refs": recorded["asset_refs"],
            "evidence_refs": recorded["evidence_refs"],
            "refs": {"decisions": [recorded["decision_id"]]},
        }
        packet = self.cli("task-start", "--project-root", str(self.project),
                          "--request-json", json.dumps(request))
        self.assertEqual("ready", packet["state"])
        self.assertEqual("recorded_snapshot_hash_match", packet["material_reads"][0]["content_status"])
        self.assertEqual("NOT_READ", packet["material_reads"][0]["reading_status"])
        self.assertIn("recorded_snapshot_original_not_revalidated",
                      [gap["reason"] for gap in packet["material_gaps"]])
        self.assertFalse(packet["execution_authorized"])


if __name__ == "__main__":
    unittest.main()
