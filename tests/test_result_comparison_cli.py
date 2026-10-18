"""Result import/comparison across CLI processes and protected persistence."""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import jsonschema

from mining_research_kernel.project_context import project_context
from mining_research_kernel.records import ResearchStore
from research_project import enable_research

REPO = Path(__file__).resolve().parents[1]


class ResultComparisonCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "project with spaces"
        self.root.mkdir()
        enable_research(self.root, "results.cli.test")
        (self.root / "START.md").write_text("# Existing project\n", encoding="utf-8")
        self.paths = []
        for name, body in (("baseline", "point_id,value\nP1,-12.5\nP2,-8.0\nP3,\n"),
                           ("candidate", "value,point_id\n-7.0,P2\n-10.0,P1\n-6.0,P4\n")):
            path = self.root / f"{name}.csv"
            path.write_text(body, encoding="utf-8")
            self.paths.append(path)
            (self.base / f"{name}.json").write_text(json.dumps(self.metadata(name)), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def metadata(self, case):
        return {"case_id": case, "quantity": "displacement_y", "unit": "mm",
                "column_meanings": {"point_id": "Authored point ID", "value": "Authored signed value"},
                "point_basis": "Shared synthetic point definitions",
                "conditions": {"stage": "synthetic stage", "scheme": case}, "origin": "synthetic"}

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
                                 *args, "--project-root", str(self.root)], cwd=self.base,
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def import_pair(self):
        captures = []
        for name in ("baseline", "candidate"):
            result = json.loads(self.cli("result-import", "--task-id", f"import-{name}", "--question", "Read selected export",
                "--csv", f"{name}.csv", "--metadata-file", str(self.base / f"{name}.json"), "--task-context", "synthetic"))
            captures.append(result["asset_refs"][0])
        return captures

    def compare_args(self, refs, task="compare"):
        return ["result-compare", "--task-id", task, "--question", "Compare selected synthetic points",
                "--baseline-asset-ref", refs[0], "--candidate-asset-ref", refs[1],
                "--point", "P1", "--point", "P2", "--point", "P3", "--task-context", "synthetic"]

    def records(self):
        return {p.name: p.read_bytes() for p in (self.root / "research/records").glob("*.json")}

    def test_cli_alignment_source_locators_offline_recovery_and_protected_export(self):
        hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths]
        refs = self.import_pair()
        compared = json.loads(self.cli(*self.compare_args(refs)))
        schema = json.loads((REPO / "schemas/task_packet.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(schema).validate(compared["task_packet"])
        rows = {p["point_id"]: p for p in compared["comparison"]["points"]}
        self.assertEqual({"P1", "P2", "P3"}, set(rows))
        self.assertEqual(Decimal("2.5"), Decimal(rows["P1"]["delta"]))
        self.assertEqual(Decimal("1"), Decimal(rows["P2"]["delta"]))
        self.assertIsNone(rows["P3"]["delta"])
        self.assertEqual("INSUFFICIENT", rows["P3"]["status"])
        self.assertEqual(2, rows["P1"]["baseline"]["rows"][0]["start_line"])
        self.assertEqual(3, rows["P1"]["candidate"]["rows"][0]["start_line"])
        self.assertEqual(hashes, [hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths])
        before = self.records()
        for path in self.paths:
            path.unlink()
        progress = json.loads(self.cli("result-progress", "--task-id", "compare"))
        self.assertEqual("compare", progress["task_packet"]["task_id"])
        report = self.cli("result-report", "--task-id", "compare")
        for digest in hashes:
            self.assertIn(digest, report)
        self.assertIn("P3", report)
        self.assertTrue(json.loads(self.cli(*self.compare_args(refs)))["replayed"])
        self.cli("result-report", "--task-id", "compare", "--output", "reports/results.md")
        self.cli("result-report", "--task-id", "compare", "--output", "START.md", expected=2)
        self.assertEqual("# Existing project\n", (self.root / "START.md").read_text(encoding="utf-8"))
        self.assertEqual(before, self.records())
        mapping = self.base / "current-paths.json"
        mapping.write_text(json.dumps({refs[0]: "baseline.csv"}), encoding="utf-8")
        missing = json.loads(self.cli("result-progress", "--task-id", "compare", "--source-paths-file", str(mapping)))
        self.assertEqual("missing", missing["source_checks"][refs[0]]["status"])
        self.assertEqual("not_checked", missing["source_checks"][refs[1]]["status"])
        types = {r["type"] for tx in ResearchStore(self.root).list_transactions() for r in tx["records"]}
        self.assertTrue(types.isdisjoint({"Run", "RunReference", "Verification"}))
        items, offset = [], 0
        while True:
            view = project_context(self.root, offset=offset)
            items.extend(view["items"])
            offset = view["page"]["next_offset"]
            if offset is None:
                break
        row = next(i for i in items if i["kind"] == "task" and i["id"] == "compare")
        self.assertIn("result-progress", row["result_progress_argv"])
        self.assertIn("result-report", row["result_report_argv"])

    def test_compare_rejects_concurrent_source_revision_at_atomic_commit(self):
        from mining_research_kernel.result_comparison import compare_results
        refs = self.import_pair()
        store = ResearchStore(self.root)
        original_commit = ResearchStore.commit
        injected = False

        def race(selected_store, operation_id, producer, records, *args, **kwargs):
            nonlocal injected
            if not injected and any(r["type"] == "TaskState" and r["id"] == "race" for r in records):
                injected = True
                changed = store.latest_record(refs[0], "Asset")
                old_revision = changed["revision"]
                changed["revision"] += 1
                changed["status"] = "changed_during_commit"
                original_commit(store, "concurrent-result-update", {"role": "test", "model": "race"},
                                [changed], expected_revisions={refs[0]: old_revision})
            return original_commit(selected_store, operation_id, producer, records, *args, **kwargs)

        with patch.object(ResearchStore, "commit", race):
            with self.assertRaisesRegex(ValueError, "revision"):
                compare_results(self.root, task_id="race", question="Compare with a source race",
                    baseline_asset_ref=refs[0], candidate_asset_ref=refs[1], point_ids=["P1"], task_context="synthetic")
        self.assertTrue(injected)
        self.assertIsNone(store.latest_record("race", "TaskState"))

    def test_import_can_replay_after_commit_response_is_lost(self):
        from mining_research_kernel.result_comparison import import_result_csv
        original_commit = ResearchStore.commit
        interrupted = False

        def interrupted_commit(store, operation_id, producer, records, *args, **kwargs):
            nonlocal interrupted
            result = original_commit(store, operation_id, producer, records, *args, **kwargs)
            if not interrupted and any(r["type"] == "TaskState" and r["id"] == "lost-response"
                                       and r.get("state") == "completed" for r in records):
                interrupted = True
                raise OSError("simulated response loss after commit")
            return result

        params = dict(task_id="lost-response", question="Read selected export", csv_path="baseline.csv",
                      metadata=self.metadata("baseline"), task_context="synthetic")
        with patch.object(ResearchStore, "commit", interrupted_commit):
            with self.assertRaises(OSError):
                import_result_csv(self.root, **params)
        self.assertTrue(interrupted)
        self.paths[0].unlink()
        before = self.records()
        with patch("mining_research_kernel.result_comparison.read_result_csv", side_effect=AssertionError("no fresh source read")):
            replay = import_result_csv(self.root, **params)
        self.assertTrue(replay["replayed"])
        self.assertEqual(before, self.records())

    def test_offline_demo_links_saved_script_and_documentation_context(self):
        root = self.base / "independent result demo"
        args = [sys.executable, "-S", "-B", "-X", "utf8", str(REPO / "examples/result_comparison/demo.py"), str(root)]
        result = subprocess.run(args, cwd=self.base, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        receipt = json.loads(result.stdout)
        self.assertTrue(receipt["source_unchanged"])
        self.assertTrue(receipt["fresh_process_recovery"])
        report = (root / receipt["report"]).read_text(encoding="utf-8")
        self.assertIn("synthetic-script-review-01", report)
        self.assertIn("synthetic-assignment-reading", report)
        self.assertIn("script-review-teaching.html", report)
        self.assertIn("assign-elastic", report)
        self.assertIn("9.6.44", report)
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        repeated = subprocess.run(args, cwd=self.base, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(2, repeated.returncode)
        self.assertEqual(before, {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()})

    def test_historical_comparison_keeps_source_versions_after_valid_capture_revision(self):
        refs = self.import_pair()
        original = json.loads(self.cli(*self.compare_args(refs)))
        report_before = self.cli("result-report", "--task-id", "compare")
        store = ResearchStore(self.root)
        asset = store.latest_record(refs[0], "Asset")
        evidence = store.latest_record(asset["payload"]["evidence_id"], "Evidence")
        edge = next(rel for tx in store.list_transactions() for rel in tx["relationships"]
                    if rel["relation"] == "evidence_derived_from_asset" and rel["from_id"] == evidence["id"])
        asset["revision"] += 1
        asset["payload"]["metadata"]["unit"] = "m"
        asset["content_sha256"] = hashlib.sha256(json.dumps(asset["payload"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
        evidence["revision"] += 1
        edge["revision"] += 1
        edge["from_revision"], edge["to_revision"] = evidence["revision"], asset["revision"]
        store.commit("source-metadata-revision", {"role": "test", "model": "fixture"}, [asset, evidence], [edge])
        self.assertEqual(report_before, self.cli("result-report", "--task-id", "compare"))
        replay = json.loads(self.cli(*self.compare_args(refs)))
        self.assertTrue(replay["replayed"])
        self.assertEqual(original["comparison"], replay["comparison"])
        changed = json.loads(self.cli(*self.compare_args(refs, task="compare-revised")))
        self.assertEqual("INSUFFICIENT", changed["comparison"]["status"])
        self.assertTrue(all(p["delta"] is None for p in changed["comparison"]["points"]))

    def test_production_comparison_rejects_synthetic_related_context(self):
        from mining_research_kernel.result_comparison import import_result_csv, compare_results
        self.import_pair()
        refs = []
        for name in ("baseline", "candidate"):
            capture = import_result_csv(self.root, task_id=f"provided-{name}", question="Read provided test fixture",
                csv_path=f"{name}.csv", metadata={**self.metadata(name), "origin": "provided_export"})
            refs.append(capture["asset_refs"][0])
        before = self.records()
        with self.assertRaisesRegex(ValueError, "synthetic related tasks"):
            compare_results(self.root, task_id="bad-context", question="Reject synthetic background in production",
                baseline_asset_ref=refs[0], candidate_asset_ref=refs[1], point_ids=["P1"],
                related_task_ids=["import-baseline"])
        self.assertEqual(before, self.records())


if __name__ == "__main__":
    unittest.main()
