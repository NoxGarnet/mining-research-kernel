from __future__ import annotations

import copy
import unittest
from unittest.mock import patch
from pathlib import Path

from mining_research_kernel.literature_comparison import record_literature_comparison
from mining_research_kernel.records import ResearchStore, ResearchStoreError
from mining_research_kernel.research_continuation import begin_research, continue_research, research_progress
from mining_research_kernel.research_report import render_research_report
from tests import test_literature_comparison as comparison_fixtures
from tests import test_source_review as source_review_fixtures
from research_project import enable_research


class ResearchContinuationTests(unittest.TestCase):
    def setUp(self):
        comparison_fixtures.LiteratureComparisonTests.setUp(self)

    def tearDown(self):
        comparison_fixtures.LiteratureComparisonTests.tearDown(self)

    def test_comparison_continuation_reuses_question_and_preserves_parent(self):
        parent = comparison_fixtures.LiteratureComparisonTests.start(self, "first-review")
        parent_packet = copy.deepcopy(parent["task_packet"])
        parent_decision = record_literature_comparison(
            self.project, task_id="first-review", operation_id="record-first",
            comparison=comparison_fixtures.LiteratureComparisonTests.comparison(self, parent_packet),
        )
        before = ResearchStore(self.project)
        old_question = before.latest_record("first-review.question.1", "ResearchQuestion")
        old_state = before.latest_record("first-review", "TaskState")
        old_decision = before.latest_record(parent_decision["review_record_ref"], "Decision")

        continued = continue_research(self.project, task_id="second-review", from_task_id="first-review",
                                      asset_refs=self.assets, reason="Compare a second saved reading.")
        packet = continued["task_packet"]
        self.assertEqual(old_question["id"], continued["question_id"])
        self.assertEqual(old_question["id"], packet["input"]["research_question_id"])
        self.assertEqual(parent_decision["review_record_ref"], packet["refs"]["decisions"][0])
        self.assertEqual(2, len(continued["sources"]))
        self.assertTrue(continued["comparison_template"])

        after = ResearchStore(self.project)
        self.assertEqual(old_question, after.latest_record(old_question["id"], "ResearchQuestion"))
        self.assertEqual(old_state, after.latest_record("first-review", "TaskState"))
        self.assertEqual(old_decision, after.latest_record(old_decision["id"], "Decision"))
        self.assertEqual(1, sum(record.get("id") == old_question["id"]
                                for tx in after.list_transactions() for record in tx["records"]))

        # A later revision of the base Decision must not reset an exact replay
        # or change the revision captured in the continuation link.
        drifted_decision = copy.deepcopy(old_decision)
        drifted_decision["revision"] += 1
        after.commit("later-base-decision-revision", {"role": "acceptance_agent", "model": "test"},
                     [drifted_decision])
        tx_count = len(after.list_transactions())
        replay = continue_research(self.project, task_id="second-review", from_task_id="first-review",
                                   asset_refs=self.assets, reason="Compare a second saved reading.")
        self.assertTrue(replay["replayed"])
        self.assertEqual(packet, replay["task_packet"])
        self.assertEqual(tx_count, len(ResearchStore(self.project).list_transactions()))
        self.assertIn("已完成并按版本绑定的历史判断",
                      render_research_report(self.project, task_id="second-review"))
        with self.assertRaisesRegex(ValueError, "different continuation"):
            continue_research(self.project, task_id="second-review", from_task_id="first-review",
                              asset_refs=self.assets, reason="Changed request")
        progress = research_progress(self.project, task_id="second-review")
        self.assertEqual(["first-review", "second-review"], [row["task_id"] for row in progress["steps"]])
        self.assertFalse(progress["source_queries_performed"])


class LegacyCombinedContinuationTests(unittest.TestCase):
    def setUp(self):
        source_review_fixtures.SourceReviewTests.setUp(self)

    def tearDown(self):
        source_review_fixtures.SourceReviewTests.tearDown(self)

    def refs(self):
        return source_review_fixtures.SourceReviewTests.refs(self)

    def test_legacy_combined_task_inherits_combined_mode_without_two_paper_gate(self):
        started = source_review_fixtures.SourceReviewTests.start(self, "legacy-research-start")
        evidence_id = started["task_packet"]["evidence_refs"][0]
        from mining_research_kernel.source_review import record_source_review
        record_source_review(self.project, task_id="legacy-research-start", operation_id="legacy-review",
                             note=source_review_fixtures.SourceReviewTests.note(self, evidence_id))
        continued = continue_research(self.project, task_id="legacy-research-next",
                                      from_task_id="legacy-research-start")
        self.assertEqual("combined_sources", continued["review_mode"])
        self.assertIn("review_template", continued)
        self.assertNotIn("comparison_template", continued)


class SelectedSourcesContinuationTests(unittest.TestCase):
    def setUp(self):
        comparison_fixtures.LiteratureComparisonTests.setUp(self)

    def tearDown(self):
        comparison_fixtures.LiteratureComparisonTests.tearDown(self)

    def test_one_saved_paper_can_be_reviewed_and_continued_without_two_source_gate(self):
        started = begin_research(self.project, task_id="single-paper-step", question="What does this reading report?",
                                 asset_refs=[self.assets[0]], mode="sources", task_context="synthetic")
        self.assertEqual("selected_sources", started["review_mode"])
        evidence_id = started["task_packet"]["evidence_refs"][0]
        from mining_research_kernel.source_review import record_source_review
        note = ("## Summary\nOne saved paper provides a bounded observation.\n\n"
                "## Findings\n- The selected page contains a reported observation. [evidence:" + evidence_id + "]\n\n"
                "## Gaps\n- Only the saved reading scope is covered.\n\n"
                "## Next\nThe user can choose whether to read another page.\n")
        record_source_review(self.project, task_id="single-paper-step", operation_id="single-paper-review", note=note)
        continued = continue_research(self.project, task_id="single-paper-next", from_task_id="single-paper-step")
        self.assertEqual(started["question_id"], continued["question_id"])
        self.assertEqual("selected_sources", continued["review_mode"])
        self.assertEqual([self.assets[0]], continued["task_packet"]["asset_refs"])
        self.assertEqual(1, len(continued["sources"]))
        self.assertIn("review_template", continued)


class ContinuationRaceTests(unittest.TestCase):
    def setUp(self):
        comparison_fixtures.LiteratureComparisonTests.setUp(self)

    def tearDown(self):
        comparison_fixtures.LiteratureComparisonTests.tearDown(self)

    def test_question_statement_drift_rejects_continuation_but_allows_status_revision(self):
        parent = comparison_fixtures.LiteratureComparisonTests.start(self, "question-drift-parent")
        record_literature_comparison(
            self.project, task_id="question-drift-parent", operation_id="question-drift-review",
            comparison=comparison_fixtures.LiteratureComparisonTests.comparison(self, parent["task_packet"]))
        store = ResearchStore(self.project)
        question = store.latest_record("question-drift-parent.question.1", "ResearchQuestion")
        status_revision = copy.deepcopy(question)
        status_revision.update(revision=question["revision"] + 1, status="paused")
        store.commit("question-status-only", {"role": "planning_agent", "model": "test"}, [status_revision])
        continue_research(self.project, task_id="status-only-child", from_task_id="question-drift-parent",
                          asset_refs=self.assets)
        changed = copy.deepcopy(status_revision)
        changed.update(revision=status_revision["revision"] + 1, statement="A different research question")
        store.commit("question-statement-changed", {"role": "planning_agent", "model": "test"}, [changed])
        with self.assertRaisesRegex(ValueError, "statement changed"):
            continue_research(self.project, task_id="reject-changed-question", from_task_id="question-drift-parent",
                              asset_refs=self.assets)
        self.assertIsNone(store.latest_record("reject-changed-question", "TaskState"))

    def test_parent_revision_change_between_validation_and_commit_is_rejected(self):
        parent = comparison_fixtures.LiteratureComparisonTests.start(self, "race-parent")
        record_literature_comparison(self.project, task_id="race-parent", operation_id="race-review",
                                     comparison=comparison_fixtures.LiteratureComparisonTests.comparison(
                                         self, parent["task_packet"]))
        real_commit = ResearchStore.commit

        def advance_parent_then_commit(store, operation_id, producer, records, relationships=None, **kwargs):
            if operation_id == "task-start.race-child":
                current = store.latest_record("race-parent", "TaskState")
                advanced = copy.deepcopy(current)
                advanced["revision"] += 1
                real_commit(store, "concurrent-parent-revision", producer, [advanced])
            return real_commit(store, operation_id, producer, records, relationships, **kwargs)

        with patch.object(ResearchStore, "commit", new=advance_parent_then_commit):
            with self.assertRaisesRegex(ResearchStoreError, "record revision changed"):
                continue_research(self.project, task_id="race-child", from_task_id="race-parent",
                                  asset_refs=self.assets)
        self.assertIsNone(ResearchStore(self.project).latest_record("race-child", "TaskState"))

    def _start_child(self, prefix):
        task_id = f"{prefix}-parent"
        parent = comparison_fixtures.LiteratureComparisonTests.start(self, task_id)
        record_literature_comparison(
            self.project, task_id=task_id, operation_id=f"{prefix}-review",
            comparison=comparison_fixtures.LiteratureComparisonTests.comparison(self, parent["task_packet"]))
        child_id = f"{prefix}-child"
        continue_research(self.project, task_id=child_id, from_task_id=task_id, asset_refs=self.assets)
        return task_id, child_id

    def test_progress_rejects_corrupt_decision_revision_and_question_link(self):
        store = ResearchStore(self.project)
        _parent, child_id = self._start_child("corrupt-decision")
        child = store.latest_record(child_id, "TaskState")
        corrupted = copy.deepcopy(child)
        corrupted["revision"] += 1
        corrupted["packet"]["input"]["research_continuation"]["previous_decision_revision"] = 99
        store.commit("corrupt-decision-link", {"role": "planning_agent", "model": "test"}, [corrupted])
        with self.assertRaisesRegex(ValueError, "missing Decision revision"):
            research_progress(self.project, task_id=child_id)

        _parent, question_child = self._start_child("corrupt-question")
        question = store.latest_record("corrupt-question-parent.question.1", "ResearchQuestion")
        other = copy.deepcopy(question)
        other.update(id="different.question.1", revision=1, statement="A different question")
        store.commit("add-other-question", {"role": "planning_agent", "model": "test"}, [other])
        state = store.latest_record(question_child, "TaskState")
        changed = copy.deepcopy(state)
        changed["revision"] += 1
        changed["packet"]["input"]["research_continuation"]["question_id"] = other["id"]
        store.commit("corrupt-question-link", {"role": "planning_agent", "model": "test"}, [changed])
        with self.assertRaisesRegex(ValueError, "different ResearchQuestion"):
            research_progress(self.project, task_id=question_child)

    def test_continuation_cannot_cross_project_boundary(self):
        parent = comparison_fixtures.LiteratureComparisonTests.start(self, "project-boundary-parent")
        record_literature_comparison(
            self.project, task_id="project-boundary-parent", operation_id="project-boundary-review",
            comparison=comparison_fixtures.LiteratureComparisonTests.comparison(self, parent["task_packet"]))
        other = Path(self.temp.name) / "other-project"
        other.mkdir()
        enable_research(other, "other.project")
        with self.assertRaisesRegex(ValueError, "unknown task"):
            continue_research(other, task_id="foreign-child", from_task_id="project-boundary-parent",
                              asset_refs=self.assets)
        self.assertIsNone(ResearchStore(other).latest_record("foreign-child", "TaskState"))
