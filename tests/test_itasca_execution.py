from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from mining_research_kernel.itasca_execution import (
    itasca_run_progress,
    load_itasca_run,
    prepare_itasca_run,
    record_itasca_observation,
    render_itasca_run_report,
)
from mining_research_kernel.records import ResearchStore


class ItascaExecutionTests(unittest.TestCase):
    def setUp(self):
        self._temporary = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary.name)
        (self.root / "research_project.json").write_text(
            json.dumps({"schema_version": 1, "project_id": "itasca-test"}), encoding="utf-8")
        (self.root / "scripts").mkdir()
        (self.root / "scripts" / "inventory.py").write_text("print('read-only inventory')\n", encoding="utf-8")
        (self.root / "outputs").mkdir()
        self.metadata = {
            "software": "flac3d", "product_version": "9.0", "purpose": "record read-only inventory",
            "stop_conditions": ["do not reset model", "do not cycle model"], "output_root": "outputs",
            "engine_session": "engine-session-test", "origin": "provided_script",
        }

    def tearDown(self):
        self._temporary.cleanup()

    def prepare(self, run_id="run-1", metadata=None, task_context="production"):
        return prepare_itasca_run(self.root, run_id=run_id, script="scripts/inventory.py",
                                  metadata=metadata or self.metadata, task_context=task_context)

    def observation(self, phase, *, status="pending", task_id="a1b2c3", origin="agent_supplied",
                    ok=True, error_code="bridge_unavailable"):
        captured = {"submission": "2026-10-19T06:00:00Z", "status": "2026-10-19T06:01:00Z"}[phase]
        if not ok:
            result = {"ok": False, "error": {"code": error_code, "message": "bridge request unavailable",
                                               "details": {"task_id": task_id}}}
        elif phase == "submission":
            result = {"ok": True, "data": {"task_id": task_id, "entry_script": str((self.root / "scripts" / "inventory.py").resolve()),
                                             "task_status": "pending", "description": "inventory"}}
        else:
            result = {"ok": True, "data": {"task_id": task_id, "task_status": status,
                                             "entry_script": str((self.root / "scripts" / "inventory.py").resolve()),
                                             "output": "8 zones; cycle 0", "pagination": {"total_lines": 1, "line_range": "1-1"}}}
        return {"schema_version": 1, "kind": "itasca_execution_observation", "origin": origin,
                "captured_at": captured, "phase": phase, "tool_result": result}

    def record(self, operation_id, observation, run_id="run-1"):
        return record_itasca_observation(self.root, run_id=run_id,
                                         operation_id=operation_id, observation=observation)

    def test_lifecycle_receipts_and_report_are_rebuildable(self):
        prepared = self.prepare()
        self.assertEqual(prepared["run_ref"]["status"], "prepared")
        submitted = self.record("submit-1", self.observation("submission"))
        self.assertEqual(submitted["run_ref"]["task_id"], "a1b2c3")
        done = self.observation("status", status="completed")
        done["captured_at"] = "2026-10-19T06:02:00Z"
        done["tool_result"]["data"]["output"] = "before ``` after " + ("x" * 2500)
        recorded = self.record("status-1", done)
        self.assertEqual(recorded["run_ref"]["status"], "completed")
        loaded = load_itasca_run(self.root, "run-1")
        self.assertEqual(loaded["plan"]["script"]["sha256"], prepared["plan"]["script"]["sha256"])
        self.assertEqual(len(loaded["observations"]), 2)
        progress = itasca_run_progress(self.root, run_id="run-1")
        self.assertEqual(progress["status"], "completed")
        self.assertEqual(progress["run_ref"]["status"], "completed")
        self.assertEqual(progress["run_id"], "run-1")
        self.assertEqual(progress["observations"], loaded["observations"])
        report = render_itasca_run_report(self.root, run_id="run-1")
        self.assertIn("not a complete production `static_check`", report)
        self.assertIn(f"Observation Evidence: `{recorded['evidence_ref']}`", report)
        self.assertIn("Stored output preview: first 2000 characters; truncated: yes", report)
        self.assertIn("\n````\nbefore ``` after ", report)
        store = ResearchStore(self.root)
        kinds = [record["type"] for tx in store.list_transactions() for record in tx["records"]]
        self.assertNotIn("TaskState", kinds)
        self.assertNotIn("Verification", kinds)

    def test_schema_is_strict_and_api_replay_is_idempotent(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "itasca_execution_observation.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        observation = self.observation("submission")
        jsonschema.validate(observation, schema)
        first = self.prepare()
        replay = self.prepare()
        self.assertEqual(first["run_ref"], replay["run_ref"])
        one = self.record("submit-1", observation)
        two = self.record("submit-1", observation)
        self.assertEqual(one["evidence_ref"], two["evidence_ref"])
        self.assertEqual(two["run_ref"]["revision"], one["run_ref"]["revision"])
        changed = self.observation("submission")
        changed["tool_result"]["data"]["description"] = "different"
        with self.assertRaisesRegex(ValueError, "different or damaged"):
            self.record("submit-1", changed)
        unknown_field = self.observation("submission")
        unknown_field["unexpected"] = "reject"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(unknown_field, schema)

    def test_status_transport_failure_without_task_id_retains_last_state(self):
        self.prepare()
        self.record("submit-1", self.observation("submission"))
        failed_query = self.observation("status", ok=False)
        failed_query["tool_result"]["error"].pop("details")
        receipt = self.record("query-disconnected", failed_query)
        self.assertEqual(receipt["state"], "pending")
        self.assertEqual(receipt["run_ref"]["task_id"], "a1b2c3")
        loaded = load_itasca_run(self.root, "run-1")
        self.assertEqual(loaded["observations"][-1], failed_query)
        self.assertIn("bridge_unavailable", render_itasca_run_report(self.root, run_id="run-1"))
        self.assertTrue(self.record("query-disconnected", failed_query)["status"] == "replayed")
        self.prepare("unsubmitted")
        with self.assertRaisesRegex(ValueError, "task_id is required"):
            self.record("query-before-submission", failed_query, run_id="unsubmitted")
        self.record("query-recovered", self.observation("status", status="completed"))
        self.assertEqual(itasca_run_progress(self.root, run_id="run-1")["status"], "completed")

    def test_changed_input_and_wrong_external_script_are_rejected_before_binding(self):
        self.prepare()
        (self.root / "scripts" / "inventory.py").write_text("print('changed')\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bytes differ"):
            self.record("submit-1", self.observation("submission"))
        ref = ResearchStore(self.root).latest_record("itasca.run." + __import__("hashlib").sha256(b"run-1").hexdigest()[:32], "RunReference")
        self.assertIsNone(ref["task_id"])

    def test_submission_entry_script_must_match_the_prepared_path(self):
        self.prepare()
        observation = self.observation("submission")
        observation["tool_result"]["data"]["entry_script"] = str((self.root / "scripts" / "other.py").resolve())
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.record("submit-wrong-path", observation)
        ref_id = "itasca.run." + __import__("hashlib").sha256(b"run-1").hexdigest()[:32]
        self.assertIsNone(ResearchStore(self.root).latest_record(ref_id, "RunReference")["task_id"])

    def test_external_task_identity_and_same_session_uniqueness(self):
        self.prepare("run-1")
        self.prepare("run-2")
        self.record("submit-1", self.observation("submission", task_id="a1b2c3"), "run-1")
        with self.assertRaisesRegex(ValueError, "another run"):
            self.record("submit-2", self.observation("submission", task_id="a1b2c3"), "run-2")
        mismatched = self.observation("status", status="running", task_id="d4e5f6")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.record("status-wrong", mismatched, "run-1")

    def test_uncertain_submission_is_not_retried_but_status_can_recover(self):
        self.prepare()
        uncertain = self.observation("submission", ok=False, error_code="bridge_unavailable")
        first = self.record("submit-unknown", uncertain)
        self.assertEqual(first["run_ref"]["status"], "submission_unknown")
        with self.assertRaisesRegex(ValueError, "allowed only once"):
            self.record("submit-retry", self.observation("submission", task_id="d4e5f6"))
        resumed = self.observation("status", status="running")
        resumed["captured_at"] = "2026-10-19T06:03:00Z"
        self.assertEqual(self.record("status-resume", resumed)["run_ref"]["status"], "running")

    def test_terminal_state_cannot_regress_and_history_survives_missing_script(self):
        self.prepare()
        self.record("submit-1", self.observation("submission"))
        complete = self.observation("status", status="completed")
        complete["captured_at"] = "2026-10-19T06:02:00Z"
        self.record("status-complete", complete)
        running = self.observation("status", status="running")
        running["captured_at"] = "2026-10-19T06:03:00Z"
        with self.assertRaisesRegex(ValueError, "terminal status"):
            self.record("status-regress", running)
        (self.root / "scripts" / "inventory.py").unlink()
        self.assertEqual(len(load_itasca_run(self.root, "run-1")["observations"]), 2)

    def test_corrupt_asset_hash_is_rejected_on_replay_and_load(self):
        self.prepare()
        observation = self.observation("submission")
        created = self.record("submit-1", observation)
        store = ResearchStore(self.root)
        import mining_research_kernel.itasca_execution as execution
        original_sha = execution._sha
        original_latest = execution._latest_records

        def damaged_sha(value):
            if isinstance(value, dict) and value.get("kind") == "itasca_execution_observation_record":
                return "0" * 64
            return original_sha(value)

        with patch.object(execution, "_sha", damaged_sha):
            with self.assertRaisesRegex(ValueError, "payload hash"):
                load_itasca_run(self.root, "run-1")
        def damaged_latest(instance):
            rows = original_latest(instance)
            rows[created["asset_ref"]]["content_sha256"] = "0" * 64
            return rows
        with patch.object(execution, "_latest_records", damaged_latest):
            with self.assertRaisesRegex(ValueError, "damaged observation"):
                self.record("submit-1", observation)

    def test_plan_asset_revision_race_rejects_observation_commit(self):
        self.prepare()
        import mining_research_kernel.itasca_execution as execution
        original_plan_for = execution._plan_for
        raced = False

        def append_plan_revision(store, run_id):
            nonlocal raced
            result = original_plan_for(store, run_id)
            if not raced:
                raced = True
                current = store.latest_record(result[1]["id"], "Asset")
                changed = copy.deepcopy(current)
                changed["revision"] += 1
                changed["payload"]["late_revision"] = "concurrent writer"
                changed["content_sha256"] = execution._sha(changed["payload"])
                store.commit("itasca-plan-race", {"role": "host", "model": "test"}, [changed],
                             expected_revisions={current["id"]: current["revision"]})
            return result

        with patch.object(execution, "_plan_for", append_plan_revision):
            with self.assertRaisesRegex(ValueError, "record revision changed"):
                self.record("submit-race", self.observation("submission"))
        progress = itasca_run_progress(self.root, run_id="run-1")
        self.assertEqual(progress["status"], "prepared")
        self.assertEqual(progress["observations"], [])

    def test_later_observation_asset_revision_does_not_rewrite_report_history(self):
        self.prepare()
        self.record("submit-1", self.observation("submission"))
        completed = self.observation("status", status="completed")
        completed["captured_at"] = "2026-10-19T06:02:00Z"
        completed["tool_result"]["data"]["output"] = "original captured log"
        self.record("status-1", completed)
        store = ResearchStore(self.root)
        run_ref = store.latest_record("itasca.run." + __import__("hashlib").sha256(b"run-1").hexdigest()[:32], "RunReference")
        evidence = store.latest_record(run_ref["observation_refs"][-1], "Evidence")
        asset = store.latest_record(evidence["asset_ref"], "Asset")
        changed = copy.deepcopy(asset)
        changed["revision"] += 1
        changed["payload"]["request"]["observation"]["tool_result"]["data"]["output"] = "later rewritten log"
        import mining_research_kernel.itasca_execution as execution
        changed["payload"]["request_sha256"] = execution._sha(changed["payload"]["request"])
        changed["content_sha256"] = execution._sha(changed["payload"])
        store.commit("itasca-observation-asset-revision", {"role": "host", "model": "test"}, [changed],
                     expected_revisions={asset["id"]: asset["revision"]})
        loaded = load_itasca_run(self.root, "run-1")
        self.assertIn("original captured log", loaded["observations"][-1]["tool_result"]["data"]["output"])
        report = render_itasca_run_report(self.root, run_id="run-1")
        self.assertIn("original captured log", report)
        self.assertNotIn("later rewritten log", report)

    def test_submission_unknown_without_task_id_is_retained_as_insufficient(self):
        self.prepare()
        unknown = self.observation("submission", ok=False)
        unknown["tool_result"]["error"]["details"].pop("task_id")
        saved = self.record("submit-unknown-no-id", unknown)
        self.assertEqual(saved["run_ref"]["status"], "submission_unknown")
        self.assertIsNone(saved["run_ref"]["task_id"])
        self.assertTrue(itasca_run_progress(self.root, run_id="run-1")["submission_unknown"])
        report = render_itasca_run_report(self.root, run_id="run-1")
        self.assertIn("cannot be associated or recovered", report)
        self.assertIn("will not guess an ID or resubmit", report)

    def test_resolved_status_state_mismatch_is_rejected(self):
        self.prepare()
        store = ResearchStore(self.root)
        run_id = "itasca.run." + __import__("hashlib").sha256(b"run-1").hexdigest()[:32]
        original = ResearchStore.latest_record

        def inconsistent(instance, record_id, record_type=None):
            result = original(instance, record_id, record_type)
            if record_id == run_id and result is not None:
                result["state"] = "completed"
            return result

        from unittest.mock import patch
        with patch.object(ResearchStore, "latest_record", inconsistent):
            with self.assertRaisesRegex(ValueError, "status/state"):
                load_itasca_run(self.root, "run-1")

    def test_project_root_symlink_or_junction_is_rejected_before_resolution(self):
        alias = self.root.parent / (self.root.name + "-link")
        try:
            os.symlink(self.root, alias, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            # Windows developer mode may disable symlink creation while
            # directory junctions remain available without elevation.
            if os.name == "nt":
                created = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(alias), str(self.root)],
                                         capture_output=True, text=True)
                if created.returncode != 0:
                    self._assert_root_guard_runs_before_resolve(alias)
                    return
            else:
                self._assert_root_guard_runs_before_resolve(alias)
                return
        try:
            with self.assertRaisesRegex(ValueError, "project root.*symlink or junction"):
                prepare_itasca_run(alias, run_id="linked", script="scripts/inventory.py",
                                   metadata=self.metadata)
            with self.assertRaisesRegex(ValueError, "project root.*symlink or junction"):
                record_itasca_observation(alias, run_id="run-1", operation_id="linked-op",
                                          observation=self.observation("submission"))
            with self.assertRaisesRegex(ValueError, "project root.*symlink or junction"):
                load_itasca_run(alias, "run-1")
        finally:
            if alias.exists() and alias.is_dir() and not alias.is_symlink():
                alias.rmdir()
            else:
                alias.unlink(missing_ok=True)

    def _assert_root_guard_runs_before_resolve(self, alias):
        from unittest.mock import patch
        import mining_research_kernel.itasca_execution as execution

        def reject(path, label):
            if label == "Itasca execution project root":
                raise ValueError("Itasca execution project root cannot pass through a symlink or junction")

        with patch.object(execution, "_reject_reparse_chain", side_effect=reject):
            with self.assertRaisesRegex(ValueError, "project root.*symlink or junction"):
                prepare_itasca_run(alias, run_id="linked", script="scripts/inventory.py",
                                   metadata=self.metadata)
            with self.assertRaisesRegex(ValueError, "project root.*symlink or junction"):
                record_itasca_observation(alias, run_id="run-1", operation_id="linked-op",
                                          observation=self.observation("submission"))
            with self.assertRaisesRegex(ValueError, "project root.*symlink or junction"):
                load_itasca_run(alias, "run-1")

    def test_synthetic_isolation_and_manifest_path_escape_rejection(self):
        synthetic = copy.deepcopy(self.metadata)
        synthetic["origin"] = "synthetic"
        self.prepare(metadata=synthetic, task_context="synthetic")
        with self.assertRaisesRegex(ValueError, "cannot be mixed"):
            self.record("synthetic-prod", self.observation("submission", origin="agent_supplied"))
        synthetic_observation = self.observation("submission", origin="synthetic")
        self.assertEqual(self.record("synthetic-only", synthetic_observation)["state"], "pending")
        escaped = dict(self.metadata, output_root="../outside")
        with self.assertRaisesRegex(ValueError, "safe project-relative"):
            self.prepare("escape-run", escaped)

    def test_concurrent_cas_serializes_observation_revisions(self):
        self.prepare()
        self.record("submit-1", self.observation("submission"))
        results, errors = [], []

        def capture(index):
            item = self.observation("status", status="running")
            item["captured_at"] = f"2026-10-19T06:0{index + 2}:00Z"
            try:
                results.append(self.record(f"status-{index}", item))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=capture, args=(index,)) for index in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 2)
        loaded = load_itasca_run(self.root, "run-1")
        self.assertEqual(loaded["run_ref"]["revision"], 4)
        self.assertEqual(len(loaded["observations"]), 3)


if __name__ == "__main__":
    unittest.main()
