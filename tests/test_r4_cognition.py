import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.cognition import CognitionError, CoreCognition
from mining_research_kernel.records import ResearchStore


class TrustedBoundary:
    def authorize(self, request):
        return {"authorized": True, "boundary_id": "host-review-boundary", "reviewer_label": "host"}


class R4CognitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "r4_project")
        self.cognition = CoreCognition(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def evidence(self, op="observe-1", kind="structured_test", observation=None):
        return self.cognition.record_mechanical_evidence(
            kind, observation if observation is not None else {"passed": True}, operation_id=op,
            locator={"test": op}, scope={"study": "r4"})

    def proposal(self, proposal_id, evidence_refs, **extra):
        value = {"id": proposal_id, "proposal_type": "project_lesson", "statement": "The fixture observation is repeatable.",
                 "evidence_refs": evidence_refs, "scope": {"study": "r4"}, "requested_status": "provisional",
                 "created_by": "agent", "created_by_role": "planning_agent", "created_model": "test", "impact": "low",
                 "object_ref": "fixture", "scope_key": "r4", "fact_key": "passed", "fact_value": True}
        value.update(extra)
        return value

    def test_mechanical_evidence_has_exact_asset_provenance_and_no_queue(self):
        result = self.evidence("observe-mechanical", "return_code", 0)
        self.assertFalse(result["queued_for_review"])
        view = self.cognition.rebuild()
        self.assertEqual([], view["pending_review"])
        tx = result["transaction"]
        self.assertEqual({"Asset", "Evidence"}, {r["type"] for r in tx["records"]})
        self.assertEqual(["evidence_derived_from_asset"], [e["relation"] for e in tx["relationships"]])

    def test_unproven_free_text_and_missing_evidence_do_not_become_provisional(self):
        without = self.cognition.propose({"id": "free-text", "proposal_type": "project_lesson", "statement": "Try a different mesh.",
                                          "evidence_refs": [], "scope": {"study": "r4"}, "requested_status": "provisional",
                                          "created_by": "agent", "impact": "low"}, "proposal-free")
        self.assertEqual("proposed", without["records"][0]["admitted_status"])
        evidence = self.evidence("observe-free")
        text = self.cognition.propose({"id": "free-with-evidence", "proposal_type": "project_lesson", "statement": "The mesh feels better.",
                                       "evidence_refs": [evidence["records"][1]["id"]], "scope": {"study": "r4"}, "requested_status": "provisional",
                                       "created_by": "agent", "impact": "low"}, "proposal-free-2")
        self.assertEqual("proposed", text["records"][0]["admitted_status"])

    def test_structured_low_risk_provisional_but_self_accept_is_pending(self):
        evidence = self.evidence("observe-provisional")
        evidence_id = evidence["records"][1]["id"]
        provisional = self.cognition.propose(self.proposal("provisional", [evidence_id]), "proposal-provisional")
        self.assertEqual("provisional", provisional["records"][0]["admitted_status"])
        requested = self.cognition.propose(self.proposal("self-accept", [evidence_id], requested_status="accepted"), "proposal-self-accept")
        self.assertEqual("pending_review", requested["records"][0]["admitted_status"])
        self.assertEqual([], CoreCognition(self.root).rebuild()["accepted"])
        with self.assertRaises(CognitionError):
            self.cognition.review("self-accept", "review-without-boundary", review_ref="host-ref")

    def test_only_injected_boundary_can_accept_and_review_is_audited(self):
        evidence = self.evidence("observe-review")
        evidence_id = evidence["records"][1]["id"]
        self.cognition.propose(self.proposal("reviewable", [evidence_id], requested_status="accepted"), "proposal-reviewable")
        accepted = CoreCognition(self.root, review_boundary=TrustedBoundary()).review(
            "reviewable", "review-1", review_ref="external-review-1")
        self.assertEqual("accepted", accepted["records"][0]["current_status"])
        self.assertEqual("CognitionReview", accepted["records"][1]["type"])
        self.assertEqual("acceptance_agent", accepted["transaction"]["producer"]["role"])
        self.assertEqual("accepted", CoreCognition(self.root).rebuild()["accepted"][0]["current_status"])

    def test_trusted_review_cannot_downgrade_declared_impact(self):
        evidence = self.evidence("observe-high-impact")
        self.cognition.propose(self.proposal("high-impact", [evidence["records"][1]["id"]], impact="high",
                                             requested_status="accepted"), "proposal-high-impact")
        with self.assertRaisesRegex(CognitionError, "cannot change proposal impact"):
            CoreCognition(self.root, review_boundary=TrustedBoundary()).review(
                "high-impact", "review-high-impact", review_ref="external-high-impact", impact="low")

    def test_raw_store_cannot_admit_accepted_cognition_without_review(self):
        evidence = self.evidence("observe-raw-admission")
        proposed = self.cognition.propose(
            self.proposal("raw-admission", [evidence["records"][1]["id"]], requested_status="accepted"),
            "proposal-raw-admission")
        record = copy.deepcopy(proposed["records"][0])
        record["revision"] = 2
        record["admitted_status"] = "accepted"
        record["current_status"] = "accepted"
        with self.assertRaisesRegex(ValueError, "accepted cognition requires"):
            ResearchStore(self.root).commit("raw-accepted", {"role": "acceptance_agent", "model": "agent"},
                                             [record], expected_revisions={record["id"]: 1})

    def test_cli_review_without_host_boundary_fails_closed(self):
        evidence = self.evidence("observe-cli-review")
        self.cognition.propose(self.proposal("cli-review", [evidence["records"][1]["id"]],
                                             requested_status="accepted"), "proposal-cli-review")
        result = subprocess.run(
            [sys.executable, "mining_kernel.py", "cognition-review", "--project-root", str(self.root),
             "cli-review", "--operation-id", "cli-review-op", "--review-ref", "cli-review-ref"],
            cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False)
        self.assertEqual(2, result.returncode)
        self.assertIn("trusted review boundary", result.stdout)

    def test_pending_review_is_deduplicated_by_deterministic_key(self):
        evidence = self.evidence("observe-queue")
        evidence_id = evidence["records"][1]["id"]
        first = self.proposal("queue-a", [evidence_id], requested_status="accepted")
        second = self.proposal("queue-b", [evidence_id], requested_status="accepted")
        self.cognition.propose(first, "proposal-queue-a")
        self.cognition.propose(second, "proposal-queue-b")
        queue = CoreCognition(self.root).rebuild()["pending_review"]
        self.assertEqual(1, len(queue))
        self.assertEqual(["queue-a", "queue-b"], queue[0]["proposal_ids"])

    def test_dependency_revision_and_asset_hash_change_make_view_stale(self):
        observed = self.evidence("observe-dependency", "file_hash", {"sha256": "a" * 64})
        evidence, asset = observed["records"][1], observed["records"][0]
        self.cognition.propose(self.proposal("stale-me", [evidence["id"]]), "proposal-stale")
        latest = ResearchStore(self.root).latest_record(asset["id"])
        changed = copy.deepcopy(latest)
        changed["revision"] = 2
        changed["content_sha256"] = "b" * 64
        ResearchStore(self.root).commit("change-asset", {"role": "planning_agent", "model": "test"}, [changed], expected_revisions={asset["id"]: 1})
        stale = CoreCognition(self.root).rebuild()["stale"]
        self.assertEqual(["stale-me"], [item["id"] for item in stale])

    def test_structured_conflict_is_local_and_unrelated_proposal_survives(self):
        evidence = self.evidence("observe-conflict")
        evidence_id = evidence["records"][1]["id"]
        self.cognition.propose(self.proposal("conflict-a", [evidence_id], fact_value=True), "proposal-conflict-a")
        self.cognition.propose(self.proposal("conflict-b", [evidence_id], fact_value=False), "proposal-conflict-b")
        self.cognition.propose(self.proposal("unrelated", [evidence_id], object_ref="other", fact_value=False), "proposal-unrelated")
        view = CoreCognition(self.root).rebuild()
        self.assertEqual({"conflict-a", "conflict-b"}, {p["id"] for p in view["contested"]})
        self.assertEqual({"unrelated"}, {p["id"] for p in view["proposed"]})

    def test_unscoped_fact_values_are_candidates_until_scope_is_bound(self):
        evidence = self.evidence("observe-unscoped")
        evidence_id = evidence["records"][1]["id"]
        first = self.proposal("unscoped-a", [evidence_id], fact_value=True)
        second = self.proposal("unscoped-b", [evidence_id], fact_value=False)
        first.pop("object_ref")
        first.pop("scope_key")
        second.pop("object_ref")
        second.pop("scope_key")
        self.cognition.propose(first, "proposal-unscoped-a")
        self.cognition.propose(second, "proposal-unscoped-b")
        view = self.cognition.rebuild()
        self.assertEqual({"unscoped-a", "unscoped-b"}, {p["id"] for p in view["proposed"]})
        self.assertEqual([], view["contested"])

    def test_failure_is_complete_filterable_and_survives_view_rebuild_and_new_instance(self):
        self.cognition.record_failure({"failure_id": "failure-relevant", "observable_failure": "fixture returned no output",
                                       "reproduction": [{"step": "run fixture"}], "affected_product_versions": ["9.6"],
                                       "input_assets": ["input-a"], "evidence_assets": ["asset-a"], "object_refs": ["route-a"],
                                       "task_id": "task-a", "route_id": "route-a", "run_id": None, "resolution_status": "open"}, "failure-relevant-op")
        self.cognition.record_failure({"failure_id": "failure-other", "observable_failure": "unrelated",
                                       "affected_product_versions": ["8.0"], "object_refs": ["route-b"], "task_id": "task-b", "route_id": "route-b"}, "failure-other-op")
        view_path = self.root / "research" / "core_cognition.json"
        self.cognition.rebuild(view_path.relative_to(self.root), route_id="route-a", version="9.6")
        self.assertEqual(["failure-relevant"], [f["id"] for f in json.loads(view_path.read_text(encoding="utf-8"))["failures"]])
        view_path.unlink()
        recovered = CoreCognition(self.root).rebuild(route_id="route-a")
        self.assertEqual(["failure-relevant"], [f["id"] for f in recovered["failures"]])

    def test_related_open_failure_blocks_next_action_but_unrelated_scope_is_clear(self):
        self.cognition.record_failure({"failure_id": "failure-gate", "observable_failure": "fixture did not converge",
                                       "object_refs": ["route-a"], "route_id": "route-a", "resolution_status": "open"},
                                      "failure-gate-op")
        blocked = self.cognition.failure_gate(route_id="route-a")
        self.assertEqual("blocked", blocked["status"])
        self.assertEqual(["failure-gate"], blocked["failure_ids"])
        clear = self.cognition.failure_gate(route_id="route-b")
        self.assertEqual("clear", clear["status"])
        self.assertEqual([], clear["failure_ids"])

    def test_same_operation_is_idempotent(self):
        first = self.evidence("observe-idempotent")
        second = CoreCognition(self.root).record_mechanical_evidence("structured_test", {"passed": True},
                                                                       operation_id="observe-idempotent", locator={"test": "observe-idempotent"}, scope={"study": "r4"})
        self.assertTrue(second["idempotent"])
        self.assertEqual(first["transaction"]["sequence"], second["transaction"]["sequence"])

    def test_conflicting_replay_and_unstructured_mechanics_fail_closed(self):
        with self.assertRaisesRegex(CognitionError, "passed"):
            self.cognition.record_mechanical_evidence(
                "structured_test", {"result": "looks good"}, operation_id="bad-mechanics",
                locator={"test": "bad"}, scope={"study": "r4"})
        self.evidence("observe-conflicting-replay")
        with self.assertRaisesRegex(CognitionError, "conflicting payload"):
            self.cognition.record_mechanical_evidence(
                "structured_test", {"passed": False}, operation_id="observe-conflicting-replay",
                locator={"test": "different"}, scope={"study": "r4"})


if __name__ == "__main__":
    unittest.main()
