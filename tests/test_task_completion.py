import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_synthetic_project
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_complete, task_inspect, task_start
from mining_research_kernel.routes import RouteLifecycle
from run_ledger import create_run, record_stage


class TaskCompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_synthetic_project(self.root, "completion_project")
        self.task_id = "completion-task"
        task_start(self.root, {
            "task_id": self.task_id,
            "question_statement": "Can the bounded route finish?",
            "claim_statement": "The bounded route has recorded evidence.",
            "task_type": "mining_research_kernel.task.static_check",
            "maturity": "exploratory", "max_runs": 1, "task_context": "synthetic",
        })
        self.route_id = self.task_id + ".route.1"
        RouteLifecycle(self.root).reserve(self.route_id, "reserve-completion")
        RouteLifecycle(self.root).finish(
            self.route_id, "reserve-completion", "completed", "finish-completion",
            outputs=["research/result.md"],
        )
        self.run_id = "run-completion"
        runs_root = self.root / "research" / "runs"
        create_run(runs_root, self.run_id, {"task_id": self.task_id, "route_id": self.route_id}, {"input_hashes": ["fixture-input"]})
        record_stage(runs_root, self.run_id, "exploration", "planning_agent", "completed", {}, model="test", operation_id="run-explore")
        record_stage(runs_root, self.run_id, "plan", "planning_agent", "completed",
                     {"steps": ["read fixture"], "risks": ["fixture only"]}, model="test", operation_id="run-plan")
        record_stage(runs_root, self.run_id, "execution", "execution_agent", "completed",
                     {"commands": ["fixture"], "return_codes": [0], "output_paths": ["research/result.md"]}, model="test", operation_id="run-execute")
        record_stage(runs_root, self.run_id, "test", "execution_agent", "completed",
                     {"test_results": ["fixture output recorded"]}, model="test", operation_id="run-test")
        record_stage(runs_root, self.run_id, "acceptance", "acceptance_agent", "completed",
                     {"verdict": "PASS", "test_evidence": ["fixture accepted"], "unresolved_risks": ["synthetic only"]},
                     model="test", operation_id="run-accept")
        manifest = json.loads((runs_root / self.run_id / "manifest.json").read_text(encoding="utf-8"))
        store = ResearchStore(self.root)
        route = store.latest_record(self.route_id, "Route")
        claim_id = next(edge["to_id"] for tx in store.list_transactions() for edge in tx["relationships"]
                         if edge["relation"] == "route_targets_claim" and edge["from_id"] == self.route_id)
        asset = self._record("Asset", "asset-completion", asset_kind="fixture-output", locator={"path": "research/result.md"},
                             content_sha256="a" * 64, authority="derived", status="observed")
        evidence = self._record("Evidence", "evidence-completion", evidence_kind="fixture-output",
                                asset_ref=asset["id"], locator={"path": "research/result.md"}, status="observed",
                                source_refs=[f"task:{self.task_id}", f"run:{self.run_id}"])
        run_ref = self._record("RunReference", "runref-completion", run_id=self.run_id,
                               manifest_sha256=hashlib.sha256((runs_root / self.run_id / "manifest.json").read_bytes()).hexdigest(),
                               status="completed", route_id=self.route_id,
                               source_refs=[f"task:{self.task_id}", f"route:{self.route_id}", f"run:{self.run_id}"])
        verification = self._record("Verification", "verification-completion", status="PASS_WITH_NOTES",
                                    gate_id="static_check", scope={"task_id": self.task_id, "route_id": self.route_id},
                                    verification_scope="bounded fixture completion", run_id=self.run_id,
                                    source_refs=[f"task:{self.task_id}", f"route:{self.route_id}", f"run:{self.run_id}"])
        wrong_verification = self._record("Verification", "verification-unlinked", status="PASS",
                                          gate_id="other", scope={"task_id": self.task_id}, run_id="other-run",
                                          source_refs=[f"task:{self.task_id}"])
        store.commit("seed-completion-evidence", {"role": "acceptance_agent", "model": "test"},
                     [asset, evidence, run_ref, verification, wrong_verification], [
                         self._relationship("edge-run-route", "run_executes_route", run_ref, route),
                         self._relationship("edge-run-evidence", "run_produces_evidence", run_ref, evidence),
                         self._relationship("edge-verification-run", "verification_checks_run", verification, run_ref),
                         self._relationship("edge-evidence-asset", "evidence_derived_from_asset", evidence, asset),
                         self._relationship("edge-evidence-claim", "source_documents_claim", evidence,
                                            store.latest_record(claim_id, "Claim")),
                     ])
        self.completion = {
            "route_ids": [self.route_id],
            "run_reference_ids": {self.route_id: run_ref["id"]},
            "verification_ids": {self.route_id: [verification["id"]]},
            "verification_gate_coverage": {self.route_id: {"static_check": [{
                "verification_id": verification["id"], "verification_gate_id": "static_check"
            }]}},
            "evidence_refs": {self.route_id: [evidence["id"]]},
            "output_refs": {self.route_id: ["research/result.md"]},
        }
        self.repo = Path(__file__).parents[1]
        self.env = os.environ.copy()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def tearDown(self):
        self.temp.cleanup()

    def _record(self, record_type, record_id, source_refs=None, **fields):
        value = {"schema_version": 1, "type": record_type, "id": record_id, "revision": 1,
                 "project_id": "completion_project", "scope": {"project_id": "completion_project"},
                 "source_refs": source_refs or [f"task:{self.task_id}"]}
        value.update(fields)
        return value

    def _relationship(self, relationship_id, relation, from_record, to_record):
        return {"schema_version": 1, "relationship_id": relationship_id, "revision": 1,
                "project_id": "completion_project", "relation": relation,
                "from_id": from_record["id"], "from_revision": from_record["revision"],
                "to_id": to_record["id"], "to_revision": to_record["revision"],
                "source_refs": [f"task:{self.task_id}"]}

    def test_completion_persists_and_is_idempotent_across_cli_process(self):
        completion_path = self.root / "completion.json"
        completion_path.write_text(json.dumps(self.completion), encoding="utf-8")
        cli_result = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "task-complete", "--project-root", str(self.root),
             self.task_id, "--operation-id", "complete-operation", "--completion-json", "@" + str(completion_path)],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, cli_result.returncode, cli_result.stderr)
        result = json.loads(cli_result.stdout)
        self.assertEqual("completed", result["state"])
        self.assertFalse(result["next_action"]["executable"])
        self.assertEqual(2, ResearchStore(self.root).latest_record(self.task_id, "TaskState")["revision"])
        tx_count = len(ResearchStore(self.root).list_transactions())
        repeated = task_complete(self.root, self.task_id, "complete-operation", copy.deepcopy(self.completion))
        self.assertEqual(result["next_action"], repeated["next_action"])
        self.assertEqual(tx_count, len(ResearchStore(self.root).list_transactions()))
        conflict = copy.deepcopy(self.completion)
        conflict["output_refs"][self.route_id] = ["research/other.md"]
        with self.assertRaisesRegex(ValueError, "different completion content"):
            task_complete(self.root, self.task_id, "complete-operation", conflict)
        code = "import json,sys; from mining_research_kernel.r2_workflow import task_inspect; print(json.dumps(task_inspect(sys.argv[1], sys.argv[2])))"
        recovered = subprocess.run([sys.executable, "-B", "-c", code, str(self.root), self.task_id],
                                   cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(0, recovered.returncode, recovered.stderr)
        self.assertEqual("completed", json.loads(recovered.stdout)["state"])
        self.assertFalse(json.loads(recovered.stdout)["next_action"]["executable"])

    def test_completion_rejects_missing_or_unlinked_evidence_and_verification(self):
        missing = copy.deepcopy(self.completion)
        missing["evidence_refs"][self.route_id] = []
        with self.assertRaisesRegex(ValueError, "evidence_refs"):
            task_complete(self.root, self.task_id, "missing-evidence", missing)
        wrong = copy.deepcopy(self.completion)
        wrong["verification_ids"][self.route_id] = ["verification-unlinked"]
        wrong["verification_gate_coverage"][self.route_id]["static_check"] = [{
            "verification_id": "verification-unlinked", "verification_gate_id": "other"
        }]
        with self.assertRaisesRegex(ValueError, "linked to the selected RunReference"):
            task_complete(self.root, self.task_id, "wrong-verification", wrong)

    def test_completion_rejects_coverage_for_a_gate_outside_current_packet(self):
        wrong_gate = copy.deepcopy(self.completion)
        wrong_gate["verification_gate_coverage"][self.route_id] = {
            "wrong_gate": [{"verification_id": "verification-completion", "verification_gate_id": "static_check"}]
        }
        with self.assertRaisesRegex(ValueError, "current required gates"):
            task_complete(self.root, self.task_id, "wrong-gate-coverage", wrong_gate)

    def test_completion_rejects_static_or_documentation_research_verification_for_documentation_gate(self):
        store = ResearchStore(self.root)
        prior = store.latest_record(self.task_id, "TaskState")
        packet = copy.deepcopy(prior["packet"])
        packet["verification_gates"] = ["documentation"]
        packet["documentation_required"] = True
        packet["gate_statuses"]["static_check"] = {
            "gate_id": "static_check", "applicable": False,
            "status": "NOT_APPLICABLE", "reason": "documentation_task_scope",
        }
        packet["gate_statuses"]["documentation"] = {
            "gate_id": "documentation", "applicable": True,
            "status": "PENDING", "reason": "selected_for_task",
        }
        packet_record = copy.deepcopy(prior)
        packet_record["revision"] = prior["revision"] + 1
        packet_record["packet"] = packet
        store.commit("require-documentation-gate", {"role": "planning_agent", "model": "test"},
                     [packet_record], expected_revisions={self.task_id: prior["revision"]})

        for gate_id, verification_id in (("static_check", "verification-completion"),
                                         ("documentation_research", "verification-documentation-research")):
            if gate_id == "documentation_research":
                run_ref = store.latest_record("runref-completion", "RunReference")
                verification = self._record(
                    "Verification", verification_id, status="PASS_WITH_NOTES", gate_id=gate_id,
                    scope={"task_id": self.task_id, "route_id": self.route_id},
                    run_id=self.run_id,
                    source_refs=[f"task:{self.task_id}", f"route:{self.route_id}", f"run:{self.run_id}"])
                store.commit("add-documentation-research-verification", {"role": "acceptance_agent", "model": "test"},
                             [verification], [self._relationship("edge-documentation-research-run",
                                                                 "verification_checks_run", verification, run_ref)])
            wrong = copy.deepcopy(self.completion)
            wrong["verification_ids"][self.route_id] = [verification_id]
            wrong["verification_gate_coverage"][self.route_id] = {"documentation": [{
                "verification_id": verification_id, "verification_gate_id": gate_id
            }]}
            with self.assertRaisesRegex(ValueError, "does not cover the current packet gate"):
                task_complete(self.root, self.task_id, "wrong-documentation-gate-" + gate_id, wrong)
        self.assertEqual("ready", ResearchStore(self.root).latest_record(self.task_id, "TaskState")["state"])
        self.assertEqual(2, ResearchStore(self.root).latest_record(self.task_id, "TaskState")["revision"])

    def test_completion_rejects_unfinished_required_route_and_cannot_claim_state(self):
        fresh = Path(self.temp.name) / "unfinished"
        init_synthetic_project(fresh, "unfinished_project")
        task_start(fresh, {
            "task_id": "unfinished-task", "question_statement": "Q", "claim_statement": "C",
            "task_type": "mining_research_kernel.task.static_check", "maturity": "exploratory",
            "max_runs": 1, "task_context": "synthetic",
        })
        with self.assertRaisesRegex(ValueError, "unsupported fields|not completed|no recorded research outputs"):
            task_complete(fresh, "unfinished-task", "unfinished-operation", {"state": "completed"})

    def test_completion_rejects_second_unfinished_packet_route_without_closing_task(self):
        store = ResearchStore(self.root)
        task = store.latest_record(self.task_id, "TaskState")
        question_id = store.latest_record(self.route_id, "Route")["question_id"]
        claim_id = next(edge["to_id"] for tx in store.list_transactions() for edge in tx["relationships"]
                         if edge["relation"] == "route_targets_claim" and edge["from_id"] == self.route_id)
        second_route_id = self.task_id + ".route.2"
        second_route = RouteLifecycle(self.root).propose({
            "route_id": second_route_id, "task_id": self.task_id,
            "question_id": question_id, "claim_id": claim_id, "hypothesis_id": None,
            "workflow_id": "workflow.synthetic", "method_id": "method.synthetic",
            "budget": 1, "write_set": ["research/second-result.md"],
        }, "propose-second-route")["route"]
        packet = copy.deepcopy(task["packet"])
        packet["routes"] = [self.route_id, second_route_id]
        packet_record = copy.deepcopy(task)
        packet_record["revision"] = task["revision"] + 1
        packet_record["packet"] = packet
        store.commit("add-second-required-route", {"role": "planning_agent", "model": "test"},
                     [packet_record], expected_revisions={self.task_id: task["revision"]})
        before = ResearchStore(self.root).latest_record(self.task_id, "TaskState")
        transaction_count = len(ResearchStore(self.root).list_transactions())
        completion = copy.deepcopy(self.completion)
        completion["route_ids"] = [self.route_id, second_route_id]
        completion["run_reference_ids"][second_route_id] = "runref-completion"
        completion["verification_ids"][second_route_id] = ["verification-completion"]
        completion["verification_gate_coverage"][second_route_id] = {"static_check": [{
            "verification_id": "verification-completion", "verification_gate_id": "static_check"
        }]}
        completion["evidence_refs"][second_route_id] = ["evidence-completion"]
        completion["output_refs"][second_route_id] = ["research/second-result.md"]
        with self.assertRaisesRegex(ValueError, "required route is not completed"):
            task_complete(self.root, self.task_id, "unfinished-second-route", completion)
        after = ResearchStore(self.root).latest_record(self.task_id, "TaskState")
        self.assertEqual("ready", after["state"])
        self.assertEqual(before["revision"], after["revision"])
        self.assertEqual(transaction_count, len(ResearchStore(self.root).list_transactions()))
        self.assertEqual("proposed", ResearchStore(self.root).latest_record(second_route_id, "Route")["status"])

    def test_completion_rejects_incomplete_current_gate_coverage(self):
        store = ResearchStore(self.root)
        prior = store.latest_record(self.task_id, "TaskState")
        packet = copy.deepcopy(prior["packet"])
        packet["verification_gates"] = ["static_check", "documentation"]
        packet["documentation_required"] = True
        packet["documentation_status"] = "CANNOT_VERIFY"
        packet["gate_statuses"]["documentation"] = {
            "gate_id": "documentation", "applicable": True,
            "status": "CANNOT_VERIFY", "reason": "required_source_missing",
        }
        packet_record = copy.deepcopy(prior)
        packet_record["revision"] = prior["revision"] + 1
        packet_record["packet"] = packet
        store.commit("set-current-documentation-gate", {"role": "planning_agent", "model": "test"},
                     [packet_record], expected_revisions={self.task_id: prior["revision"]})
        with self.assertRaisesRegex(ValueError, "current required gates"):
            task_complete(self.root, self.task_id, "missing-documentation-gate", self.completion)

        narrowed = copy.deepcopy(self.completion)
        narrowed["verification_gate_coverage"][self.route_id] = {
            "static_check": [{"verification_id": "verification-completion", "verification_gate_id": "static_check"}],
            "documentation": [{"verification_id": "verification-completion", "verification_gate_id": "static_check"}],
        }
        narrowed["verification_ids"][self.route_id] = ["verification-completion"]
        with self.assertRaisesRegex(ValueError, "multiple gates"):
            task_complete(self.root, self.task_id, "generic-pass-narrowing", narrowed)

    def test_completion_accepts_all_current_gates_with_later_valid_verification(self):
        store = ResearchStore(self.root)
        prior = store.latest_record(self.task_id, "TaskState")
        packet = copy.deepcopy(prior["packet"])
        packet["verification_gates"] = ["static_check", "documentation"]
        packet["documentation_required"] = True
        packet["documentation_status"] = "CANNOT_VERIFY"
        packet["gate_statuses"]["documentation"] = {
            "gate_id": "documentation", "applicable": True,
            "status": "CANNOT_VERIFY", "reason": "required_source_missing",
        }
        packet_record = copy.deepcopy(prior)
        packet_record["revision"] = prior["revision"] + 1
        packet_record["packet"] = packet
        store.commit("set-later-documentation-gate", {"role": "planning_agent", "model": "test"},
                     [packet_record], expected_revisions={self.task_id: prior["revision"]})
        run_ref = store.latest_record("runref-completion", "RunReference")
        verification = self._record("Verification", "verification-documentation-later", status="PASS",
                                    gate_id="documentation",
                                    scope={"task_id": self.task_id, "route_id": self.route_id},
                                    verification_scope="fixture documentation coverage", run_id=self.run_id,
                                    source_refs=[f"task:{self.task_id}", f"route:{self.route_id}", f"run:{self.run_id}"])
        store.commit("add-later-documentation-verification", {"role": "acceptance_agent", "model": "test"},
                     [verification], [self._relationship("edge-later-documentation-run", "verification_checks_run",
                                                         verification, run_ref)])
        completion = copy.deepcopy(self.completion)
        completion["verification_ids"][self.route_id].append(verification["id"])
        completion["verification_gate_coverage"][self.route_id]["documentation"] = [{
            "verification_id": verification["id"], "verification_gate_id": "documentation"
        }]
        result = task_complete(self.root, self.task_id, "all-gates-later-pass", completion)
        self.assertEqual("completed", result["state"])
        refs = result["operation_result"]["record_refs"][self.route_id]
        self.assertEqual("documentation", refs["gate_coverage"]["documentation"][0]["verification_gate_id"])

    def test_not_applicable_engineering_gates_do_not_block_documentation_task(self):
        store = ResearchStore(self.root)
        prior = store.latest_record(self.task_id, "TaskState")
        packet = copy.deepcopy(prior["packet"])
        packet["gate_statuses"].update({
            gate: {"gate_id": gate, "applicable": False, "status": "NOT_APPLICABLE",
                   "reason": "documentation_task"}
            for gate in ("engineering", "numerical", "physical", "real_flac3d")
        })
        packet_record = copy.deepcopy(prior)
        packet_record["revision"] = prior["revision"] + 1
        packet_record["packet"] = packet
        store.commit("set-not-applicable-engineering-gates", {"role": "planning_agent", "model": "test"},
                     [packet_record], expected_revisions={self.task_id: prior["revision"]})
        result = task_complete(self.root, self.task_id, "documentation-task-n-a", self.completion)
        self.assertEqual("completed", result["state"])

    def test_completion_request_schema_parses_and_accepts_real_shape(self):
        import jsonschema
        schema = json.loads((self.repo / "schemas" / "task_completion.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(self.completion)


if __name__ == "__main__":
    unittest.main()
