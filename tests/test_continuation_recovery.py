from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from mining_research_kernel.on_demand import resume_task, show_record
from mining_research_kernel.project_context import project_context
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.research_continuation import continue_research
from mining_research_kernel.literature_comparison import record_literature_comparison
from tests import test_literature_comparison as fixtures

REPO = Path(__file__).resolve().parents[1]


class ContinuationRecoveryTests(unittest.TestCase):
    def setUp(self):
        fixtures.LiteratureComparisonTests.setUp(self)

    def tearDown(self):
        fixtures.LiteratureComparisonTests.tearDown(self)

    def _pending_child(self, child_id="pending-child"):
        parent = fixtures.LiteratureComparisonTests.start(self, "recovery-parent")
        decision = record_literature_comparison(
            self.project, task_id="recovery-parent", operation_id="record-parent",
            comparison=fixtures.LiteratureComparisonTests.comparison(self, parent["task_packet"]),
        )
        child = continue_research(self.project, task_id=child_id, from_task_id="recovery-parent",
                                  asset_refs=self.assets, reason="Compare another saved reading.")
        return decision["review_record_ref"], child["task_packet"]

    def _later_revision(self, decision_id):
        store = ResearchStore(self.project)
        prior = store.latest_record(decision_id, "Decision")
        later = copy.deepcopy(prior)
        later["revision"] += 1
        later["judgment"]["summary"] = "Synthetic later independent revision."
        store.commit("later-independent-decision", {"role": "acceptance_agent", "model": "test"}, [later])
        return prior, later

    def test_pending_continuation_keeps_exact_inherited_parent_and_budget_semantics(self):
        decision_id, _ = self._pending_child()
        parent_r1, _ = self._later_revision(decision_id)

        view = resume_task(self.project, "pending-child")
        self.assertEqual([], view["judgments"])
        self.assertEqual("pending_continuation_inherits_parent", view["judgment_selection"]["reason"])
        self.assertEqual([{"decision_id": decision_id, "revision": 1, "state": "inherited_pending"}],
                         view["judgment_selection"]["inherited_decisions"])
        self.assertEqual(parent_r1["judgment"]["summary"], view["inherited_judgments"][0]["summary"])
        self.assertEqual(len(parent_r1["judgment"].get("gaps", [])),
                         view["inherited_judgments"][0]["gap_count"])
        self.assertEqual("historical parent judgment; applicability remains bounded by recorded gaps",
                         view["inherited_judgments"][0]["scope"])
        self.assertTrue(view["inherited_judgments"][0]["gap_preview"])
        self.assertNotIn("Synthetic later independent revision.", json.dumps(view, ensure_ascii=False))
        self.assertEqual([], view["judgment_selection"].get("conflict_ids", []))
        self.assertLessEqual(view["budget"]["used_unicode_chars"], 4000)

        compact = resume_task(self.project, "pending-child", max_chars=1000)
        self.assertLessEqual(compact["budget"]["used_unicode_chars"], 1000)
        self.assertEqual([], compact["judgments"])
        self.assertEqual(1, compact["inherited_judgments"][0]["revision"])
        self.assertIn("--revision 1", " ".join(compact["expansion_commands"]))

    def test_completed_continuation_uses_its_own_bound_decision_revision(self):
        _, child = self._pending_child()
        receipt = record_literature_comparison(
            self.project, task_id="pending-child", operation_id="record-child",
            comparison=fixtures.LiteratureComparisonTests.comparison(self, child),
        )
        decision_id = receipt["review_record_ref"]
        before = ResearchStore(self.project).latest_record(decision_id, "Decision")
        later = copy.deepcopy(before)
        later["revision"] += 1
        later["judgment"]["summary"] = "Synthetic unbound later revision."
        ResearchStore(self.project).commit("child-unbound-later-revision",
                                           {"role": "acceptance_agent", "model": "test"}, [later])

        view = resume_task(self.project, "pending-child")

        self.assertEqual([decision_id], view["judgment_selection"]["current_decision_ids"])
        self.assertEqual(before["revision"], view["judgments"][0]["revision"])
        self.assertNotIn("Synthetic unbound later revision.", json.dumps(view, ensure_ascii=False))
        self.assertEqual([], view["inherited_judgments"])

    def test_unbound_same_task_branch_remains_conflict_and_sibling_isolated(self):
        decision_id, _ = self._pending_child()
        other_id, _ = self._pending_child("pending-sibling")
        store = ResearchStore(self.project)
        branch = copy.deepcopy(store.latest_record(decision_id, "Decision"))
        branch.update({"id": "pending-child-independent", "revision": 1,
                       "source_refs": ["task:pending-child"]})
        branch["scope"] = {**branch.get("scope", {}), "task_id": "pending-child"}
        store.commit("independent-same-task-branch", {"role": "acceptance_agent", "model": "test"}, [branch])

        first = resume_task(self.project, "pending-child")
        second = resume_task(self.project, "pending-sibling")
        self.assertEqual([], first["judgments"])
        first_conflicts = first["judgment_selection"].get("unresolved_conflict", {}).get("decision_ids", [])
        second_conflicts = second["judgment_selection"].get("unresolved_conflict", {}).get("decision_ids", [])
        self.assertIn("pending-child-independent", first_conflicts)
        self.assertNotIn("pending-child-independent", second_conflicts)
        self.assertEqual(other_id, second["judgment_selection"]["inherited_decisions"][0]["decision_id"])

    def test_show_exact_revision_is_read_only_and_rejects_invalid_revisions(self):
        decision_id, _ = self._pending_child()
        old, new = self._later_revision(decision_id)
        store = ResearchStore(self.project)
        before = len(store.list_transactions())
        shown = show_record(self.project, decision_id, revision=old["revision"], section="judgment")
        self.assertEqual(old["revision"], shown["revision"])
        self.assertEqual(old["judgment"]["summary"], shown["record"]["summary"])
        self.assertNotEqual(old["revision"], new["revision"])
        self.assertEqual(before, len(ResearchStore(self.project).list_transactions()))
        for invalid in (True, 0, -1, 1.5, "1"):
            with self.subTest(revision=invalid), self.assertRaises(ValueError):
                show_record(self.project, decision_id, revision=invalid)
        with self.assertRaisesRegex(ValueError, "unknown record revision"):
            show_record(self.project, decision_id, revision=99)

    def test_project_context_argv_runs_across_process_with_unicode_space_path(self):
        decision_id, _ = self._pending_child()
        base = Path(self.temp.name) / "研究 空格"
        base.mkdir()
        project = base / "study project"
        # Copy the synthetic project's records through normal transaction files so
        # the subprocess test exercises argv quoting without changing this fixture.
        import shutil
        shutil.copytree(self.project, project)
        offset = 0
        row = None
        while row is None:
            context = project_context(project, offset=offset, limit=20)
            row = next((item for item in context["items"]
                        if item.get("kind") == "task" and item["id"] == "pending-child"), None)
            if row is None:
                offset = context["page"]["next_offset"]
                if offset is None:
                    self.fail("pending task missing from project-context pages")
        argv = row["research_progress_argv"]
        self.assertIsInstance(argv, list)
        self.assertEqual(decision_id, row["inherited_decisions_preview"][0]["id"])
        progress = subprocess.run(argv, cwd=REPO, capture_output=True, text=True,
                                  encoding="utf-8", env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(0, progress.returncode, progress.stderr)
        self.assertEqual("pending-child", json.loads(progress.stdout)["task_id"])
        report = subprocess.run(row["research_report_argv"], cwd=REPO, capture_output=True,
                                text=True, encoding="utf-8")
        self.assertEqual(0, report.returncode, report.stderr)
