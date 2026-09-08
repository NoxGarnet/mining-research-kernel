import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.routes import RouteLifecycle, RouteLifecycleError


class R3RouteLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "r3_project")
        self.store = ResearchStore(self.root)
        self.question = {
            "schema_version": 1, "type": "ResearchQuestion", "id": "question-1", "revision": 1,
            "project_id": "r3_project", "scope": {"study": "fixture"},
            "source_refs": ["fixture:question"], "statement": "Which route is useful?", "status": "active",
        }
        self.claim = {
            "schema_version": 1, "type": "Claim", "id": "claim-1", "revision": 1,
            "project_id": "r3_project", "scope": {"study": "fixture"},
            "source_refs": ["fixture:claim"], "statement": "The route has bounded value.", "status": "proposed",
        }
        self.store.commit("seed-question", {"role": "planning_agent", "model": "test"}, [self.question, self.claim])
        self.routes = RouteLifecycle(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def route(self, route_id, *, write_set, budget=2, parent_route_id=None):
        value = {
            "route_id": route_id, "question_id": "question-1", "hypothesis_id": None,
            "claim_id": "claim-1",
            "workflow_id": "workflow.flac3d", "method_id": "method.synthetic",
            "budget": budget, "write_set": write_set, "stop_conditions": ["budget_exhausted"],
        }
        if parent_route_id is not None:
            value["parent_route_id"] = parent_route_id
        return value

    def test_same_question_is_bounded_by_project_policy(self):
        config_path = self.root / "flac3d_project.yaml"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["route_policy"] = {"max_active_routes": 2}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.routes = RouteLifecycle(self.root)
        for index in range(1, 4):
            self.routes.propose(self.route(f"route-{index}", write_set=[f"outputs/{index}.json"]), f"propose-{index}")
        self.routes.reserve("route-1", "reserve-1")
        self.routes.reserve("route-2", "reserve-2")
        blocked = self.routes.reserve("route-3", "reserve-3")
        self.assertEqual("blocked", blocked["status"])
        self.assertEqual("max_active_routes_reached", blocked["reason"])
        self.assertEqual(0, blocked["route"]["runs_used"])

    def test_agent_cannot_widen_project_route_limit(self):
        config_path = self.root / "flac3d_project.yaml"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["route_policy"] = {"max_active_routes": 4}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "from 1 to 3"):
            RouteLifecycle(self.root)

    def test_budget_failure_cannot_verify_and_reopen_preserve_consumption(self):
        self.routes.propose(self.route("route-1", write_set=["outputs/a.json"], budget=2), "propose-1")
        self.routes.reserve("route-1", "reserve-1")
        failed = self.routes.finish("route-1", "reserve-1", "failed", "finish-1",
                                    stop_reason="fixture_failed", outputs=["failure:fixture"])
        self.assertEqual("failed", failed["route"]["status"])
        self.assertEqual(1, failed["route"]["runs_used"])
        self.routes.reopen("route-1", "reopen-1")
        self.routes.reserve("route-1", "reserve-2")
        unknown = self.routes.finish("route-1", "reserve-2", "cannot_verify", "finish-2",
                                     stop_reason="official_source_missing")
        self.assertEqual("cannot_verify", unknown["route"]["status"])
        self.assertEqual(2, unknown["route"]["runs_used"])
        self.routes.reopen("route-1", "reopen-2")
        blocked = self.routes.reserve("route-1", "reserve-3")
        self.assertEqual("blocked", blocked["status"])
        self.assertEqual("route_budget_exhausted", blocked["reason"])

    def test_child_routes_share_task_budget(self):
        packet = {
            "schema_version": 1, "type": "TaskPacket", "task_id": "task-budget",
            "project_id": "r3_project", "max_runs": 1, "runs_used": 0,
        }
        task = {
            "schema_version": 1, "type": "TaskState", "id": "task-budget", "revision": 1,
            "project_id": "r3_project", "scope": {"study": "fixture"},
            "source_refs": ["fixture:task"], "task_id": "task-budget", "state": "ready",
            "packet": packet, "operation_results": {},
        }
        self.store.commit("seed-task-budget", {"role": "planning_agent", "model": "test"}, [task])
        first = self.route("task-route-a", write_set=["outputs/task-a.json"])
        first["task_id"] = "task-budget"
        second = self.route("task-route-b", write_set=["outputs/task-b.json"])
        second["task_id"] = "task-budget"
        second["parent_route_id"] = "task-route-a"
        self.routes.propose(first, "propose-task-a")
        self.routes.propose(second, "propose-task-b")
        self.assertEqual("reserved", self.routes.reserve("task-route-a", "reserve-task-a")["status"])
        blocked = self.routes.reserve("task-route-b", "reserve-task-b")
        self.assertEqual("task_budget_exhausted", blocked["reason"])
        self.assertEqual(0, blocked["route"]["runs_used"])

    def test_write_set_conflict_blocks_without_consuming_budget(self):
        self.routes.propose(self.route("route-1", write_set=["outputs/shared.json"]), "propose-1")
        self.routes.propose(self.route("route-2", write_set=["outputs/shared.json"]), "propose-2")
        self.routes.reserve("route-1", "reserve-1")
        blocked = self.routes.reserve("route-2", "reserve-2")
        self.assertEqual("blocked", blocked["status"])
        self.assertEqual("write_set_conflict:route-1", blocked["reason"])
        self.assertEqual(0, blocked["route"]["runs_used"])
        self.routes.finish("route-1", "reserve-1", "completed", "finish-1", outputs=["asset:a"])
        self.routes.reopen("route-2", "reopen-2")
        self.assertEqual("reserved", self.routes.reserve("route-2", "reserve-3")["status"])

    def test_reservation_survives_new_service_instance_and_is_idempotent(self):
        self.routes.propose(self.route("route-1", write_set=["outputs/a.json"]), "propose-1")
        first = self.routes.reserve("route-1", "reserve-1")
        resumed = RouteLifecycle(self.root)
        repeated = resumed.reserve("route-1", "reserve-1")
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(first["route"], repeated["records"][0])
        finished = resumed.finish("route-1", "reserve-1", "completed", "finish-1", outputs=["asset:a"])
        self.assertEqual("completed", finished["route"]["status"])

    def test_parent_and_supersede_are_persisted_as_relations(self):
        self.routes.propose(self.route("route-parent", write_set=["outputs/parent.json"]), "propose-parent")
        self.routes.propose(self.route("route-child", write_set=["outputs/child.json"], parent_route_id="route-parent"), "propose-child")
        result = self.routes.supersede("route-child", "route-parent", "supersede-parent")
        self.assertEqual("superseded", result["superseded_route"]["status"])
        self.assertEqual("route-parent", result["route"]["supersedes_route_id"])
        relations = [edge["relation"] for tx in self.store.list_transactions() for edge in tx["relationships"]]
        self.assertIn("route_child_of_route", relations)
        self.assertIn("route_supersedes_route", relations)
        self.assertIn("route_targets_claim", relations)

    def test_rejection_is_a_persisted_terminal_route_state(self):
        self.routes.propose(self.route("route-rejected", write_set=["outputs/rejected.json"]), "propose-rejected")
        result = self.routes.reject("route-rejected", "reject-route", "method_out_of_scope")
        self.assertEqual("rejected", result["route"]["status"])
        self.assertEqual("method_out_of_scope", result["route"]["stop_reason"])
        with self.assertRaisesRegex(ValueError, "cannot be reserved"):
            self.routes.reserve("route-rejected", "reserve-rejected")

    def test_comparison_is_deterministic_archive_and_does_not_accept_claims(self):
        self.routes.propose(self.route("route-a", write_set=["outputs/a.json"]), "propose-a")
        self.routes.propose(self.route("route-b", write_set=["outputs/b.json"]), "propose-b")
        self.routes.reserve("route-a", "reserve-a")
        self.routes.finish("route-a", "reserve-a", "completed", "finish-a", outputs=["asset:a"])
        archive = self.routes.compare("question-1", "comparison-1", "compare-1", ["route-b", "route-a"])
        self.assertEqual(["route-a", "route-b"], archive["comparison"]["route_ids"])
        self.assertEqual("archived", archive["comparison"]["status"])
        self.assertEqual({"completed", "proposed"}, {entry["status"] for entry in archive["comparison"]["entries"]})
        self.assertNotIn("Claim", {record["type"] for record in archive["transaction"]["records"]})
        rebuilt = self.store.rebuild_research_map()
        self.assertIn("comparison-1", {node["id"] for node in rebuilt["nodes"]})
        self.assertIn("route_in_comparison", {edge["relation"] for edge in rebuilt["edges"]})

    def test_cli_can_propose_inspect_reserve_and_finish(self):
        repo = Path(__file__).parents[1]
        route_json = self.root / "route.json"
        route_json.write_text(json.dumps(self.route("route-cli", write_set=["outputs/cli.json"])), encoding="utf-8")

        def cli(*args):
            return subprocess.run([sys.executable, "mining_kernel.py", *args], cwd=repo,
                                  capture_output=True, text=True, check=False)

        proposed = cli("route-propose", "--project-root", str(self.root), "--route-json", "@" + str(route_json),
                       "--operation-id", "propose-cli")
        self.assertEqual(0, proposed.returncode, proposed.stderr)
        reserved = cli("route-reserve", "--project-root", str(self.root), "route-cli", "--operation-id", "reserve-cli")
        self.assertEqual(0, reserved.returncode, reserved.stderr)
        finished = cli("route-finish", "--project-root", str(self.root), "route-cli", "--reservation-id", "reserve-cli",
                       "--outcome", "cannot_verify", "--operation-id", "finish-cli", "--stop-reason", "no-doc")
        self.assertEqual(0, finished.returncode, finished.stderr)
        inspected = json.loads(cli("route-inspect", "--project-root", str(self.root), "route-cli").stdout)
        self.assertEqual("cannot_verify", inspected["route"]["status"])


if __name__ == "__main__":
    unittest.main()
