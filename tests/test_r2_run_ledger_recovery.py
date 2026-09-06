import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import run_ledger
from run_ledger import RunLedgerError, create_run, inspect_run, record_stage, validate_bundle


class R2RunLedgerRecoveryTests(unittest.TestCase):
    def test_new_manifest_and_legacy_boundary_roles(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_run(root, "roles")
            manifest = json.loads((root / "roles" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual("planning_agent", manifest["stages"]["exploration"]["role"])
            record_stage(root, "roles", "exploration", "sol", "completed", {}, model="m")
            attempt = json.loads((root / "roles" / "exploration.yaml").read_text(encoding="utf-8"))["attempts"][0]
            self.assertEqual("planning_agent", attempt["role"])
            manifest = json.loads((root / "roles" / "manifest.json").read_text(encoding="utf-8"))
            manifest["stages"]["plan"]["role"] = "sol"
            (root / "roles" / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual([], validate_bundle(root, "roles"))

    def test_second_writer_and_operation_replay(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_run(root, "locked")
            run_ledger._acquire_lock(root / "locked", "other")
            try:
                with self.assertRaises(RunLedgerError):
                    record_stage(root, "locked", "exploration", "sol", "completed", {}, model="m", operation_id="op")
            finally:
                run_ledger._release_lock(root / "locked", "other")
            first = record_stage(root, "locked", "exploration", "sol", "completed", {}, model="m", operation_id="op")
            second = record_stage(root, "locked", "exploration", "sol", "completed", {}, model="m", operation_id="op")
            self.assertEqual(first, second)
            attempts = json.loads((root / "locked" / "exploration.yaml").read_text(encoding="utf-8"))["attempts"]
            self.assertEqual(1, len(attempts))
            with self.assertRaises(RunLedgerError):
                record_stage(root, "locked", "exploration", "sol", "waiting_for_human", {"q": "different"}, model="m", operation_id="op")

    def test_interruption_is_recovered_by_new_process(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_run(root, "recover")
            def interrupt(point):
                self.assertEqual("after_stage", point)
                raise RuntimeError("injected interruption")
            with self.assertRaises(RuntimeError):
                record_stage(root, "recover", "exploration", "sol", "completed", {}, model="m", operation_id="crash-1", failure_hook=interrupt)
            run_dir = root / "recover"
            self.assertTrue((run_dir / ".run-journal.json").exists())
            script = "import sys; from run_ledger import inspect_run; print(inspect_run(sys.argv[1], 'recover')['current_stage'])"
            result = subprocess.run([sys.executable, "-c", script, str(root)], cwd=str(Path(__file__).parents[1]), capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("plan", result.stdout.strip())
            self.assertFalse((run_dir / ".run-journal.json").exists())
            self.assertEqual([], validate_bundle(root, "recover"))

    def test_malformed_journal_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_run(root, "bad-journal")
            (root / "bad-journal" / ".run-journal.json").write_text("{}", encoding="utf-8")
            errors = validate_bundle(root, "bad-journal")
            self.assertTrue(any("journal" in error for error in errors))
            with self.assertRaises(RunLedgerError):
                inspect_run(root, "bad-journal")

    def test_operation_id_is_ascii_validated(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            create_run(root, "ids")
            with self.assertRaises(RunLedgerError):
                record_stage(root, "ids", "exploration", "sol", "completed", {}, model="m", operation_id="含糊")


if __name__ == "__main__":
    unittest.main()
