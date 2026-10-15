import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import (
    research_map_rebuild, task_record_evidence_review, task_start,
)


class MaterialTaskLinkingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "material_linking")
        self.repo = Path(__file__).parents[1]
        self.env = os.environ.copy()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def tearDown(self):
        self.temp.cleanup()

    def _register(self, content="original source\n"):
        source = self.root / "cases" / "selected-source.dat"
        source.write_text(content, encoding="utf-8")
        result = ResearchStore(self.root).register_local_material(
            "cases/selected-source.dat", "project_record"
        )
        return source, result["asset"]["id"], result["evidence"]["id"]

    def _request(self, task_id, asset_id, evidence_id, task_type="evidence_review"):
        return {
            "task_id": task_id,
            "question_statement": "Which registered material is available for the bounded read-only review?",
            "claim_statement": "The task records material provenance separately from reading and verification.",
            "task_type": f"mining_research_kernel.task.{task_type}",
            "maturity": "exploratory",
            "max_runs": 1,
            "task_context": "production",
            "asset_refs": [asset_id],
            "evidence_refs": [evidence_id],
            "material_locations": {
                asset_id: {"path": "cases/selected-source.dat", "path_kind": "project_relative"},
            },
        }

    def _assessment(self, packet):
        material = packet["material_reads"][0]
        return {
            "scope": "material_reading_and_evidence_synthesis_only",
            "material_reads": [{
                "asset_id": material["asset_id"],
                "evidence_refs": material["evidence_refs"],
                "observed_sha256": material["content_sha256"],
                "reading_status": "READ_WITH_LIMITS",
                "verification_status": "NOT_VERIFIED",
                "locator": {"kind": "line", "value": "synthetic source lines 1-2"},
                "summary": "Read the selected synthetic source and recorded its bounded content.",
                "numeric_check_status": "NOT_APPLICABLE",
                "scientific_validation_status": "NOT_VERIFIED",
                "gaps": ["synthetic source has no scientific validation"],
            }],
            "material_gaps": [],
            "judgment": {
                "status": "PROVISIONAL_WITH_GAPS",
                "summary": "The material is read and traceable, but the claim remains unverified.",
                "supported_evidence": ["the selected source content"],
                "gaps": ["no independent validation"],
                "next_action": {
                    "action": "obtain an independent validation input",
                    "executable": False,
                },
            },
        }

    def test_valid_refs_enter_required_reads_without_static_gate(self):
        source, asset_id, evidence_id = self._register()
        packet = task_start(self.root, self._request("linked-task", asset_id, evidence_id))

        self.assertEqual("ready", packet["state"])
        self.assertNotIn("static_check", packet["verification_gates"])
        self.assertNotIn("START.md", packet["required_reads"])
        self.assertNotIn("cases/main.dat", packet["required_reads"])
        self.assertIn(f"asset:{asset_id}", packet["required_reads"])
        self.assertIn(f"evidence:{evidence_id}", packet["required_reads"])
        self.assertEqual(packet["required_reads"], packet["next_action"]["input_refs"])
        self.assertEqual("hash_match", packet["material_reads"][0]["content_status"])
        self.assertEqual("NOT_READ", packet["material_reads"][0]["reading_status"])
        self.assertEqual("NOT_VERIFIED", packet["material_reads"][0]["verification_status"])
        self.assertEqual("cases/selected-source.dat",
                         packet["material_reads"][0]["requested_locator"]["path"])
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),
                         packet["material_reads"][0]["content_sha256"])
        self.assertEqual("read-only material assessment", packet["next_action"]["expected_outputs"][0])

        view = research_map_rebuild(self.root)
        relations = {edge["relation"] for edge in view["edges"]}
        self.assertIn("route_reads_asset", relations)
        self.assertIn("route_reads_evidence", relations)

    def test_invalid_asset_ref_is_rejected_before_task_commit(self):
        with self.assertRaisesRegex(ValueError, "unknown asset_ref"):
            task_start(self.root, self._request("invalid-task", "asset.missing", "evidence.missing"))
        self.assertIsNone(ResearchStore(self.root).latest_record("invalid-task", "TaskState"))

    def test_explicit_material_list_is_all_or_nothing_and_does_not_expand_directory(self):
        _source, asset_id, evidence_id = self._register()
        request = self._request("batch-link-task", asset_id, evidence_id)
        request["asset_refs"].append("asset.missing")
        request["evidence_refs"].append("evidence.missing")
        before = {
            path.name: path.read_bytes()
            for path in (self.root / "research" / "records").glob("*.json")
        }

        with self.assertRaisesRegex(ValueError, "unknown asset_ref"):
            task_start(self.root, request)

        after = {
            path.name: path.read_bytes()
            for path in (self.root / "research" / "records").glob("*.json")
        }
        self.assertEqual(before, after)
        self.assertIsNone(ResearchStore(self.root).latest_record("batch-link-task", "TaskState"))

    def test_missing_registered_source_blocks_without_run(self):
        source, asset_id, evidence_id = self._register()
        source.unlink()
        packet = task_start(self.root, self._request("missing-task", asset_id, evidence_id))

        self.assertEqual("blocked", packet["state"])
        self.assertEqual("material_source_missing", packet["stop_reason"])
        self.assertEqual(0, packet["runs_used"])
        self.assertEqual("missing", packet["material_reads"][0]["content_status"])
        self.assertEqual("material_source_missing", packet["material_gaps"][0]["reason"])
        self.assertFalse(packet["next_action"]["executable"])

    def test_changed_registered_source_blocks_without_relabeling_verification(self):
        source, asset_id, evidence_id = self._register()
        source.write_text("changed source\n", encoding="utf-8")
        packet = task_start(self.root, self._request("changed-task", asset_id, evidence_id))

        self.assertEqual("blocked", packet["state"])
        self.assertEqual("material_content_changed", packet["stop_reason"])
        self.assertEqual("hash_mismatch", packet["material_reads"][0]["content_status"])
        self.assertEqual("NOT_VERIFIED", packet["material_reads"][0]["verification_status"])
        self.assertEqual(0, packet["runs_used"])

    def test_cross_process_inspect_recovers_material_refs_and_status(self):
        _source, asset_id, evidence_id = self._register()
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(
            self._request("cross-process-task", asset_id, evidence_id),
        ), encoding="utf-8")

        started = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "task-start",
             "--project-root", str(self.root), "--request-json", "@" + str(request_path)],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, started.returncode, started.stderr)
        self.assertEqual("ready", json.loads(started.stdout)["state"])

        inspected = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "task-inspect",
             "--project-root", str(self.root), "cross-process-task"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, inspected.returncode, inspected.stderr)
        packet = json.loads(inspected.stdout)
        self.assertEqual("ready", packet["state"])
        self.assertEqual([asset_id], packet["asset_refs"])
        self.assertEqual([evidence_id], packet["evidence_refs"])
        self.assertEqual("hash_match", packet["material_reads"][0]["content_status"])
        self.assertIn(f"asset:{asset_id}", packet["next_action"]["input_refs"])

    def test_static_check_remains_blocked_when_materials_are_linked(self):
        _source, asset_id, evidence_id = self._register()
        packet = task_start(self.root, self._request(
            "static-task", asset_id, evidence_id, task_type="static_check"
        ))

        self.assertEqual("blocked", packet["state"])
        self.assertEqual("static_check_unimplemented", packet["stop_reason"])
        self.assertIn("static_check", packet["verification_gates"])
        self.assertEqual([asset_id], packet["asset_refs"])
        self.assertEqual("hash_match", packet["material_reads"][0]["content_status"])
        self.assertEqual(0, packet["runs_used"])

    def test_host_read_and_judgment_persist_without_run_or_verification(self):
        _source, asset_id, evidence_id = self._register()
        packet = task_start(self.root, self._request("review-task", asset_id, evidence_id))
        recorded = task_record_evidence_review(
            self.root, "review-task", "record-review", self._assessment(packet)
        )

        self.assertEqual("completed", recorded["state"])
        self.assertEqual("recorded", recorded["review_status"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", recorded["research_judgment_status"])
        self.assertEqual("READ_WITH_LIMITS", recorded["material_reads"][0]["reading_status"])
        self.assertEqual("host_reloaded_hash_match", recorded["material_reads"][0]["content_status"])
        self.assertEqual(0, recorded["runs_used"])
        self.assertFalse(recorded["operation_result"]["run_created"])
        self.assertFalse(recorded["operation_result"]["verification_created"])
        decision = ResearchStore(self.root).latest_record(recorded["review_record_ref"], "Decision")
        self.assertIsNotNone(decision)
        self.assertEqual("PROVISIONAL_WITH_GAPS", decision["judgment"]["status"])
        self.assertEqual("material_reading_and_evidence_synthesis_only", decision["scope"]["kind"])
        view = research_map_rebuild(self.root)
        self.assertIn("Decision", {node["type"] for node in view["nodes"]})
        self.assertIn("decision_records_evidence", {edge["relation"] for edge in view["edges"]})

    def test_new_process_recovers_persisted_judgment_for_new_task(self):
        _source, asset_id, evidence_id = self._register()
        packet = task_start(self.root, self._request("review-task", asset_id, evidence_id))
        recorded = task_record_evidence_review(
            self.root, "review-task", "record-review", self._assessment(packet)
        )
        request_path = self.root / "recovery-request.json"
        request_path.write_text(json.dumps({
            **self._request("recovery-task", asset_id, evidence_id),
            "refs": {"decisions": [recorded["review_record_ref"]]},
            "input": {"continue_from_decision": recorded["review_record_ref"]},
        }), encoding="utf-8")
        started = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "task-start",
             "--project-root", str(self.root), "--request-json", "@" + str(request_path)],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, started.returncode, started.stderr)
        recovered = json.loads(started.stdout)
        self.assertEqual("ready", recovered["state"])
        self.assertEqual([recorded["review_record_ref"]], recovered["relevant_decision_refs"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", recovered["recovered_decisions"][0]["judgment"]["status"])
        self.assertIn("independent validation", recovered["recovered_decisions"][0]["judgment"]["gaps"][0])

    def test_evidence_review_rejects_unmatched_hash_and_scientific_pass(self):
        _source, asset_id, evidence_id = self._register()
        packet = task_start(self.root, self._request("review-task", asset_id, evidence_id))
        assessment = self._assessment(packet)
        assessment["material_reads"][0]["observed_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "does not match registered Asset hash"):
            task_record_evidence_review(self.root, "review-task", "bad-hash", assessment)

        assessment = self._assessment(packet)
        assessment["material_reads"][0]["verification_status"] = "VERIFIED"
        with self.assertRaisesRegex(ValueError, "cannot mark scientific verification complete"):
            task_record_evidence_review(self.root, "review-task", "bad-verification", assessment)

    def test_evidence_review_distinguishes_reused_persisted_reading(self):
        _source, asset_id, evidence_id = self._register()
        packet = task_start(self.root, self._request("reuse-task", asset_id, evidence_id))
        assessment = self._assessment(packet)
        assessment["material_reads"][0]["reading_status"] = "REUSED_FROM_PERSISTED_RECORD"
        assessment["material_reads"][0]["reused_from_decision"] = "decision.prior.reading"
        recorded = task_record_evidence_review(
            self.root, "reuse-task", "record-reuse", assessment
        )
        self.assertEqual("reused_persisted_hash", recorded["material_reads"][0]["content_status"])
        self.assertEqual("decision.prior.reading",
                         recorded["material_reads"][0]["reading"]["reused_from_decision"])


if __name__ == "__main__":
    unittest.main()
