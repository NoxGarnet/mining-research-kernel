import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.cognition import CoreCognition
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_run_fake, task_start
from mining_research_kernel.routes import RouteLifecycle
from providers.execution import FakeExecutionProvider


REPO = Path(__file__).parents[1]


class R5AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "fresh-project"

    def tearDown(self):
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.run([sys.executable, "mining_kernel.py", *map(str, args)], cwd=REPO,
                              capture_output=True, text=True, check=False)

    def output(self, result, *, expected=0):
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def request(self, task_id="fresh-task", **extra):
        value = {"task_id": task_id, "question_statement": "Does the bounded fixture produce a stable observation?",
                 "claim_statement": "The bounded fixture produces a stable observation.",
                 "task_type": "mining_research_kernel.task.fake_execution", "task_context": "synthetic",
                 "maturity": "exploratory", "max_runs": 1, "input": {"sample": "r5"}}
        value.update(extra)
        return value

    def test_fresh_user_cli_is_cross_process_and_rebuildable(self):
        self.output(self.cli("init-flac3d-project", self.root, "--project-id", "r5_fresh", "--template", "synthetic"))
        request = json.dumps(self.request(), separators=(",", ":"))
        started = self.output(self.cli("task-start", "--project-root", self.root, "--request-json", request))
        self.assertEqual("ready", started["state"])
        self.assertEqual("mining_research_kernel.workflow.flac3d", started["workflow_id"])
        inspected = self.output(self.cli("task-inspect", "--project-root", self.root, "fresh-task"))
        self.assertEqual(started, inspected)
        ran = self.output(self.cli("task-run-fake", "--project-root", self.root, "fresh-task",
                                  "--operation-id", "fresh-run", "--fixture-id", "fixture-r5"))
        self.assertEqual("completed", ran["state"])
        self.output(self.cli("research-map-rebuild", "--project-root", self.root))

        observed = self.output(self.cli("cognition-observe", "--project-root", self.root,
                                        "--operation-id", "observe-r5", "--observation-kind", "structured_test",
                                        "--observation-json", '{"passed":true}', "--locator-json", '{"test":"r5"}',
                                        "--scope-json", '{"study":"r5"}', "--task-id", "fresh-task"))
        evidence_id = next(row["id"] for row in observed["records"] if row["type"] == "Evidence")
        proposal_path = self.root / "proposal.json"
        proposal_path.write_text(json.dumps({
            "id": "fresh-proposal", "proposal_type": "project_lesson",
            "statement": "The bounded fixture observation is repeatable.", "evidence_refs": [evidence_id],
            "scope": {"study": "r5"}, "requested_status": "provisional", "impact": "low",
            "object_ref": "fresh-task", "scope_key": "r5", "fact_key": "passed", "fact_value": True,
        }), encoding="utf-8")
        self.output(self.cli("cognition-propose", "--project-root", self.root,
                             "--proposal-json", "@" + str(proposal_path), "--operation-id", "proposal-r5"))
        cognition = self.output(self.cli("cognition-rebuild", "--project-root", self.root))
        self.assertEqual(["fresh-proposal"], [row["id"] for row in cognition["provisional"]])
        self.assertEqual("clear", self.output(self.cli("cognition-failure-gate", "--project-root", self.root,
                                                        "--task-id", "fresh-task"))["status"])

        (self.root / "research" / "map.json").unlink()
        (self.root / "research" / "core_cognition.json").unlink()
        rebuilt_map = self.output(self.cli("research-map-rebuild", "--project-root", self.root))
        rebuilt_cognition = self.output(self.cli("cognition-rebuild", "--project-root", self.root))
        self.assertNotIn("TaskState", {row["type"] for row in rebuilt_map["nodes"]})
        self.assertTrue(any(row["type"] == "RunReference" for row in rebuilt_map["nodes"]))
        self.assertEqual(["fresh-proposal"], [row["id"] for row in rebuilt_cognition["provisional"]])
        serialized = json.dumps(rebuilt_map, ensure_ascii=False) + json.dumps(rebuilt_cognition, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)

        bad = self.cli("task-start", "--project-root", self.root,
                       "--request-json", json.dumps(self.request("bad-workflow", workflow_id="unknown.workflow")))
        self.assertEqual(2, bad.returncode)
        self.assertIn("unknown workflow builder", bad.stdout)

    def test_second_domain_uses_same_task_run_and_rebuild_path(self):
        self.output(self.cli("init-synthetic-project", self.root, "--project-id", "r5_synthetic"))
        self.assertEqual("synthetic", json.loads((self.root / "flac3d_project.yaml").read_text(encoding="utf-8"))["product"])
        r2_source = (REPO / "mining_research_kernel" / "r2_workflow.py").read_text(encoding="utf-8")
        self.assertNotIn("from adapters.flac3d import discover\n", r2_source.split("def _load_project", 1)[0])
        started = self.output(self.cli("task-start", "--project-root", self.root,
                                       "--request-json", json.dumps(self.request(
                                           "synthetic-task", workflow_id="synthetic"))))
        self.assertEqual("mining_research_kernel.workflow.synthetic", started["workflow_id"])
        self.assertEqual("mining_research_kernel.method.synthetic.fake_execution",
                         ResearchStore(self.root).latest_record("synthetic-task.route.1")["method_id"])
        inspected = self.output(self.cli("task-inspect", "--project-root", self.root, "synthetic-task"))
        ran = self.output(self.cli("task-run-fake", "--project-root", self.root, "synthetic-task",
                                  "--operation-id", "synthetic-run", "--fixture-id", "synthetic-fixture"))
        self.assertEqual("completed", ran["state"])
        rebuilt = self.output(self.cli("research-map-rebuild", "--project-root", self.root))
        types = {row["type"] for row in rebuilt["nodes"]}
        self.assertNotIn("TaskState", types)
        self.assertTrue({"RunReference", "Evidence", "Verification"}.issubset(types))
        # TaskState is intentionally excluded from ResearchMap; the persisted
        # records still prove the same shared Task/Run/Verification path.
        latest = ResearchStore(self.root)
        self.assertIsNotNone(latest.latest_record("synthetic-task", "TaskState"))
        self.assertTrue(any(row["type"] == "RunReference" for tx in latest.list_transactions() for row in tx["records"]))
        self.assertTrue(any(row["type"] == "Verification" for tx in latest.list_transactions() for row in tx["records"]))
        (self.root / "research" / "map.json").unlink()
        rebuilt_again = self.output(self.cli("research-map-rebuild", "--project-root", self.root))
        self.assertEqual(rebuilt, rebuilt_again)
        self.assertEqual(inspected["routes"], ran["routes"])

    def test_two_routes_failure_budget_and_second_process_recovery(self):
        self.output(self.cli("init-flac3d-project", self.root, "--project-id", "r5_routes"))
        question = {"schema_version": 1, "type": "ResearchQuestion", "id": "r5-question", "revision": 1,
                    "project_id": "r5_routes", "scope": {"study": "r5"}, "source_refs": ["fixture:q"],
                    "statement": "Which bounded route should continue?", "status": "active"}
        claim = {"schema_version": 1, "type": "Claim", "id": "r5-claim", "revision": 1,
                 "project_id": "r5_routes", "scope": {"study": "r5"}, "source_refs": ["fixture:c"],
                 "statement": "One route may support the claim.", "status": "proposed"}
        ResearchStore(self.root).commit("r5-seed", {"role": "planning_agent", "model": "test"}, [question, claim])
        lifecycle = RouteLifecycle(self.root)
        base = {"question_id": "r5-question", "claim_id": "r5-claim", "hypothesis_id": None,
                "workflow_id": "mining_research_kernel.workflow.synthetic", "method_id": "mining_research_kernel.method.synthetic.fake_execution",
                "budget": 1, "write_set": ["outputs/shared.json"], "stop_conditions": ["budget_exhausted"]}
        for route_id in ("r5-route-failure", "r5-route-support"):
            item = dict(base, route_id=route_id)
            lifecycle.propose(item, "propose-" + route_id)
        failed = lifecycle.reserve("r5-route-failure", "reserve-failure")
        self.assertEqual("reserved", failed["status"])
        lifecycle.finish("r5-route-failure", "reserve-failure", "failed", "finish-failure",
                         stop_reason="fixture_failed", outputs=["failure:fixture"])
        lifecycle.reopen("r5-route-failure", "reopen-failure")
        stopped = lifecycle.reserve("r5-route-failure", "reserve-after-budget")
        self.assertEqual("route_budget_exhausted", stopped["reason"])
        support = lifecycle.reserve("r5-route-support", "reserve-support")
        self.assertEqual("reserved", support["status"])
        recovered = RouteLifecycle(self.root)
        repeated = recovered.reserve("r5-route-support", "reserve-support")
        self.assertTrue(repeated["idempotent"])
        recovered.finish("r5-route-support", "reserve-support", "completed", "finish-support", outputs=["support:fixture"])
        cognition = CoreCognition(self.root)
        supporting = cognition.record_mechanical_evidence(
            "structured_test", {"passed": True}, operation_id="r5-support-evidence",
            locator={"route": "r5-route-support", "observation": "supports"},
            scope={"study": "r5"}, route_id="r5-route-support")
        contradicting = cognition.record_mechanical_evidence(
            "structured_test", {"passed": False}, operation_id="r5-contradict-evidence",
            locator={"route": "r5-route-failure", "observation": "contradicts"},
            scope={"study": "r5"}, route_id="r5-route-failure")
        claim_record = ResearchStore(self.root).latest_record("r5-claim", "Claim")
        relation_records = [supporting["records"][1], contradicting["records"][1]]
        relations = []
        for evidence, relation in zip(relation_records, ("evidence_supports_claim", "evidence_contradicts_claim")):
            relations.append({"schema_version": 1, "relationship_id": "r5-edge-" + relation,
                              "revision": 1, "project_id": "r5_routes", "relation": relation,
                              "from_id": evidence["id"], "from_revision": evidence["revision"],
                              "to_id": claim_record["id"], "to_revision": claim_record["revision"],
                              "source_refs": ["r5:route-evidence"]})
        ResearchStore(self.root).commit("r5-evidence-relations",
                                        {"role": "planning_agent", "model": "r5.acceptance"}, [], relations)
        archive = recovered.compare("r5-question", "r5-comparison", "compare-r5",
                                    ["r5-route-support", "r5-route-failure"])
        self.assertEqual(["r5-route-failure", "r5-route-support"], archive["comparison"]["route_ids"])
        self.assertEqual({"blocked", "completed"}, {row["status"] for row in archive["comparison"]["entries"]})
        relation_types = {edge["relation"] for tx in ResearchStore(self.root).list_transactions()
                          for edge in tx["relationships"]}
        self.assertIn("evidence_supports_claim", relation_types)
        self.assertIn("evidence_contradicts_claim", relation_types)
        self.assertEqual("proposed", ResearchStore(self.root).latest_record("r5-claim", "Claim")["status"])

    def test_cognition_stale_queue_dedup_and_failure_scope_survive_rebuild(self):
        self.output(self.cli("init-flac3d-project", self.root, "--project-id", "r5_cognition"))
        cognition = CoreCognition(self.root)
        observed = cognition.record_mechanical_evidence("file_hash", {"sha256": "a" * 64}, operation_id="r5-observe",
                                                       locator={"file": "fixture.txt"}, scope={"study": "r5"})
        evidence_id = observed["records"][1]["id"]
        proposal = {"id": "r5-proposal-a", "proposal_type": "project_lesson", "statement": "The fixture is stable.",
                    "evidence_refs": [evidence_id], "scope": {"study": "r5"}, "requested_status": "accepted",
                    "impact": "low", "object_ref": "route-r5", "scope_key": "r5", "fact_key": "sha256", "fact_value": "a" * 64}
        second = copy.deepcopy(proposal); second["id"] = "r5-proposal-b"
        cognition.propose(proposal, "r5-proposal-op-a")
        cognition.propose(second, "r5-proposal-op-b")
        before_change = cognition.rebuild()
        self.assertEqual(["r5-proposal-a", "r5-proposal-b"], before_change["pending_review"][0]["proposal_ids"])
        asset = observed["records"][0]
        changed = copy.deepcopy(ResearchStore(self.root).latest_record(asset["id"]))
        changed["revision"] = 2; changed["content_sha256"] = "b" * 64
        ResearchStore(self.root).commit("r5-change-asset", {"role": "planning_agent", "model": "test"},
                                         [changed], expected_revisions={asset["id"]: 1})
        failure = {"failure_id": "r5-failure", "observable_failure": "fixture stopped", "object_refs": ["route-r5"],
                   "route_id": "route-r5", "resolution_status": "open"}
        cognition.record_failure(failure, "r5-failure-op")
        view_path = self.root / "research" / "core_cognition.json"
        view = cognition.rebuild(view_path.relative_to(self.root), route_id="route-r5")
        self.assertEqual(["r5-proposal-a", "r5-proposal-b"], [row["id"] for row in view["stale"]])
        self.assertEqual("blocked", cognition.failure_gate(route_id="route-r5")["status"])
        view_path.unlink()
        rebuilt = CoreCognition(self.root).rebuild(route_id="route-r5")
        self.assertEqual(["r5-failure"], [row["id"] for row in rebuilt["failures"]])

    def test_provider_replacement_and_legacy_cli_boundary(self):
        init_project(self.root, "r5_provider")
        request = self.request("provider-task")
        task_start(self.root, request)

        class EquivalentProvider(FakeExecutionProvider):
            provider_id = "host.replacement.fake"

        result = task_run_fake(self.root, "provider-task", "replacement-run", "fixture-provider",
                               fake_provider=EquivalentProvider())
        self.assertEqual("completed", result["state"])
        run_records = [record for tx in ResearchStore(self.root).list_transactions() for record in tx["records"]]
        self.assertTrue(any(record["type"] == "Verification" and record["status"] == "passed" for record in run_records))

        discover = self.cli("--workspace", self.root, "discover")
        self.assertEqual(0, discover.returncode, discover.stdout + discover.stderr)
        invalid = self.cli("task-inspect", "--project-root", self.root, "missing-task")
        self.assertEqual(2, invalid.returncode)
        self.assertIn("unknown task", invalid.stdout)


if __name__ == "__main__":
    unittest.main()
