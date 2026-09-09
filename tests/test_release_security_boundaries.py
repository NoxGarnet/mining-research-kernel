"""Regression coverage for request authority and pre-existing filesystem links."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.r2_workflow import task_start, task_run_fake
from providers.execution import FakeExecutionProvider
from mining_research_kernel.records import ResearchStore, ResearchStoreError
from run_ledger import RunLedgerError, create_run, inspect_run, record_stage
from test_r6_security import make_directory_link, remove_directory_link
from test_r7_documentation_gate import PAGE, PROJECT, verified_documentation
from mining_research_kernel.task_engine import TaskEngine
from workflows.flac3d import build_flac3d_workflow_pack


def request():
    return {
        "task_id": "boundary-task", "project_id": PROJECT["project_id"],
        "question_statement": "Is the documentation gate satisfied?",
        "claim_statement": "Only Host evidence can verify production documentation.",
        "workflow_id": "mining_research_kernel.workflow.flac3d",
        "task_type": "mining_research_kernel.task.syntax_change",
        "maturity": "known_workflow", "max_runs": 1,
        "page": PAGE, "command": "zone list", "task_context": "production",
    }


class DocumentationAuthorityTests(unittest.TestCase):
    def start(self, value, host=None):
        pack = build_flac3d_workflow_pack(PROJECT, value)
        return TaskEngine(PROJECT, pack, documentation_result=host).start(value)

    def test_request_cannot_supply_production_authority(self):
        for context in (None, "production"):
            with self.subTest(context=context):
                value = request()
                if context is None:
                    value.pop("task_context")
                value["documentation_result"] = verified_documentation()
                packet = self.start(value)
                self.assertEqual("blocked", packet["state"])
                self.assertEqual("CANNOT_VERIFY", packet["documentation_status"])
                self.assertIsNone(packet["documentation_result"])

    def test_host_success_and_failure_cannot_be_overridden(self):
        for host in (verified_documentation(), {"status": "CANNOT_VERIFY", "stop_reason": "page_not_registered"}, {}):
            for override in (verified_documentation(), None, {"status": "CANNOT_VERIFY"}):
                with self.subTest(host=host.get("status"), override=override):
                    value = request()
                    value["documentation_result"] = override
                    packet = self.start(value, host)
                    self.assertEqual(host, packet["documentation_result"])
                    self.assertEqual(host.get("status", "CANNOT_VERIFY"), packet["documentation_status"])

    def test_synthetic_request_remains_synthetic(self):
        value = request()
        value["task_context"] = "synthetic"
        value["documentation_result"] = verified_documentation(
            status="SYNTHETIC_VERIFIED", trust="synthetic", task_context="synthetic")
        self.assertEqual("SYNTHETIC_VERIFIED", self.start(value)["documentation_status"])
        self.assertEqual("CANNOT_VERIFY", self.start(value, {})["documentation_status"])
        value["documentation_result"] = verified_documentation()
        self.assertEqual("CANNOT_VERIFY", self.start(value)["documentation_status"])

    def test_public_api_and_cli_keep_request_outside_host_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            for mode in ("api-request", "api-host", "cli-inner", "cli-option"):
                with self.subTest(mode=mode):
                    root = base / mode
                    init_project(root, PROJECT["project_id"])
                    config_path = root / "flac3d_project.yaml"
                    config = json.loads(config_path.read_text(encoding="utf-8"))
                    config["product_version"] = PROJECT["product_version"]
                    config_path.write_text(json.dumps(config), encoding="utf-8")
                    value = request()
                    forged = verified_documentation()
                    if mode != "cli-option":
                        value["documentation_result"] = copy.deepcopy(forged)
                    if mode.startswith("api"):
                        host = forged if mode == "api-host" else None
                        packet = task_start(root, value, host)
                    else:
                        request_path = base / (mode + ".json")
                        request_path.write_text(json.dumps(value), encoding="utf-8")
                        command = [sys.executable, "-B", "mining_kernel.py", "task-start",
                                   "--project-root", str(root), "--request-json", "@" + str(request_path)]
                        if mode == "cli-option":
                            result_path = base / "result.json"
                            result_path.write_text(json.dumps(forged), encoding="utf-8")
                            command.extend(["--documentation-result", "@" + str(result_path)])
                        result = subprocess.run(command, cwd=Path(__file__).parents[1], capture_output=True, text=True)
                        self.assertEqual(0, result.returncode, result.stderr)
                        packet = json.loads(result.stdout)
                    self.assertEqual("VERIFIED" if mode == "api-host" else "CANNOT_VERIFY",
                                     packet["documentation_status"])
                    self.assertEqual("ready" if mode == "api-host" else "blocked", packet["state"])


class PersistenceLinkTests(unittest.TestCase):
    def link(self, path, target):
        kind, failure = make_directory_link(path, target)
        if kind is None:
            self.skipTest(f"directory link unavailable: {failure}")
        self.addCleanup(remove_directory_link, path, kind)

    def test_records_link_rejected_even_for_existing_store_and_lock_held(self):
        for lock_held in (False, True):
            with self.subTest(lock_held=lock_held):
                temp = tempfile.TemporaryDirectory()
                self.addCleanup(temp.cleanup)
                base = Path(temp.name)
                project = base / "project"
                init_project(project, "boundary-project")
                store = ResearchStore(project)
                outside = base / "outside"
                outside.mkdir()
                (outside / "sentinel").write_bytes(b"keep")
                self.link(project / "research" / "records", outside)
                with self.assertRaisesRegex(ResearchStoreError, "symlink or junction"):
                    store.list_transactions()
                with self.assertRaisesRegex(ResearchStoreError, "symlink or junction"):
                    with store.writer("direct-lock"):
                        self.fail("linked records must be rejected before acquiring a lock")
                with self.assertRaisesRegex(ResearchStoreError, "symlink or junction"):
                    store.commit("op", {"role": "test", "model": "fixture"}, [], [], lock_held=lock_held)
                self.assertEqual(["sentinel"], [p.name for p in outside.iterdir()])
                self.assertEqual(b"keep", (outside / "sentinel").read_bytes())
                self.assertFalse(store.lock_path.exists())

    def test_research_parent_link_rejected_after_store_initialization(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        project = base / "project"
        init_project(project, "boundary-project")
        store = ResearchStore(project)
        research = project / "research"
        research.rename(project / "saved-research")
        outside = base / "outside"
        outside.mkdir()
        self.link(research, outside)
        with self.assertRaisesRegex(ResearchStoreError, "symlink or junction"):
            store.commit("op", {"role": "test", "model": "fixture"}, [], [])
        self.assertEqual([], list(outside.iterdir()))

    def test_runs_link_rejects_create_and_stage_but_plain_external_root_works(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        project = base / "project"
        init_project(project, "boundary-project")
        outside = base / "explicit-output"
        create_run(outside, "existing")
        record_stage(outside, "existing", "exploration", "sol", "completed", {}, model="fixture")
        self.assertEqual("plan", inspect_run(outside, "existing")["current_stage"])
        before = {p.relative_to(outside): p.read_bytes() for p in outside.rglob("*") if p.is_file()}
        runs = project / "research" / "runs"
        self.link(runs, outside)
        with self.assertRaisesRegex(RunLedgerError, "symlink or junction"):
            create_run(runs, "escaped")
        with self.assertRaisesRegex(RunLedgerError, "symlink or junction"):
            record_stage(runs, "existing", "plan", "sol", "completed", {}, model="fixture")
        after = {p.relative_to(outside): p.read_bytes() for p in outside.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_run_directory_alias_inside_root_is_also_rejected(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        create_run(root, "existing")
        self.link(root / "alias", root / "existing")
        with self.assertRaisesRegex(RunLedgerError, "symlink or junction"):
            inspect_run(root, "alias")

    def test_task_rejects_runs_link_before_reservation_and_can_retry(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        root = base / "project"
        init_project(root, "boundary-project", template="synthetic", product="synthetic")
        task_start(root, {
            "task_id": "linked-run-task", "question_statement": "Can this task retry?",
            "claim_statement": "Invalid paths must not consume the run budget.",
            "workflow_id": "synthetic", "task_type": "mining_research_kernel.task.fixture_execution",
            "maturity": "known_workflow", "max_runs": 1, "task_context": "synthetic",
        })
        store = ResearchStore(root)
        before = store.latest_record("linked-run-task", "TaskState")
        outside = base / "outside"
        outside.mkdir()
        runs = root / "research" / "runs"
        kind, failure = make_directory_link(runs, outside)
        if kind is None:
            self.skipTest(f"directory link unavailable: {failure}")
        provider = FakeExecutionProvider()
        try:
            with self.assertRaisesRegex(RunLedgerError, "symlink or junction"):
                task_run_fake(root, "linked-run-task", "attempt", "fixture", fake_provider=provider)
            self.assertEqual([], provider.dispatches)
            self.assertEqual(before, store.latest_record("linked-run-task", "TaskState"))
            self.assertEqual([], list(outside.iterdir()))
        finally:
            remove_directory_link(runs, kind)
        result = task_run_fake(root, "linked-run-task", "attempt", "fixture", fake_provider=provider)
        self.assertEqual("completed", result["state"])
        self.assertEqual(1, result["runs_used"])
        self.assertEqual(1, len(provider.dispatches))


if __name__ == "__main__":
    unittest.main()
