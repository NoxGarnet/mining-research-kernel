import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.cognition import CoreCognition
from mining_research_kernel.r2_workflow import task_start
from mining_research_kernel.task_engine import TaskEngine
from providers.execution import DisabledExecutionProvider
from workflows.flac3d import build_flac3d_workflow_pack


PROJECT = {
    "project_id": "r7-project",
    "product": "flac3d",
    "product_version": "9.6.44",
    "entry": "START.md",
    "baseline": "cases/main.dat",
    "execution": {"provider": "disabled"},
}
PAGE = "flac3d/zone/doc/manual/zone_commands/cmd_zone.list.html"


def verified_documentation(*, status="VERIFIED", trust="official_local",
                           task_context="production"):
    command = "zone list"
    anchor = "command:zone.list"
    canonical = {
        "product": "flac3d", "product_version": "9.6.44", "topic": PAGE,
        "command": command, "source": None, "anchor": anchor,
        "task_context": task_context,
    }
    query_sha256 = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return {
        "status": status,
        "coverage_scope": "command_name_only",
        "citation": {
            "status": status,
            "trust_class": trust,
            "source_id": "host.local.flac3d.documentation",
            "product": "flac3d",
            "document_family": "9.6",
            "document_build": "9.6.44",
            "product_version": "9.6.44",
            "page": PAGE,
            "command": command,
            "anchor": anchor,
            "sha256_body": "a" * 64,
            "query_sha256": query_sha256,
            "fetched_at": "2026-09-06T00:00:00Z",
            "checked_at": "2026-09-06T00:00:01Z",
        },
    }


class R7DocumentationGateTests(unittest.TestCase):
    def start(self, task_type, *, gates=None, documentation_result=None,
              task_context="production", workflow_request=None):
        request = {
            "task_id": "r7-task",
            "project_id": PROJECT["project_id"],
            "workflow_id": "mining_research_kernel.workflow.flac3d",
            "task_type": task_type,
            "maturity": "known_workflow",
            "max_runs": 1,
            "page": PAGE,
            "command": "zone list",
            "task_context": task_context,
        }
        if gates is not None:
            request["verification_gates"] = gates
        if workflow_request:
            request.update(workflow_request)
        pack = build_flac3d_workflow_pack(
            PROJECT, request, {"execution": DisabledExecutionProvider()}
        )
        return TaskEngine(
            copy.deepcopy(PROJECT), pack,
            {"execution": DisabledExecutionProvider()},
            documentation_result=documentation_result,
        ).start(request)

    def test_explicit_documentation_gate_blocks_without_result(self):
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"],
        )
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])
        self.assertFalse(packet["next_action"]["executable"])
        self.assertEqual("documentation_provider_unavailable", packet["stop_reason"])
        self.assertEqual("provide_matching documentation citation", packet["resume_condition"])
        self.assertEqual("CANNOT_VERIFY", packet["gate_statuses"]["documentation"]["status"])
        self.assertEqual("documentation_provider_unavailable", packet["gate_statuses"]["documentation"]["reason"])

    def test_matching_source_normalizes_current_gate_and_preserves_source_check(self):
        source_check = verified_documentation()
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"], documentation_result=source_check,
        )
        self.assertEqual("ready", packet["state"])
        self.assertEqual("VERIFIED", packet["documentation_status"])
        self.assertEqual("VERIFIED", packet["gate_statuses"]["documentation"]["status"])
        self.assertEqual("documentation_verified_for_task_context", packet["gate_statuses"]["documentation"]["reason"])
        self.assertEqual(source_check, packet["documentation_result"])
        self.assertEqual("command_name_only", packet["documentation_result"]["coverage_scope"])
        self.assertEqual("a" * 64, packet["documentation_result"]["citation"]["sha256_body"])

    def test_verified_source_with_version_or_query_mismatch_is_currently_unverified(self):
        wrong_version = verified_documentation()
        wrong_version["citation"]["document_build"] = "9.6.43"
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"], documentation_result=wrong_version,
        )
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])
        self.assertEqual("CANNOT_VERIFY", packet["gate_statuses"]["documentation"]["status"])
        self.assertEqual("documentation_product_version_mismatch", packet["stop_reason"])
        self.assertEqual("documentation_product_version_mismatch", packet["gate_statuses"]["documentation"]["reason"])
        self.assertEqual("VERIFIED", packet["documentation_result"]["status"])

        wrong_query = verified_documentation()
        wrong_query["citation"]["query_sha256"] = "b" * 64
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"], documentation_result=wrong_query,
        )
        self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])
        self.assertEqual("documentation_query_digest_mismatch", packet["gate_statuses"]["documentation"]["reason"])

    def test_unavailable_source_result_is_currently_unverified_and_traceable(self):
        source_check = {
            "status": "CANNOT_VERIFY", "coverage_scope": "none",
            "stop_reason": "page_not_registered",
            "citation": {"status": "CANNOT_VERIFY", "source_id": "host.local.flac3d.documentation"},
        }
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"], documentation_result=source_check,
        )
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])
        self.assertEqual("CANNOT_VERIFY", packet["gate_statuses"]["documentation"]["status"])
        self.assertEqual("page_not_registered", packet["stop_reason"])
        self.assertEqual("page_not_registered", packet["gate_statuses"]["documentation"]["reason"])
        self.assertEqual(source_check, packet["documentation_result"])

    def test_independent_failure_gate_keeps_documentation_reason_separate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            init_project(root, "r7-independent")
            config = root / "flac3d_project.yaml"
            config.write_text(config.read_text(encoding="utf-8").replace('"product_version": "unknown"', '"product_version": "9.6.44"'), encoding="utf-8")
            task_id = "r7-independent-task"
            route_id = task_id + ".route.1"
            CoreCognition(root).record_failure(
                {"failure_id": "r7-open-failure", "observable_failure": "independent gate is open",
                 "task_id": task_id, "route_id": route_id, "resolution_status": "open"},
                "r7-open-failure-op",
            )
            packet = task_start(root, {
                "task_id": task_id,
                "question_statement": "Does the independent gate remain separate?",
                "claim_statement": "The documentation gate and failure gate retain separate reasons.",
                 "task_type": "mining_research_kernel.task.syntax_change",
                "workflow_id": "mining_research_kernel.workflow.flac3d",
                "maturity": "known_workflow", "max_runs": 1,
                "task_context": "production", "topic": PAGE, "page": PAGE,
                "command": "zone list", "anchor": "command:zone.list",
                "verification_gates": ["documentation"],
            }, verified_documentation())
            self.assertEqual("blocked", packet["state"])
            self.assertEqual("unresolved_failure_gate", packet["stop_reason"])
            self.assertEqual("VERIFIED", packet["documentation_status"])
            self.assertEqual("VERIFIED", packet["gate_statuses"]["documentation"]["status"])
            self.assertEqual("documentation_verified_for_task_context", packet["gate_statuses"]["documentation"]["reason"])

    def test_static_check_without_explicit_documentation_keeps_existing_behavior(self):
        packet = self.start("mining_research_kernel.task.static_check")
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("static_check_unimplemented", packet["stop_reason"])
        self.assertFalse(packet["next_action"]["executable"])
        self.assertEqual("PENDING", packet["gate_statuses"]["static_check"]["status"])
        self.assertTrue(packet["gate_statuses"]["static_check"]["applicable"])
        self.assertFalse(packet["capability_statuses"]["static_check"]["available"])
        self.assertEqual("NOT_APPLICABLE", packet["documentation_status"])
        self.assertNotIn("documentation", packet["verification_gates"])

    def test_syntax_change_still_requires_documentation(self):
        packet = self.start("mining_research_kernel.task.syntax_change")
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])

    def test_only_actual_production_verified_result_can_pass(self):
        synthetic = verified_documentation(
            status="SYNTHETIC_VERIFIED", trust="synthetic",
            task_context="synthetic",
        )
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"], documentation_result=synthetic,
        )
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])
        self.assertEqual("CANNOT_VERIFY", packet["gate_statuses"]["documentation"]["status"])
        self.assertEqual("documentation_not_verified_for_task_context", packet["stop_reason"])

        self_filled = verified_documentation()
        self_filled["status"] = "VERIFIED"
        self_filled["citation"]["status"] = "VERIFIED"
        self_filled["citation"]["trust_class"] = "self_filled"
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            gates=["documentation"], documentation_result=self_filled,
        )
        self.assertEqual("blocked", packet["state"])

    def test_workflow_and_request_gates_are_union_and_request_cannot_relax(self):
        packet = self.start(
            "mining_research_kernel.task.syntax_change",
            workflow_request={"verification_gates": []},
        )
        self.assertEqual(["documentation"], packet["verification_gates"])
        self.assertEqual("blocked", packet["state"])


if __name__ == "__main__":
    unittest.main()
