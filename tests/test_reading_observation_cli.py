from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.research_continuation import begin_research, continue_research
from mining_research_kernel.research_report import render_research_report
from mining_research_kernel.source_review import record_source_review
from mining_research_kernel.reading_observation import record_reading_observation
from mining_research_kernel.r2_workflow import _sha256_json
from research_project import enable_research

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reading_demo", REPO / "examples/reading_observations/demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class ReadingObservationCliTests(unittest.TestCase):
    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
                                 *map(str, args)], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_standard_library_demo_continues_and_recovers_without_import_files(self):
        with tempfile.TemporaryDirectory(dir=REPO.parent) as directory:
            root = Path(directory) / "study with spaces"
            result = demo.run_demo(root)
            self.assertEqual(2, result["steps"])
            self.assertTrue(result["historical_report_unchanged"])
            report = (root / result["report"]).read_text(encoding="utf-8")
            self.assertIn("teaching-b", report)
            self.assertIn("Methods", report)
            self.assertIn("来源版本未知", report)
            self.assertIn("offline teaching fixture", report)
            self.assertIn("覆盖从", report)
            records = [r for tx in ResearchStore(root).list_transactions() for r in tx["records"]]
            self.assertEqual(1, sum(r["type"] == "ResearchQuestion" for r in records))
            self.assertFalse(any(r["type"] in {"Run", "RunReference", "Verification"} for r in records))

    def test_unavailable_observation_is_saved_but_cannot_supply_a_narrative_citation(self):
        with tempfile.TemporaryDirectory(dir=REPO.parent) as directory:
            root = Path(directory)
            enable_research(root, "unavailable-reading")
            data = demo.observation("teaching-b")
            data["passages"][0].update(status="unavailable", text_sha256=None, excerpt="")
            path = root / "observation.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            receipt = self.cli("reading-record", "--project-root", root, "--observation-id", "failed-read",
                               "--observation", path, "--task-context", "synthetic", expected=2)
            self.assertEqual("UNAVAILABLE", receipt["reading_status"])
            start = begin_research(root, task_id="failed-analysis", question="What can the failed reading establish?",
                                   asset_refs=[receipt["asset_ref"]], mode="sources", task_context="synthetic")
            eid = start["task_packet"]["evidence_refs"][0]
            with self.assertRaises(ValueError):
                record_source_review(root, task_id="failed-analysis", operation_id="false-support",
                    note="## Summary\nClaim.\n\n## Findings\n- Claim. [evidence:" + eid +
                         "]\n\n## Gaps\nUnavailable reading.\n\n## Next\nWait for a successful read.\n")
            self.assertFalse(any(r["type"] == "Decision" for tx in ResearchStore(root).list_transactions()
                                 for r in tx["records"]))

    def test_cli_rejects_bad_types_and_oversized_import_without_records(self):
        with tempfile.TemporaryDirectory(dir=REPO.parent) as directory:
            root = Path(directory)
            enable_research(root, "invalid-reading")
            path = root / "observation.json"
            data = demo.observation("teaching-a")
            data["origin"] = []
            path.write_text(json.dumps(data), encoding="utf-8")
            self.assertIn("error", self.cli("validate-reading-observation", path, expected=2))
            path.write_bytes(b" " * (256 * 1024 + 1))
            self.assertIn("256 KiB", self.cli("reading-record", "--project-root", root,
                "--observation-id", "too-large", "--observation", path, expected=2)["error"])
            self.assertEqual([], ResearchStore(root).list_transactions())

    def test_narrative_continuation_report_uses_pinned_generic_source_history(self):
        with tempfile.TemporaryDirectory(dir=REPO.parent) as directory:
            root = Path(directory)
            enable_research(root, "narrative-reading")
            capture = demo.observation("teaching-a")
            ref = record_reading_observation(root, observation_id="a", observation=capture, task_context="synthetic")
            first = begin_research(root, task_id="first", question="What is reported?", asset_refs=[ref["asset_ref"]],
                                   mode="sources", task_context="synthetic")
            eid = ref["evidence_ref"]
            note = ("## Summary\nThe teaching observation reports laboratory inputs.\n\n## Findings\n"
                    "- The observation attributes inputs to measurements. [evidence:" + eid + "]\n\n"
                    "## Gaps\nSynthetic scope only.\n\n## Next\nThe user decides whether to read further.\n")
            record_source_review(root, task_id="first", operation_id="first-review", note=note)
            second = continue_research(root, task_id="second", from_task_id="first")
            self.assertEqual(first["question_id"], second["question_id"])
            record_source_review(root, task_id="second", operation_id="second-review", note=note)
            old_report = render_research_report(root, task_id="second")
            self.assertIn("Teaching paper teaching-a", old_report)
            store = ResearchStore(root)
            asset = copy.deepcopy(store.latest_record(ref["asset_ref"], "Asset"))
            asset["revision"] += 1
            asset["payload"]["request"]["observation"]["source"]["title"] = "Later source title"
            asset["payload"]["provenance"]["request_sha256"] = _sha256_json(asset["payload"]["request"])
            asset["content_sha256"] = _sha256_json(asset["payload"])
            store.commit("later-source-revision", {"role": "host", "model": "test"}, [asset])
            self.assertEqual(old_report, render_research_report(root, task_id="second"))


if __name__ == "__main__":
    unittest.main()
