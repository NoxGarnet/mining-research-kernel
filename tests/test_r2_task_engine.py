import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mining_research_kernel.task_engine import TaskEngine, reserve_execution
from providers.execution import DisabledExecutionProvider, FakeExecutionProvider
from workflows.flac3d import build_flac3d_workflow_pack


PROJECT = {
    "project_id": "synthetic-project", "product": "flac3d", "product_version": "9.6.44",
    "entry": "START.md", "baseline": "cases/main.dat", "errors": "errors.jsonl",
    "decisions": "decisions.jsonl", "research_map": "map.json",
    "execution": {"provider": "fake"}, "execution_authorized": True,
}
PAGE = "flac3d/zone/doc/manual/zone_commands/cmd_zone.list.html"


def citation(status="VERIFIED", trust="official_local", version="9.6.44",
             *, product_version="9.6.44", topic=PAGE, command="zone list",
             source=None, anchor=None, task_context=None, body_digest=None,
             source_id="host.local.flac3d.documentation", fetched_at="2026-09-05T00:00:00Z",
             checked_at="2026-09-05T00:00:01Z"):
    normalized = " ".join(command.split())
    expected_anchor = "command:" + ".".join(normalized.split())
    anchor = anchor or expected_anchor
    task_context = task_context or ("synthetic" if trust == "synthetic" else "production")
    canonical = {"product": "flac3d", "product_version": product_version,
                 "topic": topic, "command": normalized, "source": source,
                 "anchor": anchor, "task_context": task_context}
    query_digest = hashlib.sha256(json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
    return {"status": status, "trust_class": trust, "source_id": source_id,
            "product": "flac3d", "document_family": "9.6", "document_build": version,
            "page": topic, "anchor": anchor, "sha256": body_digest or "a" * 64,
            "sha256_body": body_digest or "a" * 64,
            "query_sha256": query_digest, "fetched_at": fetched_at, "checked_at": checked_at}


class R2TaskEngineTests(unittest.TestCase):
    def make_engine(self, *, docs=None, fake=False, project=None):
        project = copy.deepcopy(project or PROJECT)
        providers = {"execution": FakeExecutionProvider()} if fake else {"execution": DisabledExecutionProvider()}
        pack = build_flac3d_workflow_pack(project, {"task_type": "mining_research_kernel.task.syntax_change"}, providers)
        return TaskEngine(project, pack, providers,
                          relevant_refs={"failures": ["failure.1"], "decisions": ["decision.1"], "cognition": ["cognition.1"]},
                          documentation_result=docs)

    def request(self, task_type="mining_research_kernel.task.syntax_change", **extra):
        value = {"task_id": "task-r2", "project_id": "synthetic-project",
                 "workflow_id": "mining_research_kernel.workflow.flac3d",
                 "task_type": task_type, "maturity": "known_workflow", "max_runs": 2}
        value.update(extra)
        return value

    def test_packet_has_structured_next_action_and_stops(self):
        engine = self.make_engine()
        packet = engine.start(self.request())
        self.assertEqual("blocked", packet["state"])
        self.assertIsNone(packet["next_action"]["action_id"])
        self.assertFalse(packet["next_action"]["executable"])
        self.assertTrue(packet["stop_conditions"])
        self.assertEqual(["failure.1"], packet["refs"]["failures"])
        self.assertIn("writeback_targets", packet)

    def test_production_exact_document_and_wrong_version_or_synthetic_boundary(self):
        good = {"status": "VERIFIED", "coverage_scope": "command_name_only", "citation": citation()}
        engine = self.make_engine(docs=good)
        self.assertEqual("ready", engine.start(self.request(page=PAGE, command="zone list"))["state"])
        wrong = copy.deepcopy(good)
        wrong["citation"]["document_build"] = "9.6.43"
        self.assertEqual("blocked", self.make_engine(docs=wrong).start(self.request(page=PAGE, command="zone list"))["state"])
        synthetic = {"status": "SYNTHETIC_VERIFIED", "coverage_scope": "command_name_only",
                     "citation": citation("SYNTHETIC_VERIFIED", "synthetic", task_context="synthetic")}
        self.assertEqual("blocked", self.make_engine(docs=synthetic).start(self.request(page=PAGE, command="zone list"))["state"])
        self.assertEqual("ready", self.make_engine(docs=synthetic).start(
            self.request(page=PAGE, command="zone list", task_context="synthetic"))["state"])

    def test_syntax_citation_is_bound_to_provider_query_and_body_metadata(self):
        request = self.request(page=PAGE, command="  zone   list  ", source="registered-source",
                                anchor="command:zone.list")
        good = {"status": "VERIFIED", "coverage_scope": "command_name_only",
                "citation": citation(source="registered-source", command="  zone   list  ")}
        self.assertEqual("ready", self.make_engine(docs=good).start(request)["state"])
        mutations = {
            "command": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                         "citation": citation(source="registered-source")},
            "page": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                     "citation": citation(source="registered-source")},
            "anchor": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                       "citation": citation(source="registered-source")},
            "query_digest": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                             "citation": dict(citation(source="registered-source"), query_sha256="b" * 64)},
            "body_digest": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                            "citation": dict(citation(source="registered-source"), sha256_body="B" * 64)},
            "source_id": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                          "citation": dict(citation(source="registered-source"), source_id="forged")},
            "source": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                        "citation": citation(source="registered-source")},
            "fetched_at": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                           "citation": dict(citation(source="registered-source"), fetched_at="")},
            "checked_at": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                           "citation": dict(citation(source="registered-source"), checked_at="")},
            "trust": {"status": "VERIFIED", "coverage_scope": "command_name_only",
                      "citation": dict(citation(source="registered-source"), trust_class="synthetic")},
        }
        for name, result in mutations.items():
            mutated_request = dict(request)
            if name == "command":
                mutated_request["command"] = "zone save"
            elif name == "page":
                mutated_request["page"] = "other/page.html"
            elif name == "anchor":
                mutated_request["anchor"] = "command:zone.other"
            elif name == "source":
                mutated_request["source"] = "different-source"
            self.assertEqual("blocked", self.make_engine(docs=result).start(mutated_request)["state"], name)

    def test_workflow_selects_only_applicable_gates(self):
        project = copy.deepcopy(PROJECT)
        for task, expected in (("syntax_change", ["documentation"]),
                               ("static_check", ["static_check"]),
                               ("fake_execution", ["execution"])):
            request = {"task_type": f"mining_research_kernel.task.{task}"}
            pack = build_flac3d_workflow_pack(project, request, {"execution": FakeExecutionProvider()})
            self.assertEqual(expected, pack["verification_gates"])
            for gate in ("mcp_connectivity", "numerical", "physical", "engineering"):
                self.assertEqual("NOT_APPLICABLE", pack["gate_statuses"][gate]["status"])
        pack = build_flac3d_workflow_pack(project, {"task_type": "x.y.static_check", "needs": ["engineering"]})
        self.assertEqual("PENDING", pack["gate_statuses"]["engineering"]["status"])

    def test_disabled_default_never_dispatches(self):
        provider = DisabledExecutionProvider()
        result = provider.execute({"operation": "execute", "task_type": "x.y.fake_execution", "context": "synthetic"})
        self.assertEqual("UNAVAILABLE", result["status"])
        self.assertFalse(provider.capability()["available"])

    def test_fake_is_deterministic_fixture_only_and_denies_mutation(self):
        provider = FakeExecutionProvider()
        request = {"operation": "execute", "task_type": "x.y.fake_execution",
                   "task_context": "synthetic", "fixture_id": "fixture-1", "input": {"a": 1}}
        first = provider.execute(request)
        second = provider.execute(request)
        self.assertEqual(first, second)
        self.assertEqual("COMPLETED", first["status"])
        self.assertEqual(2, len(provider.dispatches))
        mutated = dict(request, operation="mutate")
        self.assertEqual("REJECTED", provider.execute(mutated)["status"])
        self.assertEqual([], list(Path(tempfile.gettempdir()).glob("r2-task-engine-*")))

    def test_budget_retry_unknown_and_idempotence(self):
        provider = FakeExecutionProvider()
        project = copy.deepcopy(PROJECT)
        pack = build_flac3d_workflow_pack(project, {"task_type": "x.y.fake_execution"}, {"execution": provider})
        engine = TaskEngine(project, pack, {"execution": provider})
        packet = engine.start(self.request("x.y.fake_execution", task_context="synthetic", fixture_id="f", max_runs=1))
        done = engine.execute_fake(packet, "op-1")
        self.assertEqual("completed", done["state"])
        self.assertEqual(1, done["runs_used"])
        again = engine.execute_fake(done, "op-1")
        self.assertEqual(done["last_run"], again["last_run"])
        self.assertEqual(1, len(provider.dispatches))
        self.assertEqual(1, reserve_execution({"task_id": "t", "project_id": "p", "workflow_id": "x.y",
                                                "state": "ready", "max_runs": 1}, "operation")["runs_used"])
        exhausted = engine.start(self.request("x.y.fake_execution", task_id="task-r2b",
                                               task_context="synthetic", fixture_id="f", max_runs=1))
        self.assertEqual("completed", engine.execute_fake(exhausted, "op-2")["state"])
        self.assertEqual(1, engine.execute_fake(exhausted, "op-3")["runs_used"])

    def test_unknown_outcome_cannot_retry_same_operation_but_new_retry_is_charged(self):
        class UnknownProvider(FakeExecutionProvider):
            def execute(self, request):
                self.dispatches.append(dict(request))
                return {"schema_version": 1, "type": "ExecutionResult", "provider_id": self.provider_id,
                        "status": "UNKNOWN", "stop_reason": "dispatch_outcome_unknown", "operation": "execute",
                        "side_effect": "unknown", "fixture_id": request["fixture_id"], "input_digest": "digest",
                        "output": None}

        provider = UnknownProvider()
        project = copy.deepcopy(PROJECT)
        pack = build_flac3d_workflow_pack(project, {"task_type": "x.y.fake_execution"}, {"execution": provider})
        engine = TaskEngine(project, pack, {"execution": provider})
        packet = engine.start(self.request("x.y.fake_execution", task_context="synthetic", fixture_id="f", max_runs=2))
        failed = engine.execute_fake(packet, "op-unknown")
        self.assertEqual("failed", failed["state"])
        self.assertEqual(1, failed["runs_used"])
        same = engine.execute_fake(failed, "op-unknown")
        self.assertEqual(1, same["runs_used"])
        self.assertEqual(1, len(provider.dispatches))
        retried = engine.execute_fake(failed, "op-retry")
        self.assertEqual(2, retried["runs_used"])
        self.assertEqual(2, len(provider.dispatches))

    def test_route_budget_blocks_without_charging_task_budget(self):
        provider = FakeExecutionProvider()
        project = copy.deepcopy(PROJECT)
        pack = build_flac3d_workflow_pack(project, {"task_type": "x.y.fake_execution"}, {"execution": provider})
        engine = TaskEngine(project, pack, {"execution": provider})
        packet = engine.start(self.request("x.y.fake_execution", task_context="synthetic", fixture_id="f", max_runs=2))
        blocked = engine.reserve_execution(packet, "route-op-1", {"route_id": packet["routes"][0], "max_runs": 1})
        self.assertEqual(1, blocked["runs_used"])
        blocked = engine.reserve_execution(blocked, "route-op-2")
        self.assertEqual("blocked", blocked["state"])
        self.assertEqual(1, blocked["runs_used"])

    def test_preflight_does_not_charge_and_legal_transitions_are_enforced(self):
        project = copy.deepcopy(PROJECT)
        pack = build_flac3d_workflow_pack(project, {"task_type": "x.y.fake_execution"}, {"execution": DisabledExecutionProvider()})
        engine = TaskEngine(project, pack, {"execution": DisabledExecutionProvider()})
        packet = engine.start(self.request("x.y.fake_execution", task_context="synthetic", fixture_id="f"))
        self.assertEqual(0, packet["runs_used"])
        with self.assertRaisesRegex(ValueError, "illegal"):
            engine.transition(packet, "completed")
        proposed = copy.deepcopy(packet)
        proposed["task_id"] = "task-proposed"
        proposed["state"] = "proposed"
        engine._tasks["task-proposed"] = proposed
        self.assertEqual("ready", engine.transition(proposed, "ready")["state"])
        with self.assertRaisesRegex(ValueError, "illegal"):
            engine.transition(proposed, "completed")


if __name__ == "__main__":
    unittest.main()
