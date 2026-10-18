from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from examples.continuing_research.demo import _safe_root
from mining_research_kernel import artifacts
from mining_research_kernel.records import ResearchStore
from research_project import enable_research

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "examples" / "continuing_research" / "demo.py"


class ContinuingResearchExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mrk-continuing-example-", dir=REPO.parent)
        self.base = Path(self.temp.name)
        self.project = self.base / "持续研究 demo"
        self.other_cwd = self.base / "different working directory"
        self.other_cwd.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def run_demo(self, stage: str, root: Path | None = None, *, cwd: Path | None = None,
                 expected: int = 0) -> subprocess.CompletedProcess:
        result = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(SCRIPT), stage, "--project-root", str(root or self.project)],
            cwd=cwd or self.other_cwd, capture_output=True, text=True, encoding="utf-8", timeout=60,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        self.assertEqual(expected, result.returncode, result.stdout + result.stderr)
        return result

    def test_separate_processes_keep_question_and_parent_and_replay_stably(self):
        self.run_demo("first")
        store = ResearchStore(self.project)
        parent = store.latest_record("synthetic-review-01", "TaskState")
        parent_decision_id = parent["packet"]["review_record_ref"]
        parent_decision = store.latest_record(parent_decision_id, "Decision")
        self.assertEqual("INSUFFICIENT", parent_decision["judgment"]["status"])
        question_id = parent["packet"]["input"]["research_question_id"]
        self.assertIn("合成", parent["packet"]["input"]["review_question"])

        self.run_demo("continue", cwd=self.base)
        progress = subprocess.run(
            [sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"), "research-progress",
             "--project-root", str(self.project), "--task-id", "synthetic-review-02"],
            cwd=self.other_cwd, capture_output=True, text=True, encoding="utf-8", timeout=45,
        )
        self.assertEqual(0, progress.returncode, progress.stdout + progress.stderr)
        recovered = json.loads(progress.stdout)
        self.assertEqual(question_id, recovered["question_id"])
        self.assertEqual(["synthetic-review-01", "synthetic-review-02"],
                         [step["task_id"] for step in recovered["steps"]])
        child = ResearchStore(self.project).latest_record("synthetic-review-02", "TaskState")
        self.assertEqual(parent_decision_id, child["packet"]["input"]["research_continuation"]["previous_decision_id"])
        self.assertEqual(parent_decision, ResearchStore(self.project).latest_record(parent_decision_id, "Decision"))
        final = ResearchStore(self.project).latest_record(child["packet"]["review_record_ref"], "Decision")
        self.assertEqual("PROVISIONAL_WITH_GAPS", final["judgment"]["status"])
        report = self.project / "reports" / "continuing-research.md"
        original_bytes = report.read_bytes()
        transactions = sorted(path.read_bytes() for path in (self.project / "research" / "records").glob("*.json"))
        self.assertIn("双传感器", original_bytes.decode("utf-8"))

        self.run_demo("continue")
        self.assertEqual(original_bytes, report.read_bytes())
        self.assertEqual(transactions, sorted(path.read_bytes() for path in
                         (self.project / "research" / "records").glob("*.json")))

    def test_first_refuses_nonempty_and_repository_targets(self):
        occupied = self.base / "occupied"
        occupied.mkdir()
        sentinel = occupied / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        self.run_demo("first", occupied, expected=2)
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
        self.run_demo("first", REPO, expected=2)
        self.assertFalse((REPO / "research_project.json").exists())

    def test_continue_rejects_ordinary_research_project_without_changes(self):
        ordinary = self.base / "ordinary"
        ordinary.mkdir()
        enable_research(ordinary, "ordinary-user-project")
        before = sorted(path.read_bytes() for path in ordinary.rglob("*" ) if path.is_file())
        self.run_demo("continue", ordinary, expected=2)
        after = sorted(path.read_bytes() for path in ordinary.rglob("*") if path.is_file())
        self.assertEqual(before, after)

    def test_shared_reparse_guard_rejects_junction_and_dangling_link_paths(self):
        candidate = self.base / "reparse project"
        candidate.mkdir()
        real_check = artifacts._is_reparse_point

        def reparse_check(path: Path) -> bool:
            return path == candidate or real_check(path)

        with patch("mining_research_kernel.artifacts._is_reparse_point", side_effect=reparse_check):
            with self.assertRaisesRegex(ValueError, "symlink or junction"):
                _safe_root(str(candidate))
        # The shared guard uses lexists, so a dangling link is checked too;
        # this assertion exercises that branch without requiring Windows link privileges.
        with patch("mining_research_kernel.artifacts.os.path.lexists", return_value=True), \
             patch("mining_research_kernel.artifacts._is_reparse_point", return_value=True):
            with self.assertRaisesRegex(ValueError, "symlink or junction"):
                artifacts._reject_reparse_chain(candidate, "test project root")


if __name__ == "__main__":
    unittest.main()
