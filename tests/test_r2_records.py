import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.records import ResearchStore, ResearchStoreError, WriterLockedError


class R2RecordStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "r2_project")
        self.store = ResearchStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def record(self, record_type, record_id, revision=1, **extra):
        base = {
            "schema_version": 1,
            "type": record_type,
            "id": record_id,
            "revision": revision,
            "project_id": "r2_project",
            "scope": {"study": "fixture"},
            "source_refs": ["fixture:source-1"],
        }
        defaults = {
            "ResearchQuestion": {"statement": "Does the fixture answer the question?", "status": "active"},
            "Hypothesis": {"statement": "The fixture is informative.", "status": "proposed"},
            "TaskState": {},
            "Asset": {
                "asset_kind": "source-file", "locator": {"path": "source.txt"},
                "content_sha256": "b" * 64, "authority": "authoritative", "status": "available",
            },
            "Claim": {"statement": "The fixture supports the claim.", "status": "proposed"},
            "Evidence": {
                "evidence_kind": "document",
                "asset_ref": "asset-1",
                "locator": {"page": 1},
                "status": "accepted",
            },
            "Route": {
                "status": "active", "question_id": "question-1", "hypothesis_id": None,
                "workflow_id": "workflow-1", "method_id": "method-1", "budget": 2,
            },
            "Failure": {"status": "observed", "observable_failure": "fixture failed"},
            "Decision": {"status": "accepted", "statement": "Close the route."},
            "Verification": {"status": "passed", "gate_id": "gate-1"},
            "RunReference": {"run_id": "run-1", "manifest_sha256": "a" * 64, "status": "accepted"},
        }
        base.update(defaults[record_type])
        if record_type == "TaskState":
            base.update({
                "task_id": record_id,
                "state": "proposed",
                "packet": {"project_id": "r2_project", "task_id": record_id, "next_action": None},
                "operation_results": {},
            })
        base.update(extra)
        return base

    def relationship(self, relationship_id, relation, from_id, from_revision, to_id, to_revision, revision=1):
        return {
            "schema_version": 1,
            "relationship_id": relationship_id,
            "revision": revision,
            "project_id": "r2_project",
            "relation": relation,
            "from_id": from_id,
            "from_revision": from_revision,
            "to_id": to_id,
            "to_revision": to_revision,
            "source_refs": ["fixture:source-1"],
        }

    def test_second_writer_rejected_and_lock_released_on_exception(self):
        with self.store.writer("writer-one"):
            with self.assertRaises(WriterLockedError):
                with self.store.writer("writer-two"):
                    pass
            self.assertTrue(self.store.lock_path.is_file())
        self.assertFalse(self.store.lock_path.exists())
        with self.assertRaises(RuntimeError):
            with self.store.writer("writer-three"):
                raise RuntimeError("test exception")
        self.assertFalse(self.store.lock_path.exists())

    def test_malformed_ids_and_traversal_are_rejected(self):
        for bad_id in ("../escape", "", "ümlaut", "a/b", "a" * 65):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ResearchStoreError):
                    self.store.commit("op-" + str(len(bad_id)), {"role": "planning", "model": "test"},
                                      [self.record("Claim", bad_id)])
        with self.assertRaises(ResearchStoreError):
            self.store.commit("op-dangling", {"role": "planning", "model": "test"},
                              [self.record("Claim", "claim-1")], [self.relationship(
                                  "edge-1", "evidence_supports_claim", "missing", 1, "claim-1", 1)])

    def test_all_r2_record_types_are_admitted_with_their_minimum_fields(self):
        record_types = (
            "ResearchQuestion", "Hypothesis", "TaskState", "Asset", "Claim", "Evidence",
            "Route", "Failure", "Decision", "Verification", "RunReference",
        )
        records = []
        for index, record_type in enumerate(record_types):
            record_id = {"Asset": "asset-1", "Evidence": "evidence-1"}.get(record_type, f"node-{index}")
            records.append(self.record(record_type, record_id))
        committed = self.store.commit("all-types", {"role": "planning", "model": "test"}, records, [
            self.relationship("evidence-asset", "evidence_derived_from_asset", "evidence-1", 1, "asset-1", 1)
        ])
        self.assertEqual(record_types, tuple(record["type"] for record in committed["records"]))
        with self.assertRaises(ResearchStoreError):
            self.store.commit("unknown-type", {"role": "planning", "model": "test"}, [
                self.record("Claim", "known", extra="ok") | {"type": "Unknown"}
            ])

    def test_run_reference_requires_lowercase_64_hex_manifest_digest(self):
        with self.assertRaisesRegex(ResearchStoreError, "manifest_sha256"):
            self.store.commit(
                "bad-manifest-digest", {"role": "execution", "model": "test"},
                [self.record("RunReference", "runref-invalid", manifest_sha256="A" * 64)],
            )

    def test_atomic_failures_leave_only_ignored_temp_and_after_replace_is_idempotent(self):
        def fail_before(stage):
            if stage == "before_replace":
                raise RuntimeError("injected before replace")

        with self.assertRaises(RuntimeError):
            self.store.commit("atomic-before", {"role": "execution", "model": "test"},
                              [self.record("Claim", "claim-before")], injection_hook=fail_before)
        self.assertEqual([], list(self.store.records_dir.glob("[0-9]*.json")))
        self.assertEqual([".atomic-before.tmp"], sorted(path.name for path in self.store.records_dir.iterdir()))
        self.assertEqual([], self.store.list_transactions())
        (self.store.records_dir / ".atomic-before.tmp").unlink()

        fired = {"after": False}

        def fail_after(stage):
            if stage == "after_replace" and not fired["after"]:
                fired["after"] = True
                raise RuntimeError("injected after replace")

        with self.assertRaises(RuntimeError):
            self.store.commit("atomic-after", {"role": "execution", "model": "test"},
                              [self.record("Claim", "claim-after")], injection_hook=fail_after)
        self.assertEqual([], [p.name for p in self.store.records_dir.iterdir() if p.name.endswith(".tmp")])
        committed = self.store.commit("atomic-after", {"role": "execution", "model": "test"},
                                       [self.record("Claim", "claim-after")])
        self.assertEqual(1, committed["sequence"])
        self.assertEqual(committed, self.store.commit("atomic-after", {"role": "execution", "model": "test"},
                                                       [self.record("Claim", "claim-after")]))

    def test_idempotency_conflict_and_revision_reference_validation(self):
        claim = self.record("Claim", "claim-1")
        self.store.commit("first", {"role": "planning", "model": "test"}, [claim])
        with self.assertRaises(ResearchStoreError):
            self.store.commit("first", {"role": "planning", "model": "test"},
                              [self.record("Claim", "claim-other")])
        with self.assertRaises(ResearchStoreError):
            self.store.commit("gap", {"role": "planning", "model": "test"},
                              [self.record("Claim", "claim-1", revision=3)])
        question = self.record("ResearchQuestion", "question-1")
        route = self.record("Route", "route-1", question_id="question-1")
        edge = self.relationship("route-question", "route_addresses_question", "route-1", 1,
                                  "question-1", 1)
        self.store.commit("second", {"role": "planning", "model": "test"}, [question, route], [edge])
        with self.assertRaises(ResearchStoreError):
            self.store.commit("bad-edge", {"role": "planning", "model": "test"}, [], [
                self.relationship("dangling", "route_addresses_question", "route-1", 1, "question-1", 2)
            ])
        with self.assertRaises(ResearchStoreError):
            self.store.commit("evidence-without-asset-edge", {"role": "planning", "model": "test"}, [
                self.record("Asset", "asset-1"), self.record("Evidence", "evidence-1")
            ])

    def test_task_state_revisions_are_authoritative_and_latest_record_is_deep_copied(self):
        task_id = "task-recovery"
        first = self.record("TaskState", task_id, packet={
            "project_id": "r2_project", "task_id": task_id, "state": "proposed"
        })
        self.store.commit("task-1", {"role": "planning", "model": "test"}, [first])
        second = self.record("TaskState", task_id, revision=2, state="completed", packet={
            "project_id": "r2_project", "task_id": task_id, "state": "completed",
            "nested": {"value": 2},
        })
        self.store.commit("task-2", {"role": "execution", "model": "test"}, [second])
        latest = self.store.latest_record(task_id)
        self.assertEqual("completed", latest["state"])
        latest["packet"]["nested"]["value"] = 999
        self.assertEqual(2, self.store.latest_record(task_id, "TaskState")["packet"]["nested"]["value"])
        self.assertIsNone(self.store.latest_record(task_id, "Claim"))
        with self.assertRaises(ResearchStoreError):
            self.store.latest_record(task_id, "Unknown")

        code = (
            "import json,sys; from mining_research_kernel.records import ResearchStore; "
            "print(json.dumps(ResearchStore(sys.argv[1]).latest_record(sys.argv[2]), "
            "ensure_ascii=False, sort_keys=True, separators=(',', ':')))"
        )
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(self.root), task_id],
            cwd=str(Path(__file__).parents[1]), capture_output=True, text=True, env=env,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(second, json.loads(result.stdout))

    def test_load_rejects_mutated_transaction_bytes_and_sequence_gaps(self):
        self.store.commit("immutable", {"role": "planning", "model": "test"},
                          [self.record("Claim", "claim-1")])
        transaction_path = self.store.records_dir / "00000001.json"
        transaction = json.loads(transaction_path.read_text(encoding="utf-8"))
        transaction["producer"]["model"] = "mutated"
        transaction_path.write_text(json.dumps(transaction), encoding="utf-8")
        with self.assertRaises(ResearchStoreError):
            self.store.list_transactions()

        transaction_path.write_text(json.dumps({}), encoding="utf-8")
        transaction_path.rename(self.store.records_dir / "00000002.json")
        with self.assertRaises(ResearchStoreError):
            self.store.list_transactions()

    def test_rebuild_is_deterministic_in_subprocess_and_after_view_deletion(self):
        question = self.record("ResearchQuestion", "question-1")
        claim = self.record("Claim", "claim-1")
        task = self.record("TaskState", "task-1")
        asset = self.record("Asset", "asset-1")
        evidence = self.record("Evidence", "evidence-1")
        self.store.commit("seed", {"role": "planning", "model": "test"},
                          [question, claim, task, asset, evidence], [
            self.relationship("support-1", "evidence_supports_claim", "evidence-1", 1, "claim-1", 1),
            self.relationship("derived-1", "evidence_derived_from_asset", "evidence-1", 1, "asset-1", 1),
        ])
        configured_map = self.root / "research" / "map.json"
        configured_bytes = configured_map.read_bytes()
        returned = self.store.rebuild_research_map()
        self.assertEqual("ResearchMap", returned["type"])
        self.assertEqual(configured_bytes, configured_map.read_bytes())
        view_path = self.root / "research" / "derived-map.json"
        first = self.store.rebuild_research_map(view_path)
        first_bytes = view_path.read_bytes()
        view_path.unlink()
        second = self.store.rebuild_research_map(view_path)
        self.assertEqual(first, second)
        self.assertEqual(first_bytes, view_path.read_bytes())
        self.assertEqual(["asset-1", "claim-1", "evidence-1", "question-1"], [n["id"] for n in first["nodes"]])
        self.assertNotIn("task-1", [n["id"] for n in first["nodes"]])
        self.assertEqual(
            {"evidence_supports_claim", "evidence_derived_from_asset"},
            {edge["relation"] for edge in first["edges"]},
        )

        code = (
            "import json,sys; from mining_research_kernel.records import ResearchStore; "
            "p=ResearchStore(sys.argv[1]).rebuild_research_map(sys.argv[2]); "
            "print(json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(',', ':')))"
        )
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [sys.executable, "-B", "-c", code, str(self.root), str(self.root / "research" / "subprocess-map.json")],
            cwd=str(Path(__file__).parents[1]), capture_output=True, text=True, env=env,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(first, json.loads(result.stdout))
        self.assertEqual(hashlib.sha256(first_bytes).hexdigest(),
                         hashlib.sha256(view_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
