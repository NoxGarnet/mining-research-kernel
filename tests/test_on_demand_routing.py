import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.cognition import CoreCognition
from mining_research_kernel.on_demand import resume_task, show_record
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_record_evidence_review, task_start


class OnDemandRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "on_demand_routing")
        self.repo = Path(__file__).parents[1]
        self.env = os.environ.copy()
        self.env["PYTHONDONTWRITEBYTECODE"] = "1"

    def tearDown(self):
        self.temp.cleanup()

    def _materials(self, count=1):
        refs = []
        locations = {}
        for index in range(count):
            relative = Path("cases") / f"source-{index}.txt"
            (self.root / relative).write_text(f"synthetic source {index}\n", encoding="utf-8")
            result = ResearchStore(self.root).register_local_material(
                relative.as_posix(), "project_record"
            )
            refs.append((result["asset"]["id"], result["evidence"]["id"], relative.as_posix()))
            locations[result["asset"]["id"]] = {
                "path": relative.as_posix(), "path_kind": "project_relative"
            }
        return refs, locations

    def _request(self, task_id, refs, *, task_type="evidence_review"):
        return {
            "task_id": task_id,
            "question_statement": "Which persisted synthetic evidence should guide the next bounded action?",
            "claim_statement": "A compact recovery view preserves the relevant research state without rereading source files.",
            "task_type": f"mining_research_kernel.task.{task_type}",
            "maturity": "exploratory",
            "max_runs": 1,
            "task_context": "production",
            "asset_refs": [item[0] for item in refs],
            "evidence_refs": [item[1] for item in refs],
            "material_locations": {item[0]: {"path": item[2], "path_kind": "project_relative"} for item in refs},
        }

    def _assessment(self, packet, *, gaps=None, summary=None):
        reads = []
        for material in packet["material_reads"]:
            reads.append({
                "asset_id": material["asset_id"],
                "evidence_refs": material["evidence_refs"],
                "observed_sha256": material["content_sha256"],
                "reading_status": "READ_WITH_LIMITS",
                "verification_status": "NOT_VERIFIED",
                "locator": {"kind": "line", "value": "synthetic source lines 1-2"},
                "summary": "Read the selected synthetic source with bounded scope.",
                "numeric_check_status": "NOT_APPLICABLE",
                "scientific_validation_status": "NOT_VERIFIED",
                "gaps": [],
            })
        return {
            "scope": "material_reading_and_evidence_synthesis_only",
            "material_reads": reads,
            "material_gaps": [],
            "judgment": {
                "status": "PROVISIONAL_WITH_GAPS",
                "summary": summary or "The selected synthetic evidence is traceable but remains bounded.",
                "supported_evidence": ["the selected synthetic source records"],
                "gaps": gaps or ["no independent validation"],
                "next_action": {"action": "inspect the next bounded evidence", "executable": False},
            },
        }

    def _completed_task(self, task_id="resume-task", refs=None):
        refs = refs or self._materials()[0]
        packet = task_start(self.root, self._request(task_id, refs))
        return task_record_evidence_review(
            self.root, task_id, f"record-{task_id}", self._assessment(packet)
        )

    def test_resume_exposes_relevant_state_without_map_write(self):
        recorded = self._completed_task()
        map_path = self.root / "research" / "map.json"
        before = map_path.read_bytes()

        view = resume_task(self.root, "resume-task")

        self.assertEqual("TaskResumeView", view["type"])
        self.assertEqual("completed", view["state"])
        self.assertIn("persisted synthetic evidence", view["question"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", view["judgments"][0]["status"])
        gap_items = view["gaps"] if isinstance(view["gaps"], list) else view["gaps"]["items"]
        gap_texts = [item if isinstance(item, str) else item.get("text", item.get("preview", "")) for item in gap_items]
        self.assertIn("no independent validation", gap_texts)
        self.assertFalse(view["budget"]["overflow"])
        self.assertLessEqual(view["budget"]["used_unicode_chars"], 4000)
        self.assertEqual(view["budget"]["used_unicode_chars"], len(json.dumps(view, ensure_ascii=False, indent=2)))
        self.assertEqual(before, map_path.read_bytes())

        decision_view = show_record(self.root, recorded["review_record_ref"], section="judgment")
        self.assertEqual("Decision", decision_view["record_type"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", decision_view["record"]["status"])

    def test_resume_cli_works_in_new_process_and_show_is_targeted(self):
        recorded = self._completed_task("cli-resume-task")
        resumed = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "resume",
             "--project", str(self.root), "--task", "cli-resume-task"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, resumed.returncode, resumed.stderr)
        view = json.loads(resumed.stdout)
        self.assertEqual("cli-resume-task", view["task_id"])
        self.assertIn(recorded["review_record_ref"], view["citations"]["decision_ids"])

        shown = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "show",
             "--project-root", str(self.root), "--record-id", recorded["review_record_ref"],
             "--section", "assessment"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(0, shown.returncode, shown.stderr)
        self.assertEqual("assessment", json.loads(shown.stdout)["section"])

    def test_unrelated_failure_is_not_loaded_but_related_failure_is_visible(self):
        recorded = self._completed_task("failure-filter-task")
        route_id = ResearchStore(self.root).latest_record("failure-filter-task", "TaskState")["packet"]["routes"][0]
        cognition = CoreCognition(self.root)
        cognition.record_failure({
            "failure_id": "related-failure",
            "observable_failure": "related bounded failure",
            "task_id": "failure-filter-task",
            "route_id": route_id,
        }, "record-related-failure")
        cognition.record_failure({
            "failure_id": "unrelated-failure",
            "observable_failure": "unrelated bounded failure",
            "task_id": "other-task",
        }, "record-unrelated-failure")

        view = resume_task(self.root, "failure-filter-task")

        failure_ids = {item["failure_id"] for item in view["attempts_and_stops"]["related_failures"]}
        self.assertEqual({"related-failure"}, failure_ids)
        gap_items = view["gaps"] if isinstance(view["gaps"], list) else view["gaps"]["items"]
        gap_texts = [item if isinstance(item, str) else item.get("text", item.get("preview", "")) for item in gap_items]
        self.assertTrue(any("related bounded failure" in text for text in gap_texts))
        self.assertNotIn("unrelated bounded failure", json.dumps(view, ensure_ascii=False))

    def test_resume_preserves_static_capability_gap_without_execution(self):
        refs, _ = self._materials()
        packet = task_start(self.root, self._request("static-gap-task", refs, task_type="static_check"))
        self.assertEqual("blocked", packet["state"])

        view = resume_task(self.root, "static-gap-task")

        self.assertEqual("blocked", view["state"])
        self.assertIn("static_check_unimplemented", json.dumps(view, ensure_ascii=False))
        self.assertEqual([], view["judgments"])

    def test_long_gap_reports_overflow_and_exact_expansion(self):
        refs, _ = self._materials()
        packet = task_start(self.root, self._request("long-gap-task", refs))
        long_gap = "unverified limitation " + ("x" * 6500)
        task_record_evidence_review(
            self.root, "long-gap-task", "record-long-gap",
            self._assessment(packet, gaps=[long_gap], summary="bounded judgment"),
        )

        view = resume_task(self.root, "long-gap-task")

        self.assertTrue(view["overflow"]["occurred"])
        self.assertLessEqual(view["budget"]["used_unicode_chars"], 4000)
        self.assertEqual(view["budget"]["used_unicode_chars"], len(json.dumps(view, ensure_ascii=False, indent=2)))
        self.assertTrue(view["gaps"]["full_available"])
        self.assertTrue(any("show" in command for command in view["expansion_commands"]))

    def test_no_judgment_is_explicit_not_invented_and_two_material_versions_remain_visible(self):
        refs, _ = self._materials(count=2)
        task_start(self.root, self._request("no-judgment-task", refs))

        view = resume_task(self.root, "no-judgment-task")

        self.assertEqual([], view["judgments"])
        self.assertEqual(2, len(view["version_scope"]["materials"]))
        self.assertTrue(view["candidate_actions"])

    def test_resume_keeps_old_decision_material_when_current_task_has_new_version(self):
        old_refs, _ = self._materials()
        old = self._completed_task("old-version-task", old_refs)
        new_refs, _ = self._materials()
        request = self._request("new-version-task", new_refs)
        request["refs"] = {"decisions": [old["review_record_ref"]]}
        task_start(self.root, request)

        view = resume_task(self.root, "new-version-task")

        asset_ids = {item["asset_id"] for item in view["version_scope"]["materials"]}
        self.assertEqual({old_refs[0][0], new_refs[0][0]}, asset_ids)
        self.assertIn(old["review_record_ref"], view["citations"]["decision_ids"])

    def test_real_scale_material_counts_keep_judgment_and_exact_budget(self):
        for count in (8, 4):
            task_id = f"real-scale-{count}-task"
            refs, _ = self._materials(count=count)
            packet = task_start(self.root, self._request(task_id, refs))
            recorded = task_record_evidence_review(
                self.root, task_id, f"record-{task_id}",
                self._assessment(
                    packet,
                    summary=(
                        "The selected material set is internally traceable, but the stored result remains bounded "
                        "by its recorded input revision and unverified scientific conditions."
                    ),
                    gaps=["current revision is not independently validated", "no physical validation"],
                ),
            )
            view = resume_task(self.root, task_id)
            self.assertEqual(recorded["review_record_ref"], view["judgments"][0]["decision_id"])
            self.assertTrue(view["judgments"][0]["summary"])
            self.assertEqual(view["budget"]["used_unicode_chars"], len(json.dumps(view, ensure_ascii=False, indent=2)))
            self.assertLessEqual(view["budget"]["used_unicode_chars"], 4000)

    def test_multiple_explicit_decisions_surface_conflict_instead_of_selecting_by_order(self):
        refs, _ = self._materials()
        first = self._completed_task("conflict-source-a", refs)
        second = self._completed_task("conflict-source-b", refs)
        request = self._request("conflict-review", refs)
        request["refs"] = {"decisions": [first["review_record_ref"], second["review_record_ref"]]}
        task_start(self.root, request)

        view = resume_task(self.root, "conflict-review")

        self.assertEqual("unresolved_current_conflict", view["judgment_selection"]["reason"])
        self.assertEqual(
            {first["review_record_ref"], second["review_record_ref"]},
            set(view["judgment_selection"]["unresolved_conflict"]["decision_ids"]),
        )
        self.assertEqual(
            {first["review_record_ref"], second["review_record_ref"]},
            {item["decision_id"] for item in view["judgments"]},
        )
        self.assertEqual(view["budget"]["used_unicode_chars"], len(json.dumps(view, ensure_ascii=False, indent=2)))
        self.assertLessEqual(view["budget"]["used_unicode_chars"], 4000)


if __name__ == "__main__":
    unittest.main()
