import json
import subprocess
import sys
import unittest

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_record_judgment_update
from tests.test_on_demand_routing import OnDemandRoutingTests


class IncrementalWritebackTests(unittest.TestCase):
    setUp = OnDemandRoutingTests.setUp
    tearDown = OnDemandRoutingTests.tearDown
    _materials = OnDemandRoutingTests._materials
    _request = OnDemandRoutingTests._request
    _assessment = OnDemandRoutingTests._assessment
    _completed_task = OnDemandRoutingTests._completed_task

    def _update(self, recorded, evidence_id, **overrides):
        update = {
            "base_decision_id": recorded["review_record_ref"],
            "base_revision": 1,
            "change_kind": "supplement",
            "status": "PROVISIONAL_WITH_GAPS",
            "statement": "A new bounded observation supplements the prior judgment without changing material provenance.",
            "supported_evidence": [evidence_id],
            "gaps": ["the new observation has no independent scientific validation"],
            "next_action": {"action": "review the new bounded observation", "executable": False},
            "changed_fields": ["summary", "supported_evidence", "gaps", "next_action"],
        }
        update.update(overrides)
        return update

    def test_short_delta_inherits_materials_and_preserves_prior_decision(self):
        recorded = self._completed_task("incremental-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        update = self._update(recorded, evidence_id)

        result = task_record_judgment_update(
            self.root, "incremental-task", "incremental-op", update
        )

        self.assertEqual("incremental_update_recorded", result["review_status"])
        self.assertTrue(result["incremental_update"]["material_reads_inherited"])
        self.assertEqual(3, ResearchStore(self.root).latest_record("incremental-task", "TaskState")["revision"])
        self.assertFalse(result["operation_result"]["run_created"])
        self.assertFalse(result["operation_result"]["verification_created"])
        self.assertIsNotNone(ResearchStore(self.root).latest_record(recorded["review_record_ref"], "Decision"))
        new_decision = ResearchStore(self.root).latest_record(result["review_record_ref"], "Decision")
        self.assertEqual("incremental_judgment_update", new_decision["scope"]["kind"])
        self.assertEqual(recorded["review_record_ref"], new_decision["judgment"]["inherited_from"]["decision_id"])

        resumed = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "resume",
             "--project-root", str(self.root), "--task", "incremental-task"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, resumed.returncode, resumed.stderr)
        view = json.loads(resumed.stdout)
        self.assertIn(result["review_record_ref"], view["citations"]["decision_ids"])
        self.assertTrue(any("new bounded observation" in item["summary"] for item in view["judgments"]))

    def test_delta_rejects_revision_conflict_unknown_evidence_and_long_input(self):
        recorded = self._completed_task("incremental-reject-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        with self.assertRaisesRegex(ValueError, "revision conflict"):
            task_record_judgment_update(
                self.root, "incremental-reject-task", "bad-revision",
                self._update(recorded, evidence_id, base_revision=2),
            )
        with self.assertRaisesRegex(ValueError, "unknown supported_evidence"):
            task_record_judgment_update(
                self.root, "incremental-reject-task", "bad-evidence",
                self._update(recorded, "evidence.missing"),
            )
        with self.assertRaisesRegex(ValueError, "<= 2000"):
            task_record_judgment_update(
                self.root, "incremental-reject-task", "too-long",
                self._update(recorded, evidence_id, statement="x" * 2100),
            )

    def test_delta_is_idempotent_but_conflicting_reuse_is_rejected(self):
        recorded = self._completed_task("incremental-idempotent-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        update = self._update(recorded, evidence_id)
        first = task_record_judgment_update(
            self.root, "incremental-idempotent-task", "same-op", update
        )
        repeated = task_record_judgment_update(
            self.root, "incremental-idempotent-task", "same-op", update
        )
        self.assertEqual(first["operation_result"], repeated["operation_result"])
        with self.assertRaisesRegex(ValueError, "different update"):
            task_record_judgment_update(
                self.root, "incremental-idempotent-task", "same-op",
                self._update(recorded, evidence_id, statement="different delta"),
            )

    def test_cli_accepts_short_incremental_update(self):
        recorded = self._completed_task("incremental-cli-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        update_path = self.root / "incremental-update.json"
        update_path.write_text(json.dumps(self._update(recorded, evidence_id)), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "task-record-judgment-update",
             "--project-root", str(self.root), "incremental-cli-task",
             "--operation-id", "incremental-cli-op", "--update-json", "@" + str(update_path)],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("incremental_update_recorded", json.loads(result.stdout)["review_status"])

    def test_resume_selects_latest_incremental_branch_and_keeps_history_after_three_updates(self):
        recorded = self._completed_task("incremental-history-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        current_id = recorded["review_record_ref"]
        kinds = ["supplement", "contradiction", "version_replacement"]
        results = []
        for index, change_kind in enumerate(kinds, start=1):
            result = task_record_judgment_update(
                self.root,
                "incremental-history-task",
                f"incremental-history-op-{index}",
                self._update(
                    {"review_record_ref": current_id},
                    evidence_id,
                    base_decision_id=current_id,
                    change_kind=change_kind,
                    statement=f"Update {index} is a bounded {change_kind} observation.",
                ),
            )
            current_id = result["review_record_ref"]
            results.append(result)

        resumed = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "resume",
             "--project-root", str(self.root), "--task", "incremental-history-task"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, resumed.returncode, resumed.stderr)
        view = json.loads(resumed.stdout)
        self.assertEqual([current_id], view["judgment_selection"]["current_decision_ids"])
        self.assertEqual(3, view["judgment_selection"]["historical_decision_count"])
        self.assertIn(current_id, view["citations"]["decision_ids"])
        self.assertIn("version_replacement", json.dumps(view, ensure_ascii=False))
        self.assertEqual(view["budget"]["used_unicode_chars"], len(json.dumps(view, ensure_ascii=False, indent=2)))
        self.assertLessEqual(view["budget"]["used_unicode_chars"], 4000)

    def test_success_binds_inherited_revisions_and_preserves_read_statuses(self):
        recorded = self._completed_task("incremental-revision-binding-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        result = task_record_judgment_update(
            self.root, "incremental-revision-binding-task", "revision-binding-op",
            self._update(recorded, evidence_id),
        )

        inherited = result["decision"]["judgment"]["inherited_material_revisions"]
        self.assertEqual(1, len(inherited))
        self.assertEqual(recorded["material_reads"][0]["asset_id"], inherited[0]["asset_id"])
        self.assertEqual("READ_WITH_LIMITS", inherited[0]["reading_status"])
        self.assertEqual("NOT_VERIFIED", inherited[0]["verification_status"])
        self.assertEqual(1, inherited[0]["asset_revision"])
        self.assertEqual(1, inherited[0]["evidence_revisions"][evidence_id])
        self.assertLessEqual(result["operation_result"]["input_unicode_chars"], 2000)

    def test_invalid_inheritance_evidence_shape_and_source_change_are_atomic(self):
        recorded = self._completed_task("incremental-validation-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]

        def snapshot():
            records = {
                path.name: path.read_bytes()
                for path in (self.root / "research" / "records").glob("*.json")
            }
            task = ResearchStore(self.root).latest_record("incremental-validation-task", "TaskState")
            return records, task["revision"], (self.root / "research" / "map.json").read_bytes()

        other_refs, _ = self._materials(count=2)
        unrelated_evidence = other_refs[1][1]
        before = snapshot()
        with self.assertRaisesRegex(ValueError, r"supported_evidence\[0\].*current task"):
            task_record_judgment_update(
                self.root, "incremental-validation-task", "unrelated-evidence-op",
                self._update(recorded, unrelated_evidence),
            )
        self.assertEqual(before, snapshot())

        bad_action = self._update(recorded, evidence_id, next_action={"action": "missing boolean"})
        with self.assertRaisesRegex(ValueError, "update.next_action.executable"):
            task_record_judgment_update(
                self.root, "incremental-validation-task", "bad-action-op", bad_action,
            )
        self.assertEqual(before, snapshot())

        source = self.root / "cases" / "source-0.txt"
        source.write_text("changed after the persisted read\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, r"packet.material_reads\[0\].source changed"):
            task_record_judgment_update(
                self.root, "incremental-validation-task", "changed-source-op",
                self._update(recorded, evidence_id),
            )
        after = snapshot()
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[1], after[1])
        self.assertEqual(before[2], after[2])

    def test_stale_or_wrong_base_decision_is_rejected_without_write(self):
        recorded = self._completed_task("incremental-inheritance-task")
        evidence_id = recorded["material_reads"][0]["evidence_refs"][0]
        advanced = task_record_judgment_update(
            self.root, "incremental-inheritance-task", "advance-inheritance-op",
            self._update(recorded, evidence_id),
        )
        before_files = {
            path.name: path.read_bytes()
            for path in (self.root / "research" / "records").glob("*.json")
        }
        before_revision = ResearchStore(self.root).latest_record(
            "incremental-inheritance-task", "TaskState"
        )["revision"]
        with self.assertRaisesRegex(ValueError, "packet.review_record_ref"):
            task_record_judgment_update(
                self.root, "incremental-inheritance-task", "stale-inheritance-op",
                self._update(recorded, evidence_id),
            )
        after_files = {
            path.name: path.read_bytes()
            for path in (self.root / "research" / "records").glob("*.json")
        }
        self.assertEqual(before_files, after_files)
        self.assertEqual(before_revision, ResearchStore(self.root).latest_record(
            "incremental-inheritance-task", "TaskState"
        )["revision"])
        self.assertEqual(advanced["review_record_ref"], ResearchStore(self.root).latest_record(
            "incremental-inheritance-task", "TaskState"
        )["packet"]["review_record_ref"])


del OnDemandRoutingTests


if __name__ == "__main__":
    unittest.main()
