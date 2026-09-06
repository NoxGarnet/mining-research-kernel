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
from mining_research_kernel.r2_workflow import research_map_rebuild, task_run_fake, task_start
from providers.execution import FakeExecutionProvider


class R2EndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "r2_e2e")
        self.repo = Path(__file__).parents[1]
        self.env = os.environ.copy()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def tearDown(self):
        self.temp.cleanup()

    def request(self, task_id="task-e2e"):
        return {
            "task_id": task_id,
            "question_statement": "Does the bounded synthetic route complete?",
            "claim_statement": "The kernel workflow mechanics complete for this fixture.",
            "task_type": "mining_research_kernel.task.fake_execution",
            "maturity": "exploratory",
            "max_runs": 1,
            "task_context": "synthetic",
        }

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", *args], cwd=self.repo,
            env=self.env, capture_output=True, text=True,
        )

    def test_cli_second_process_fake_run_idempotence_and_map_rebuild(self):
        request_path = self.root / "request.json"
        request_path.write_text(json.dumps(self.request()), encoding="utf-8")
        started = self.cli("task-start", "--project-root", str(self.root),
                           "--request-json", "@" + str(request_path))
        self.assertEqual(0, started.returncode, started.stderr)
        self.assertEqual("ready", json.loads(started.stdout)["state"])

        inspected = self.cli("task-inspect", "--project-root", str(self.root), "task-e2e")
        self.assertEqual(0, inspected.returncode, inspected.stderr)
        self.assertEqual("ready", json.loads(inspected.stdout)["state"])

        ran = self.cli("task-run-fake", "--project-root", str(self.root), "task-e2e",
                       "--operation-id", "fake-op", "--fixture-id", "fixture-a")
        self.assertEqual(0, ran.returncode, ran.stderr)
        run_result = json.loads(ran.stdout)
        self.assertEqual("completed", run_result["state"])
        run_id = run_result["run_id"]
        manifest = self.root / "research" / "runs" / run_id / "manifest.json"
        self.assertTrue(manifest.is_file())
        manifest_hash = hashlib.sha256(manifest.read_bytes()).hexdigest()
        self.assertEqual(manifest_hash, run_result["manifest_sha256"])

        repeated = self.cli("task-run-fake", "--project-root", str(self.root), "task-e2e",
                            "--operation-id", "fake-op", "--fixture-id", "fixture-a")
        self.assertEqual(0, repeated.returncode, repeated.stderr)
        self.assertEqual(run_id, json.loads(repeated.stdout)["run_id"])
        self.assertEqual(1, len(list((self.root / "research" / "runs").iterdir())))

        conflict = self.cli("task-run-fake", "--project-root", str(self.root), "task-e2e",
                            "--operation-id", "fake-op", "--fixture-id", "fixture-b")
        self.assertEqual(2, conflict.returncode)
        self.assertIn("different fixture_id", conflict.stdout)

        completed = self.cli("task-inspect", "--project-root", str(self.root), "task-e2e")
        self.assertEqual("completed", json.loads(completed.stdout)["state"])
        map_path = self.root / "research" / "map.json"
        map_path.unlink()
        rebuilt = self.cli("research-map-rebuild", "--project-root", str(self.root))
        self.assertEqual(0, rebuilt.returncode, rebuilt.stderr)
        view = json.loads(rebuilt.stdout)
        types = {node["type"] for node in view["nodes"]}
        self.assertTrue({"Claim", "ResearchQuestion", "Route", "RunReference",
                         "Asset", "Evidence", "Verification"}.issubset(types))
        relations = {edge["relation"] for edge in view["edges"]}
        self.assertTrue({"route_addresses_question", "run_executes_route",
                         "run_produces_evidence", "verification_checks_run",
                         "evidence_derived_from_asset"}.issubset(relations))

    def test_fake_run_persists_reservation_before_provider_dispatch(self):
        observed = {}

        class FailingProvider(FakeExecutionProvider):
            def execute(inner_self, request):
                observed["task"] = ResearchStore(self.root).latest_record(
                    "task-reservation", "TaskState"
                )
                raise RuntimeError("forced dispatch interruption")

        task_start(self.root, self.request("task-reservation"))
        with self.assertRaisesRegex(RuntimeError, "forced dispatch interruption"):
            task_run_fake(
                self.root, "task-reservation", "reservation-op", "fixture-a",
                fake_provider=FailingProvider(),
            )

        state = observed["task"]
        self.assertEqual("running", state["state"])
        self.assertEqual("reserved", state["operation_results"]["reservation-op"]["status"])
        self.assertEqual("execution", state["operation_results"]["reservation-op"]["reservation"])
        self.assertFalse((self.root / "research" / "runs").exists())

    def test_reserved_operation_is_conflict_without_dispatch_and_cli_reports_it(self):
        class FailingProvider(FakeExecutionProvider):
            def execute(inner_self, request):
                raise RuntimeError("leave reservation")

        class CountingProvider(FakeExecutionProvider):
            def __init__(inner_self):
                super().__init__()
                inner_self.calls = 0

            def execute(inner_self, request):
                inner_self.calls += 1
                return super().execute(request)

        task_start(self.root, self.request("task-reserved"))
        with self.assertRaises(RuntimeError):
            task_run_fake(
                self.root, "task-reserved", "reserved-op", "fixture-a",
                fake_provider=FailingProvider(),
            )

        provider = CountingProvider()
        with self.assertRaisesRegex(ValueError, "requires reconciliation"):
            task_run_fake(
                self.root, "task-reserved", "reserved-op", "fixture-a",
                fake_provider=provider,
            )
        self.assertEqual(0, provider.calls)

        conflict = self.cli(
            "task-run-fake", "--project-root", str(self.root), "task-reserved",
            "--operation-id", "reserved-op", "--fixture-id", "fixture-a",
        )
        self.assertEqual(2, conflict.returncode)
        self.assertIn("requires reconciliation", conflict.stdout)

    def test_zotero_snapshot_requires_local_source_and_preserves_hashes(self):
        snapshot = self.root / "snapshot.json"
        snapshot.write_text(json.dumps({
            "schema_version": 1, "snapshot_type": "zotero_filtered_metadata",
            "instance_id": "b" * 16, "exported_at": "2026-09-05T00:00:00Z",
            "library": {"version": 1},
            "items": [{"item_key": "ITEM1", "version": 4, "item_type": "journalArticle",
                       "title": "Synthetic source", "collections": [], "tags": [], "attachments": []}],
        }), encoding="utf-8")
        source = self.root / "source.txt"
        source.write_text("A separately retained local source.\n", encoding="utf-8")
        req = self.request("task-lit")
        req["task_type"] = "mining_research_kernel.task.static_check"
        req["literature_evidence"] = {
            "snapshot_path": "snapshot.json", "source_path": "source.txt", "item_key": "ITEM1",
            "locator": {"kind": "paragraph", "value": "p1"},
            "question_statement": req["question_statement"],
            "claim_statement": req["claim_statement"],
        }
        packet = task_start(self.root, req)
        self.assertEqual("ready", packet["state"])
        view = research_map_rebuild(self.root)
        asset = next(node for node in view["nodes"] if node["type"] == "Asset")
        evidence = next(node for node in view["nodes"] if node["type"] == "Evidence")
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), asset["content_sha256"])
        self.assertEqual("snapshot.json", asset["locator"]["snapshot_path"])
        self.assertEqual("source.txt", asset["locator"]["source_path"])
        self.assertNotIn(str(self.root), json.dumps(asset, ensure_ascii=False))
        self.assertNotIn("evidence_supports_claim", {edge["relation"] for edge in view["edges"]})
        self.assertEqual("document", evidence["evidence_kind"])

        with self.assertRaises(ValueError):
            task_start(self.root, dict(self.request("metadata-only"), literature_evidence={
                "snapshot_path": "snapshot.json", "item_key": "ITEM1",
                "question_statement": self.request()["question_statement"],
                "claim_statement": self.request()["claim_statement"],
            }))

    def test_bad_item_and_production_fake_are_rejected(self):
        with self.assertRaises(ValueError):
            task_start(self.root, dict(self.request("bad-ref"), literature_evidence={
                "snapshot_path": "missing.json", "source_path": "source.txt", "item_key": "MISSING",
                "locator": {"line": 1}, "question_statement": self.request()["question_statement"],
                "claim_statement": self.request()["claim_statement"],
            }))
        production = self.request("production-task")
        production["task_context"] = "production"
        started = task_start(self.root, production)
        self.assertEqual("blocked", started["state"])
        result = self.cli("task-run-fake", "--project-root", str(self.root), "production-task",
                          "--operation-id", "blocked-op", "--fixture-id", "fixture")
        self.assertEqual(2, result.returncode)
        self.assertIn("production tasks cannot use", result.stdout)

    def test_literature_inputs_must_stay_inside_project(self):
        source = self.root / "source.txt"
        source.write_text("source\n", encoding="utf-8")
        request = self.request("path-boundary")
        request["literature_evidence"] = {
            "snapshot_path": str(self.root / "missing-snapshot.json"),
            "source_path": "source.txt",
            "item_key": "ITEM1",
            "locator": {"line": 1},
            "question_statement": request["question_statement"],
            "claim_statement": request["claim_statement"],
        }
        with self.assertRaisesRegex(ValueError, "project-relative"):
            task_start(self.root, request)


if __name__ == "__main__":
    unittest.main()
