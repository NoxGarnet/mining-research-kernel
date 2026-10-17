"""An exported historical pointer must expand the saved revision across processes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from mining_research_kernel.r2_workflow import _record
from mining_research_kernel.records import ResearchStore
from research_project import enable_research


REPO = Path(__file__).resolve().parents[1]


class HistoricalShowCLITests(unittest.TestCase):
    def test_exact_revision_survives_later_update_and_missing_revision_fails(self):
        with tempfile.TemporaryDirectory(prefix="historical-show-", dir=REPO / "tests") as tmp:
            root = Path(tmp) / "研究 project"
            root.mkdir()
            enable_research(root, "historical-show")
            store = ResearchStore(root)
            original = _record("ResearchQuestion", "saved.question", store.project_id, [],
                               statement="Original bounded question.", status="open")
            store.commit("original-question", {"role": "test", "model": "synthetic"}, [original])
            changed = copy.deepcopy(original)
            changed.update(revision=2, statement="A later independently revised question.")
            store.commit("later-question", {"role": "test", "model": "synthetic"}, [changed])

            def snapshot():
                return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in root.rglob("*") if p.is_file()}

            before = snapshot()
            command = [sys.executable, "-B", "-X", "utf8", str(REPO / "mining_kernel.py"),
                       "show", "--project-root", str(root), "--record-id", "saved.question",
                       "--section", "statement"]
            for revision, expected in ((None, changed), (1, original)):
                run = subprocess.run(command + ([] if revision is None else ["--revision", str(revision)]),
                                     cwd=tmp, capture_output=True, text=True, encoding="utf-8", timeout=30)
                self.assertEqual(0, run.returncode, run.stdout + run.stderr)
                value = json.loads(run.stdout)
                self.assertEqual(expected["revision"], value["revision"])
                self.assertEqual(expected["statement"], value["record"])
            for bad in ("0", "-1", "9", "true"):
                run = subprocess.run(command + ["--revision", bad], cwd=tmp, capture_output=True,
                                     text=True, encoding="utf-8", timeout=30)
                self.assertNotEqual(0, run.returncode, run.stdout)
            self.assertEqual(before, snapshot())


if __name__ == "__main__":
    unittest.main()
