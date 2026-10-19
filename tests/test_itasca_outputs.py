from __future__ import annotations

import base64
import hashlib
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.itasca_outputs import MAX_OUTPUT_BYTES, capture_itasca_output
from mining_research_kernel.r2_workflow import _record
from research_project import enable_research


class ItascaOutputCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        enable_research(self.root, "itasca.outputs.tests")
        self.runs = {}
        self._module = types.ModuleType("mining_research_kernel.itasca_execution")
        self._module.load_itasca_run = self.load_run
        self._modules = patch.dict(sys.modules, {"mining_research_kernel.itasca_execution": self._module})
        self._modules.start()
        self.addCleanup(self._modules.stop)
        self.addCleanup(self.temp.cleanup)

    def load_run(self, project_root, run_id):
        current = ResearchStore(project_root).latest_record(self.runs[run_id]["run_ref"]["id"], "RunReference")
        return {"run_ref": current, "plan": self.runs[run_id]["plan"], "observations": []}

    def add_run(self, run_id="run-a", *, status="completed", context="production", origin="provided_script"):
        output_root = f"outputs/{run_id}"
        plan = {"schema_version": 1, "kind": "itasca_execution_plan", "run_id": run_id,
                "script": {"path": "inputs/model.dat", "sha256": "a" * 64, "text": "model solve"},
                "software": "flac3d", "product_version": "9", "purpose": "inspection",
                "stop_conditions": [], "output_root": output_root, "engine_session": "fake-session",
                "task_context": context, "origin": origin}
        manifest_hash = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        run_ref = _record("RunReference", "runref." + run_id, "itasca.outputs.tests", [f"run:{run_id}"],
            run_id=run_id, revision=1, manifest_sha256=manifest_hash,
            status=status, plan_asset_ref="asset.plan." + run_id, task_id="task-" + run_id,
            engine_session="fake-session", task_context=context)
        asset_id = "asset.plan." + run_id
        plan_asset = _record("Asset", asset_id, "itasca.outputs.tests", [f"run:{run_id}"],
            asset_kind="itasca_execution_plan", locator={"path": f"record:{asset_id}"},
            content_sha256=hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest(),
            authority="derived", status="observed", payload={"plan": plan})
        ResearchStore(self.root).commit("fixture." + run_id, {"role": "host", "model": "test"},
                                        [run_ref, plan_asset])
        self.runs[run_id] = {"run_ref": run_ref, "plan": plan}
        directory = self.root / output_root
        directory.mkdir(parents=True)
        return directory

    @staticmethod
    def write_csv(directory, name="zone_count.csv", body="zone_count\n8\n"):
        target = directory / name
        target.write_text(body, encoding="utf-8", newline="")
        return target

    def capture(self, *, run_id="run-a", operation_id="capture-1", path="outputs/run-a/zone_count.csv", kind="csv"):
        return capture_itasca_output(self.root, run_id=run_id, operation_id=operation_id, path=path, kind=kind)

    def test_capture_embeds_exact_bytes_and_replays_after_source_is_removed(self):
        directory = self.add_run()
        source = self.write_csv(directory)
        original = source.read_bytes()
        result = self.capture()
        self.assertEqual(hashlib.sha256(original).hexdigest(), result["sha256"])
        self.assertEqual("runref.run-a", result["run_ref"])
        self.assertIn("asset_ref", result)
        self.assertIn("evidence_ref", result)
        store = ResearchStore(self.root)
        asset = store.latest_record(result["asset_ref"], "Asset")
        evidence = store.latest_record(result["evidence_ref"], "Evidence")
        self.assertEqual(original, base64.b64decode(asset["payload"]["bytes_base64"], validate=True))
        self.assertEqual(result["asset_ref"], evidence["asset_ref"])
        self.assertTrue(any(edge["relation"] == "run_produces_evidence"
            and edge["from_id"] == result["run_ref"] and edge["to_id"] == result["evidence_ref"]
            for tx in store.list_transactions() for edge in tx["relationships"]))
        source.unlink()
        replay = self.capture()
        self.assertTrue(replay["replayed"])
        self.assertEqual(result["sha256"], replay["sha256"])

    def test_capture_uses_real_itasca_loader_and_status_lifecycle(self):
        module_name = "mining_research_kernel.itasca_execution"
        test_stub = sys.modules.pop(module_name)
        try:
            execution = importlib.import_module(module_name)
        finally:
            sys.modules[module_name] = test_stub
        self._module.load_itasca_run = execution.load_itasca_run
        script_dir = self.root / "inputs"
        script_dir.mkdir()
        script = script_dir / "model.dat"
        script.write_text("model new\n", encoding="utf-8")
        execution.prepare_itasca_run(self.root, run_id="actual-run", script="inputs/model.dat",
            metadata={"software": "flac3d", "product_version": "9", "purpose": "inspect zone count",
                "stop_conditions": ["capture zone_count.csv"], "output_root": "outputs/actual-run",
                "engine_session": "fixture-only", "origin": "provided_script"})
        base_observation = {"schema_version": 1, "kind": "itasca_execution_observation",
            "origin": "agent_supplied", "captured_at": "2026-10-19T00:00:00Z",
            "phase": "submission", "tool_result": {"ok": True, "data": {
                "task_id": "task-actual", "task_status": "pending", "entry_script": str(script.resolve())}}}
        execution.record_itasca_observation(self.root, run_id="actual-run", operation_id="submit-observation",
                                             observation=base_observation)
        completed_observation = {**base_observation, "captured_at": "2026-10-19T00:00:01Z", "phase": "status",
            "tool_result": {"ok": True, "data": {"task_id": "task-actual", "task_status": "completed"}}}
        execution.record_itasca_observation(self.root, run_id="actual-run", operation_id="complete-observation",
                                             observation=completed_observation)
        current = execution.load_itasca_run(self.root, "actual-run")["run_ref"]
        self.assertEqual("completed", current["status"])
        self.assertEqual("completed", current["state"])
        directory = self.root / "outputs" / "actual-run"
        directory.mkdir(parents=True)
        self.write_csv(directory, body="point_id,value\nZ1,8\n")
        result = capture_itasca_output(self.root, run_id="actual-run", operation_id="actual-capture",
            path="outputs/actual-run/zone_count.csv")
        self.assertEqual(current["id"], result["run_ref"])
        self.assertEqual(current["revision"], result["run_revision"])
        later_observation = {**completed_observation, "captured_at": "2026-10-19T00:00:02Z"}
        execution.record_itasca_observation(self.root, run_id="actual-run",
            operation_id="complete-observation-again", observation=later_observation)
        latest = execution.load_itasca_run(self.root, "actual-run")["run_ref"]
        self.assertGreater(latest["revision"], result["run_revision"])
        from mining_research_kernel.result_comparison import import_result_csv
        metadata = {"case_id": "zone-count-demo", "quantity": "zone count", "unit": "count",
            "column_meanings": {"point_id": "zone", "value": "count"},
            "point_basis": "authored example", "conditions": {"model": "fixture-example"}}
        imported = import_result_csv(self.root, task_id="actual-import", question="Import captured count",
            csv_path="outputs/actual-run/zone_count.csv", metadata=metadata, run_ref=current["id"])
        from mining_research_kernel.result_comparison import (
            compare_results, render_result_comparison_report,
        )
        imported_asset = ResearchStore(self.root).latest_record(imported["capture_asset_ref"], "Asset")
        binding = imported_asset["payload"]["run_binding"]
        self.assertEqual(result["run_revision"], binding["output_run_revision"])
        self.assertEqual(latest["revision"], binding["run_revision"])
        import_report = render_result_comparison_report(self.root, task_id="actual-import")
        self.assertIn("This report does not execute a solver", import_report)
        self.assertNotIn("No solver was run", import_report)
        self.assertIn(current["id"], import_report)
        self.assertIn(str(result["run_revision"]), import_report)
        self.assertIn(str(latest["revision"]), import_report)
        self.assertIn(result["asset_ref"], import_report)
        self.assertIn("caller-association-not-authenticated", import_report)
        candidate_file = self.root / "candidate.csv"
        candidate_file.write_text("point_id,value\nZ1,7\n", encoding="utf-8")
        candidate_meta = {**metadata, "case_id": "candidate"}
        candidate = import_result_csv(self.root, task_id="actual-candidate", question="Capture comparison candidate",
            csv_path=candidate_file, metadata=candidate_meta)
        compare_results(self.root, task_id="actual-comparison", question="Compare captured values",
            baseline_asset_ref=imported["capture_asset_ref"], candidate_asset_ref=candidate["capture_asset_ref"],
            point_ids=["Z1"])
        comparison_report = render_result_comparison_report(self.root, task_id="actual-comparison")
        self.assertIn(current["id"], comparison_report)
        self.assertIn("caller-association-not-authenticated", comparison_report)

    def test_operation_replay_rejects_changed_bytes_and_damaged_snapshot(self):
        directory = self.add_run()
        source = self.write_csv(directory)
        self.capture()
        source.write_text("zone_count\n2\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            self.capture()
        store = ResearchStore(self.root)
        tx_path = store.records_dir / "00000002.json"
        tx = json.loads(tx_path.read_text(encoding="utf-8"))
        asset = next(row for row in tx["records"] if row.get("asset_kind") == "itasca_output")
        asset["payload"]["bytes_base64"] = base64.b64encode(b"corrupt").decode("ascii")
        unsigned = dict(tx)
        unsigned.pop("content_sha256", None)
        tx["content_sha256"] = hashlib.sha256(json.dumps(unsigned, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        tx_path.write_text(json.dumps(tx), encoding="utf-8")
        with self.assertRaises(ValueError):
            self.capture()

    def test_output_paths_must_be_inside_root_without_links_and_small_utf8_files(self):
        directory = self.add_run()
        source = self.write_csv(directory)
        for bad in ("../outside.csv", "outputs/run-a/../outside.csv", "outputs\\run-a\\zone_count.csv",
                    str(source), "outputs/run-a"):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                self.capture(path=bad, operation_id="bad" + str(list(str(ord(c)) for c in bad)[0]))
        source.write_bytes(b"a" * (MAX_OUTPUT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "maximum size"):
            self.capture(operation_id="too-large")
        source.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "UTF-8"):
            self.capture(operation_id="bad-utf8", kind="log")

    def test_symlink_and_output_root_escape_are_rejected(self):
        directory = self.add_run()
        external = Path(self.temp.name) / "external.csv"
        external.write_text("zone_count\n1\n", encoding="utf-8")
        link = directory / "linked.csv"
        try:
            link.symlink_to(external)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation is unavailable")
        with self.assertRaisesRegex(ValueError, "symlink|reparse"):
            self.capture(path="outputs/run-a/linked.csv")
        with self.assertRaisesRegex(ValueError, "beneath plan.output_root"):
            self.capture(path="inputs/zone_count.csv", operation_id="outside-root")
        alias = Path(self.temp.name) / "project-alias"
        try:
            alias.symlink_to(self.root, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("directory symlink creation is unavailable")
        with self.assertRaisesRegex(ValueError, "symlink or junction"):
            capture_itasca_output(alias, run_id="run-a", operation_id="root-alias",
                path="outputs/run-a/zone_count.csv")
        from mining_research_kernel.result_comparison import import_result_csv
        metadata = {"case_id": "zone-count", "quantity": "zone count", "unit": "count",
                    "column_meanings": {"point_id": "zone", "value": "count"},
                    "point_basis": "inspection", "conditions": {"model": "fixture"}}
        with self.assertRaisesRegex(ValueError, "symlink or junction"):
            import_result_csv(alias, task_id="root-alias-import", question="reject aliased root",
                csv_path="outputs/run-a/zone_count.csv", metadata=metadata, run_ref="runref.run-a")

    def test_only_terminal_runs_capture_and_failed_runs_are_diagnostic(self):
        pending_dir = self.add_run("pending-run", status="running")
        self.write_csv(pending_dir)
        with self.assertRaisesRegex(ValueError, "terminal run status"):
            self.capture(run_id="pending-run", path="outputs/pending-run/zone_count.csv")
        failed_dir = self.add_run("failed-run", status="failed")
        (failed_dir / "solver.log").write_text("solver stopped", encoding="utf-8")
        diagnostic = self.capture(run_id="failed-run", operation_id="failed-log",
                                  path="outputs/failed-run/solver.log", kind="log")
        self.assertEqual("log", diagnostic["kind"])
        self.assertTrue(diagnostic["diagnostic_only"])
        self.assertEqual("failed", ResearchStore(self.root).latest_record(diagnostic["run_ref"], "RunReference")["status"])
        with self.assertRaisesRegex(ValueError, "completed Itasca run"):
            self.capture(run_id="failed-run", operation_id="failed-csv",
                          path="outputs/failed-run/zone_count.csv", kind="csv")
        interrupted_dir = self.add_run("interrupted-run", status="interrupted")
        (interrupted_dir / "solver.log").write_text("interrupted by stop condition", encoding="utf-8")
        interrupted = self.capture(run_id="interrupted-run", operation_id="interrupted-log",
            path="outputs/interrupted-run/solver.log", kind="log")
        self.assertTrue(interrupted["diagnostic_only"])

    def test_synthetic_csv_cannot_be_imported_as_production_evidence(self):
        directory = self.add_run("synthetic-run", context="synthetic", origin="synthetic")
        self.write_csv(directory)
        captured = self.capture(run_id="synthetic-run", path="outputs/synthetic-run/zone_count.csv")
        self.assertFalse(captured["diagnostic_only"])
        from mining_research_kernel.result_comparison import import_result_csv

        metadata = {"case_id": "synthetic", "quantity": "zone count", "unit": "count",
                    "column_meanings": {"point_id": "zone", "value": "count"},
                    "point_basis": "inspection", "conditions": {"model": "fixture"}}
        with self.assertRaisesRegex(ValueError, "task_context does not match"):
            import_result_csv(self.root, task_id="synthetic-production", question="reject synthetic",
                csv_path="outputs/synthetic-run/zone_count.csv", metadata=metadata,
                run_ref=captured["run_ref"])

    def test_run_revision_compare_and_swap_rejects_concurrent_change(self):
        directory = self.add_run()
        self.write_csv(directory)
        store_type = ResearchStore
        original_commit = store_type.commit
        changed = {"done": False}

        def interleaved_commit(store, operation_id, producer, records, relationships=None, **kwargs):
            if operation_id.startswith("itasca-output.") and not changed["done"]:
                changed["done"] = True
                old = store.latest_record("runref.run-a", "RunReference")
                bumped = dict(old)
                bumped["revision"] = 2
                bumped["status"] = "interrupted"
                original_commit(store, "fixture.bump", {"role": "host", "model": "test"}, [bumped])
            return original_commit(store, operation_id, producer, records, relationships, **kwargs)

        with patch.object(store_type, "commit", interleaved_commit):
            with self.assertRaisesRegex(ValueError, "revision changed"):
                self.capture()

    def test_result_csv_import_binds_only_captured_matching_output(self):
        directory = self.add_run()
        self.write_csv(directory, body="point_id,value\nZ1,8\n")
        captured = self.capture()
        from mining_research_kernel.result_comparison import import_result_csv

        metadata = {"case_id": "zone-count-demo", "quantity": "zone count", "unit": "count",
                    "column_meanings": {"point_id": "zone", "value": "count"},
                    "point_basis": "authored example", "conditions": {"model": "fixture-example"}}
        result = import_result_csv(self.root, task_id="bound-import", question="Read zone count",
            csv_path="outputs/run-a/zone_count.csv", metadata=metadata, run_ref=captured["run_ref"])
        store = ResearchStore(self.root)
        evidence = store.latest_record(result["evidence_refs"][0], "Evidence")
        self.assertEqual(captured["run_ref"], store.latest_record(
            "runref.run-a", "RunReference")["id"])
        self.assertTrue(any(edge["relation"] == "run_produces_evidence"
            and edge["from_id"] == captured["run_ref"] and edge["to_id"] == evidence["id"]
            for tx in store.list_transactions() for edge in tx["relationships"]))
        self.assertEqual(captured["sha256"], evidence["locator"].get("sha256", captured["sha256"]))

    def test_result_csv_import_rejects_wrong_run_uncaptured_or_changed_bytes(self):
        directory = self.add_run()
        self.add_run("run-b")
        source = self.write_csv(directory, body="point_id,value\nZ1,8\n")
        self.write_csv(self.root / "outputs" / "run-b", body="point_id,value\nZ1,8\n")
        captured = self.capture()
        from mining_research_kernel.result_comparison import import_result_csv

        metadata = {"case_id": "zone-count-demo", "quantity": "zone count", "unit": "count",
                    "column_meanings": {"point_id": "zone", "value": "count"},
                    "point_basis": "authored example", "conditions": {"model": "fixture-example"}}
        with self.assertRaisesRegex(ValueError, "no captured output"):
            import_result_csv(self.root, task_id="wrong-run", question="wrong", csv_path=source,
                metadata=metadata, run_ref="runref.run-b")
        source.write_text("point_id,value\nZ1,999\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "no captured output"):
            import_result_csv(self.root, task_id="changed", question="changed", csv_path=source,
                metadata=metadata, run_ref=captured["run_ref"])
        source.write_bytes(b"x" * (MAX_OUTPUT_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "maximum size"):
            import_result_csv(self.root, task_id="oversized-bound-import", question="reject oversized",
                csv_path=source, metadata=metadata, run_ref=captured["run_ref"])
        with self.assertRaisesRegex(ValueError, "no captured output"):
            import_result_csv(self.root, task_id="uncaptured", question="uncaptured",
                csv_path="outputs/run-b/zone_count.csv", metadata=metadata, run_ref="runref.run-b")

    def test_result_csv_import_rejects_historical_run_identity_mismatch(self):
        directory = self.add_run()
        self.write_csv(directory, body="point_id,value\nZ1,8\n")
        captured = self.capture()
        store = ResearchStore(self.root)
        previous = store.latest_record(captured["run_ref"], "RunReference")
        changed = dict(previous)
        changed.update({"revision": previous["revision"] + 1, "task_id": "different-external-task"})
        store.commit("fixture.identity-change", {"role": "host", "model": "test"}, [changed])
        from mining_research_kernel.result_comparison import import_result_csv

        metadata = {"case_id": "zone-count-demo", "quantity": "zone count", "unit": "count",
                    "column_meanings": {"point_id": "zone", "value": "count"},
                    "point_basis": "authored example", "conditions": {"model": "fixture-example"}}
        with self.assertRaisesRegex(ValueError, "historical RunReference identity"):
            import_result_csv(self.root, task_id="wrong-historical-identity", question="reject changed identity",
                csv_path="outputs/run-a/zone_count.csv", metadata=metadata, run_ref=captured["run_ref"])

    def test_ordinary_csv_import_without_run_ref_keeps_existing_behavior(self):
        self.add_run("unused-run")
        source = self.root / "ordinary.csv"
        source.write_text("point_id,value\nZ1,4\n", encoding="utf-8")
        from mining_research_kernel.result_comparison import import_result_csv

        metadata = {"case_id": "ordinary", "quantity": "stress", "unit": "MPa",
                    "column_meanings": {"point_id": "point", "value": "stress"},
                    "point_basis": "same points", "conditions": {"support": "A"}}
        result = import_result_csv(self.root, task_id="ordinary-import", question="Read export",
                                   csv_path=source, metadata=metadata)
        self.assertEqual(1, result["capture"]["row_count"])
        self.assertFalse(result["replayed"])


if __name__ == "__main__":
    unittest.main()
