import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project, init_synthetic_project
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_complete, task_inspect, task_start
from mining_research_kernel.task_engine import TaskEngine
from providers.execution import DisabledExecutionProvider
from workflows.flac3d import build_flac3d_workflow_pack


PROJECT = {
    "project_id": "capability-project",
    "product": "flac3d",
    "product_version": "9.6.44",
    "entry": "START.md",
    "baseline": "cases/main.dat",
    "execution": {"provider": "disabled"},
}
PAGE = "flac3d/zone/doc/manual/zone_commands/cmd_zone.list.html"


def verified_documentation():
    command = "zone list"
    anchor = "command:zone.list"
    query = {
        "product": "flac3d", "product_version": "9.6.44", "topic": PAGE,
        "command": command, "source": None, "anchor": anchor,
        "task_context": "production",
    }
    query_sha256 = hashlib.sha256(json.dumps(
        query, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    citation = {
        "status": "VERIFIED", "trust_class": "official_local",
        "source_id": "host.local.flac3d.documentation", "product": "flac3d",
        "document_family": "9.6", "document_build": "9.6.44",
        "product_version": "9.6.44", "page": PAGE, "command": command,
        "anchor": anchor, "sha256_body": "a" * 64,
        "query_sha256": query_sha256, "fetched_at": "2026-09-06T00:00:00Z",
        "checked_at": "2026-09-06T00:00:01Z",
    }
    return {"status": "VERIFIED", "coverage_scope": "command_name_only", "citation": citation}


class TaskCapabilityBoundaryTests(unittest.TestCase):
    def test_new_production_flac3d_static_check_is_blocked_but_gate_is_pending(self):
        request = {
            "task_id": "capability-task", "project_id": PROJECT["project_id"],
            "workflow_id": "mining_research_kernel.workflow.flac3d",
            "task_type": "mining_research_kernel.task.static_check",
            "maturity": "known_workflow", "max_runs": 1,
        }
        pack = build_flac3d_workflow_pack(PROJECT, request, {"execution": DisabledExecutionProvider()})
        packet = TaskEngine(PROJECT, pack, {"execution": DisabledExecutionProvider()}).start(request)
        self.assertEqual("blocked", packet["state"])
        self.assertFalse(packet["next_action"]["executable"])
        self.assertEqual("static_check_unimplemented", packet["next_action"]["reason"])
        self.assertEqual("static_check_unimplemented", packet["stop_reason"])
        self.assertEqual("PENDING", packet["gate_statuses"]["static_check"]["status"])
        self.assertTrue(packet["gate_statuses"]["static_check"]["applicable"])
        self.assertFalse(packet["capability_statuses"]["static_check"]["available"])

    def test_synthetic_static_check_remains_available(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "synthetic"
            init_synthetic_project(root, "synthetic-capability")
            packet = task_start(root, {
                "task_id": "synthetic-static", "workflow_id": "synthetic",
                "question_statement": "Can the fixture be checked?",
                "claim_statement": "The fixture check remains available.",
                "task_type": "mining_research_kernel.task.static_check",
                "maturity": "exploratory", "max_runs": 1, "task_context": "synthetic",
            })
            self.assertEqual("ready", packet["state"])
            self.assertTrue(packet["next_action"]["executable"])
            self.assertTrue(packet["capability_statuses"]["static_check"]["available"])

    def test_documentation_only_task_is_not_blocked_by_static_capability(self):
        request = {
            "task_id": "documentation-task", "project_id": PROJECT["project_id"],
            "workflow_id": "mining_research_kernel.workflow.flac3d",
            "task_type": "mining_research_kernel.task.syntax_change",
            "maturity": "known_workflow", "max_runs": 1, "page": PAGE,
            "command": "zone list", "task_context": "production",
        }
        pack = build_flac3d_workflow_pack(PROJECT, request, {"execution": DisabledExecutionProvider()})
        packet = TaskEngine(PROJECT, pack, {"execution": DisabledExecutionProvider()},
                            documentation_result=verified_documentation()).start(request)
        self.assertEqual("ready", packet["state"])
        self.assertTrue(packet["next_action"]["executable"])
        self.assertNotIn("static_check", packet["verification_gates"])

    def test_legacy_inspect_projects_current_static_capability_without_rewriting_packet(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "legacy"
            init_project(root, "legacy-capability")
            task_id = "legacy-static"
            task_start(root, {
                "task_id": task_id,
                "question_statement": "Does the old packet remain recoverable?",
                "claim_statement": "The old packet retains its historical snapshot.",
                "task_type": "mining_research_kernel.task.static_check",
                "maturity": "known_workflow", "max_runs": 1,
            })
            store = ResearchStore(root)
            prior = store.latest_record(task_id, "TaskState")
            legacy_packet = copy.deepcopy(prior["packet"])
            legacy_packet.pop("capability_statuses", None)
            legacy_packet["state"] = "ready"
            legacy_packet.pop("stop_reason", None)
            legacy_packet.pop("resume_condition", None)
            legacy_packet["stop_conditions"] = []
            legacy_packet["next_action"] = {
                "action_id": legacy_packet["task_type"] + ".run", "executable": True,
                "input_refs": legacy_packet["required_reads"],
                "expected_outputs": ["structured Run observation"],
                "preconditions": [],
            }
            record = copy.deepcopy(prior)
            record["revision"] += 1
            record["packet"] = legacy_packet
            store.commit("legacy-packet-snapshot", {"role": "planning_agent", "model": "test"},
                         [record], expected_revisions={task_id: prior["revision"]})

            inspected = task_inspect(root, task_id)
            self.assertFalse(inspected["next_action"]["executable"])
            self.assertEqual("static_check_unimplemented", inspected["next_action"]["reason"])
            self.assertTrue(inspected["historical_next_action"]["executable"])
            self.assertEqual("static_check_unimplemented",
                             inspected["current_capability_statuses"]["static_check"]["reason"])
            persisted = ResearchStore(root).latest_record(task_id, "TaskState")["packet"]
            self.assertNotIn("current_next_action", persisted)
            self.assertNotIn("capability_statuses", persisted)
            self.assertTrue(persisted["next_action"]["executable"])

    def test_task_complete_cannot_bypass_unimplemented_static_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "blocked"
            init_project(root, "blocked-capability")
            task_id = "blocked-static"
            packet = task_start(root, {
                "task_id": task_id,
                "question_statement": "Can production static checking run?",
                "claim_statement": "Production static checking is available.",
                "task_type": "mining_research_kernel.task.static_check",
                "maturity": "known_workflow", "max_runs": 1,
            })
            route_id = packet["routes"][0]
            completion = {
                "route_ids": [route_id],
                "run_reference_ids": {route_id: "runref-forged"},
                "verification_ids": {route_id: ["verification-forged"]},
                "verification_gate_coverage": {route_id: {"static_check": [{
                    "verification_id": "verification-forged",
                    "verification_gate_id": "static_check",
                }]}},
                "evidence_refs": {route_id: ["evidence-forged"]},
                "output_refs": {route_id: ["research/result.md"]},
            }
            with self.assertRaisesRegex(ValueError, "required capability unavailable: static_check_unimplemented"):
                task_complete(root, task_id, "bypass-static", completion)
            current = ResearchStore(root).latest_record(task_id, "TaskState")
            self.assertEqual(1, current["revision"])
            self.assertEqual("blocked", current["state"])


if __name__ == "__main__":
    unittest.main()
