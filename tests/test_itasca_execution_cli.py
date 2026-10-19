"""Public CLI recovery and output protections for external execution observations."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import _record, _sha256_json
from providers.execution import DisabledExecutionProvider
from research_project import enable_research

REPO = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("itasca_demo", REPO / "examples/itasca_execution/demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class ItascaExecutionCliTests(unittest.TestCase):
    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
                                 *map(str, args)], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_public_example_recovers_run_outputs_and_comparison_without_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "study with spaces"
            result = demo.run_demo(root)
            self.assertFalse(result["engine_called"])
            self.assertTrue(result["fresh_process_recovery_after_inputs_and_outputs_move"])
            self.assertTrue(result["ledger_unchanged_during_recovery"])
            self.assertEqual("completed", result["status"])
            self.assertFalse((root / "inputs").exists())
            self.assertFalse((root / "outputs").exists())
            report = (root / "reports/execution.md").read_text(encoding="utf-8")
            self.assertIn("synthetic", report)
            self.assertIn("engineering", report)
            self.assertIn("Recorded output evidence", report)
            records = [r for tx in ResearchStore(root).list_transactions() for r in tx["records"]]
            self.assertFalse(any(r["type"] == "Verification" for r in records))
            self.assertFalse(DisabledExecutionProvider().capability()["available"])
            rows, offset = [], 0
            while True:
                context = self.cli("project-context", "--project-root", root, "--offset", offset)
                rows.extend(context["items"])
                offset = context["page"]["next_offset"]
                if offset is None:
                    break
            navigation = next(row for row in rows if row["kind"] == "external_run")
            self.assertIn("itasca-run-progress", navigation["progress_argv"])
            entry = root / "START.md"
            entry.write_text("# User entry\n", encoding="utf-8")
            before = ResearchStore(root).list_transactions()
            self.cli("itasca-run-report", "--project-root", root, "--run-id", "teaching",
                     "--output", "START.md", expected=2)
            self.assertEqual("# User entry\n", entry.read_text(encoding="utf-8"))
            self.assertEqual(before, ResearchStore(root).list_transactions())
            # A generated Markdown view may later be registered as an output;
            # its marker must not allow replacing that captured material.
            store = ResearchStore(root)
            material = _record("Asset", "captured.execution.report", store.project_id,
                ["fixture:registered-output"], asset_kind="itasca_output", authority="derived", status="observed",
                locator={"path": "record:captured.execution.report#payload", "path_kind": "record_embedded"},
                content_sha256=_sha256_json({"path": "reports/execution.md"}), payload={"path": "reports/execution.md"})
            store.commit("register.report.output", {"role": "host", "model": "test"}, [material])
            saved_report = (root / "reports/execution.md").read_bytes()
            self.assertIn("registered material", self.cli("itasca-run-report", "--project-root", root,
                "--run-id", "teaching", "--output", "reports/execution.md", expected=2)["error"])
            self.assertEqual(saved_report, (root / "reports/execution.md").read_bytes())

    def test_oversized_and_nonfinite_plan_json_create_no_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            enable_research(root, "itasca.invalid.cli")
            script = root / "probe.py"
            script.write_text("print('no engine')\n", encoding="utf-8")
            metadata = root / "plan.json"
            metadata.write_bytes(b" " * (64 * 1024 + 1))
            result = self.cli("itasca-run-prepare", "--project-root", root, "--run-id", "bad",
                "--script", "probe.py", "--metadata-file", metadata, expected=2)
            self.assertIn("exceeds", result["error"])
            metadata.write_text('{"software": NaN}', encoding="utf-8")
            self.assertIn("JSON number", self.cli("itasca-run-prepare", "--project-root", root,
                "--run-id", "bad", "--script", "probe.py", "--metadata-file", metadata, expected=2)["error"])
            self.assertEqual([], ResearchStore(root).list_transactions())


if __name__ == "__main__":
    unittest.main()
