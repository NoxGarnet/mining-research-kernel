from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.result_comparison import (
    compare_results, import_result_csv, render_result_comparison_report,
    result_comparison_progress,
)
from research_project import enable_research


class ResultComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        enable_research(self.project, "result.csv.tests")
        self.baseline = self.base / "baseline.csv"
        self.candidate = self.base / "candidate.csv"
        self.baseline.write_text("point_id,value\nP1,-12.5\nP2,-8\nP3,\n", encoding="utf-8")
        self.candidate.write_text("value,point_id\n-6,P4\n-10,P1\n-7,P2\n", encoding="utf-8")
        self.meta = {"case_id": "case-A", "quantity": "stress", "unit": "MPa",
            "column_meanings": {"point_id": "monitoring point", "value": "stress"},
            "point_basis": "same named points", "conditions": {"support": "A"}}

    def tearDown(self):
        self.temp.cleanup()

    def capture(self, task, path, case):
        metadata = {**self.meta, "case_id": case}
        return import_result_csv(self.project, task_id=task, question="Capture export", csv_path=path, metadata=metadata)

    def test_import_replay_and_restore_without_source(self):
        first = self.capture("import-base", self.baseline, "base")
        source_hash = hashlib.sha256(self.baseline.read_bytes()).hexdigest()
        self.assertEqual(source_hash, first["capture"]["source_sha256"])
        self.assertEqual(first["capture_asset_ref"], first["asset_refs"][0])
        self.baseline.unlink()
        replay = self.capture("import-base", self.baseline, "base")
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["capture"], replay["capture"])
        self.assertFalse(replay["run_created"])
        self.assertFalse(replay["verification_created"])
        with self.assertRaises(ValueError):
            import_result_csv(self.project, task_id="import-base", question="Changed", csv_path=self.baseline,
                              metadata={**self.meta, "case_id": "base"})

    def test_selected_points_delta_status_lines_report_and_no_run(self):
        base = self.capture("base-cap", self.baseline, "base")
        candidate = self.capture("candidate-cap", self.candidate, "candidate")
        result = compare_results(self.project, task_id="compare", question="Compare selected points",
            baseline_asset_ref=base["asset_refs"][0], candidate_asset_ref=candidate["asset_refs"][0],
            point_ids=["P1", "P2", "P3"])
        points = result["comparison"]["points"]
        self.assertEqual(["P1", "P2", "P3"], [row["point_id"] for row in points])
        self.assertEqual(["2.5", "1"], [row["delta"] for row in points[:2]])
        self.assertEqual("INSUFFICIENT", points[2]["status"])
        self.assertEqual(2, points[0]["baseline"]["rows"][0]["start_line"])
        self.assertEqual(3, points[0]["candidate"]["rows"][0]["start_line"])
        self.assertNotIn("P4", json.dumps(result["comparison"]))
        self.assertFalse(result["run_created"])
        self.assertFalse(result["verification_created"])
        report = render_result_comparison_report(self.project, task_id="compare")
        self.assertIn("Candidate − baseline", report)
        self.assertIn("No solver was run", report)
        self.assertEqual([], list((self.project / "reports").glob("*")) if (self.project / "reports").exists() else [])

    def test_metadata_gates_and_synthetic_isolation(self):
        base = self.capture("base-cap", self.baseline, "base")
        wrong = self.capture("candidate-cap", self.candidate, "candidate")
        # A fresh task with a different unit preserves values but does not calculate deltas.
        store = ResearchStore(self.project)
        # The mismatch is exercised with a separately captured synthetic pair below.
        self.assertIsNotNone(store.latest_record(base["capture_asset_ref"], "Asset"))
        synthetic_meta = {**self.meta, "case_id": "syn", "origin": "synthetic"}
        synth = import_result_csv(self.project, task_id="synthetic-cap", question="Capture synthetic",
            csv_path=self.candidate, metadata=synthetic_meta, task_context="synthetic")
        with self.assertRaisesRegex(ValueError, "synthetic captures"):
            compare_results(self.project, task_id="mixed", question="Do not mix",
                baseline_asset_ref=base["capture_asset_ref"], candidate_asset_ref=synth["capture_asset_ref"],
                point_ids=["P1"])
        self.assertTrue(wrong["capture"]["source_sha256"])

    def test_unit_mismatch_keeps_selected_points_without_delta(self):
        base = self.capture("base-unit", self.baseline, "base")
        other_metadata = {**self.meta, "case_id": "other", "unit": "kPa"}
        other = import_result_csv(self.project, task_id="other-unit", question="Capture other unit",
            csv_path=self.candidate, metadata=other_metadata)
        result = compare_results(self.project, task_id="unit-compare", question="Compare unlike units",
            baseline_asset_ref=base["capture_asset_ref"], candidate_asset_ref=other["capture_asset_ref"],
            point_ids=["P1"])
        point = result["comparison"]["points"][0]
        self.assertEqual("INSUFFICIENT", point["status"])
        self.assertIsNone(point["delta"])
        self.assertIn("unit_mismatch", result["judgment"]["gaps"])

    def test_bad_requests_and_progress_source_hash_are_bounded(self):
        result = self.capture("base-cap", self.baseline, "base")
        with self.assertRaises(ValueError):
            compare_results(self.project, task_id="bad", question="bad",
                baseline_asset_ref=result["capture_asset_ref"], candidate_asset_ref=result["capture_asset_ref"],
                point_ids=["P1", "P1"])
        checks = result_comparison_progress(self.project, task_id="base-cap",
            source_paths={result["capture_asset_ref"]: str(self.baseline)})
        self.assertEqual("unchanged", checks["source_checks"][result["capture_asset_ref"]]["status"])
        self.baseline.write_text("point_id,value\nP1,999\n", encoding="utf-8")
        changed = result_comparison_progress(self.project, task_id="base-cap",
            source_paths={result["capture_asset_ref"]: str(self.baseline)})
        self.assertEqual("changed", changed["source_checks"][result["capture_asset_ref"]]["status"])
        self.assertEqual(result["capture"]["source_sha256"], result_comparison_progress(
            self.project, task_id="base-cap")["captures"][0]["source_sha256"])

    def test_malformed_json_types_fail_as_value_errors(self):
        with self.assertRaises(ValueError):
            import_result_csv(self.project, task_id="bad-origin", question="bad", csv_path=self.baseline,
                metadata={**self.meta, "origin": {}})
        with self.assertRaises(ValueError):
            import_result_csv(self.project, task_id="bad-path", question="bad", csv_path={}, metadata=self.meta)
        with self.assertRaises(ValueError):
            compare_results(self.project, task_id="bad-related", question="bad",
                baseline_asset_ref="a", candidate_asset_ref="b", point_ids=["P1"], related_task_ids=[{}])

    def test_relative_paths_migrate_and_external_same_names_are_distinct(self):
        exports = self.project / "exports"
        exports.mkdir()
        source = exports / "baseline.csv"
        source.write_text("point_id,value\nP1,2\n", encoding="utf-8")
        first = import_result_csv(self.project, task_id="portable", question="Portable capture",
            csv_path="exports/baseline.csv", metadata=self.meta)
        moved = self.base / "moved-project"
        shutil.copytree(self.project, moved)
        replay = import_result_csv(moved, task_id="portable", question="Portable capture",
            csv_path="exports/baseline.csv", metadata=self.meta)
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["capture"]["source_locator"], replay["capture"]["source_locator"])
        with self.assertRaisesRegex(ValueError, "'..'"):
            import_result_csv(self.project, task_id="escape", question="Escape", csv_path="../baseline.csv", metadata=self.meta)

        one = self.base / "external-one"
        two = self.base / "external-two"
        one.mkdir(); two.mkdir()
        (one / "same.csv").write_text("point_id,value\nP1,1\n", encoding="utf-8")
        (two / "same.csv").write_text("point_id,value\nP1,1\n", encoding="utf-8")
        a = import_result_csv(self.project, task_id="external-one", question="External", csv_path=one / "same.csv", metadata=self.meta)
        b = import_result_csv(self.project, task_id="external-two", question="External", csv_path=two / "same.csv", metadata=self.meta)
        self.assertEqual("caller:same.csv", a["capture"]["source_locator"]["path"])
        self.assertNotEqual(a["capture"]["source_locator"]["identity_sha256"], b["capture"]["source_locator"]["identity_sha256"])
        with self.assertRaisesRegex(ValueError, "collide"):
            import_result_csv(self.project, task_id="bad-conditions", question="Bad metadata", csv_path=source,
                metadata={**self.meta, "conditions": {" support": "A", "support ": "B"}})


if __name__ == "__main__":
    unittest.main()
