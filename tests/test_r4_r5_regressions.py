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


REPO = Path(__file__).parents[1]


class R4R5RegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "r4_r5_regressions")
        self.cognition = CoreCognition(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def proposal(self, proposal_id, evidence_id, **extra):
        value = {
            "id": proposal_id,
            "proposal_type": "project_lesson",
            "statement": "The observed fixture passed.",
            "evidence_refs": [evidence_id],
            "scope": {"study": "regression"},
            "requested_status": "provisional",
            "created_by": "agent",
            "created_by_role": "planning_agent",
            "created_model": "test",
            "impact": "low",
            "object_ref": "fixture",
            "scope_key": "regression",
            "fact_key": "passed",
            "fact_value": True,
        }
        value.update(extra)
        return value

    def test_provisional_requires_allowlisted_direct_observation_and_exact_asset_provenance(self):
        observed = self.cognition.record_mechanical_evidence(
            "structured_test", {"passed": False}, operation_id="observe-regression",
            locator={"test": "regression"}, scope={"study": "regression"})
        evidence, asset = observed["records"][1], observed["records"][0]

        mismatch = self.cognition.propose(
            self.proposal("failed-to-passed", evidence["id"]), "proposal-failed-to-passed")
        self.assertEqual("proposed", mismatch["records"][0]["admitted_status"])

        unsupported = self.cognition.propose(
            self.proposal("unsupported-key", evidence["id"], fact_key="stable"),
            "proposal-unsupported-key")
        self.assertEqual("proposed", unsupported["records"][0]["admitted_status"])

        free_text_value = self.proposal("free-text", evidence["id"])
        free_text_value.pop("fact_key")
        free_text_value.pop("fact_value")
        free_text = self.cognition.propose(free_text_value, "proposal-free-text")
        self.assertEqual("proposed", free_text["records"][0]["admitted_status"])

        for index, proposal_type in enumerate(("workflow_rule", "domain_rule", "claim")):
            result = self.cognition.propose(
                self.proposal(f"restricted-type-{index}", evidence["id"], proposal_type=proposal_type),
                f"proposal-restricted-type-{index}")
            self.assertIn(result["records"][0]["admitted_status"], {"proposed", "pending_review"})

        changed_asset = copy.deepcopy(asset)
        changed_asset["revision"] = 2
        changed_asset["observation"] = {"passed": True}
        ResearchStore(self.root).commit(
            "change-regression-asset", {"role": "planning_agent", "model": "test"},
            [changed_asset], expected_revisions={asset["id"]: 1})
        provenance_mismatch = self.cognition.propose(
            self.proposal("asset-mismatch", evidence["id"], fact_value=False),
            "proposal-asset-mismatch")
        self.assertEqual("proposed", provenance_mismatch["records"][0]["admitted_status"])

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "mining_kernel.py", *map(str, args)], cwd=REPO,
            capture_output=True, text=True, check=False)

    def output(self, result):
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def task_request(self, task_id):
        return json.dumps({
            "task_id": task_id,
            "question_statement": "Does the bounded fixture run?",
            "claim_statement": "The bounded fixture runs.",
            "task_type": "mining_research_kernel.task.fake_execution",
            "task_context": "synthetic",
            "maturity": "exploratory",
            "max_runs": 1,
            "input": {"fixture": "regression"},
        }, separators=(",", ":"))

    def test_failure_gate_is_loaded_by_new_task_start_process_and_is_scoped(self):
        gate_root = Path(self.temp.name) / "gate-project"
        self.output(self.cli(
            "init-flac3d-project", gate_root, "--project-id", "r5_gate", "--template", "synthetic"))
        failure = json.dumps({
            "failure_id": "persisted-task-failure",
            "observable_failure": "the bounded fixture failed",
            "task_id": "blocked-task",
            "resolution_status": "open",
        }, separators=(",", ":"))
        self.output(self.cli(
            "failure-record", "--project-root", gate_root, "--failure-json", failure,
            "--operation-id", "record-persisted-failure"))

        blocked = self.output(self.cli(
            "task-start", "--project-root", gate_root,
            "--request-json", self.task_request("blocked-task")))
        self.assertEqual("blocked", blocked["state"])
        self.assertEqual(["persisted-task-failure"], blocked["relevant_failures"])
        self.assertEqual("blocked", self.output(
            self.cli("task-inspect", "--project-root", gate_root, "blocked-task"))["state"])

        unrelated = self.output(self.cli(
            "task-start", "--project-root", gate_root,
            "--request-json", self.task_request("unrelated-task")))
        self.assertEqual("ready", unrelated["state"])
        self.assertEqual([], unrelated["relevant_failures"])


if __name__ == "__main__":
    unittest.main()
