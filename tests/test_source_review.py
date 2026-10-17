from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from mining_research_kernel.documentation_records import record_documentation_query
from mining_research_kernel.on_demand import resume_task
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.source_review import start_source_review, record_source_review, _payload_record
from mining_research_kernel.r2_workflow import _sha256_json
from mining_research_kernel.zotero_records import record_zotero_reading
from research_project import enable_research
from tests.test_r1_documentation import PAGE, html_page
from tests.test_zotero_records import capture
from flac3d_project import init_project


REPO = Path(__file__).resolve().parents[1]


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="source-review-", dir=REPO / "tests")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        enable_research(self.project, "source.review.project")
        docs = self.root / "docs"
        page_path = docs / Path(*PAGE.split("/"))
        page_path.parent.mkdir(parents=True)
        page_path.write_bytes(html_page())
        self.registration = self.root / "registration.json"
        self.registration.write_text(json.dumps({
            "schema_version": 1, "source_id": "example.docs.local", "root": str(docs),
            "product": "flac3d", "document_family": "9.6", "document_build": "9.6.44",
            "trust_class": "official_local", "product_subdir": "flac3d",
            "pages": {PAGE: hashlib.sha256(page_path.read_bytes()).hexdigest()},
        }), encoding="utf-8")
        self.literature = record_zotero_reading(
            self.project, task_id="source-lit", question="Read captured paper pages",
            capture=capture(origin="synthetic"), task_context="synthetic",
            findings=[{"statement": "Saved observation", "citation": {
                "attachment_key": "ATTACH01", "start_page": 12, "end_page": 13}}],
        )
        self.documentation = record_documentation_query(
            self.project, task_id="source-doc", question="Check documented command coverage",
            registration=self.registration, page=PAGE, command="zone list",
            product="flac3d", product_version="9.6",
        )

    def tearDown(self):
        self.temp.cleanup()

    def refs(self):
        store = ResearchStore(self.project)
        return [store.latest_record(i, "Asset")["id"] for i in (
            self.literature["task_packet"]["asset_refs"][0],
            self.documentation["task_packet"]["asset_refs"][0],
        )]

    def start(self, task_id="combined-review", context="synthetic"):
        return start_source_review(self.project, task_id=task_id,
                                   question="How does the saved literature relate to the documentation?",
                                   asset_refs=self.refs(), task_context=context)

    def note(self, evidence):
        return ("## Summary\nA bounded synthesis.\n\n## Findings\n"
                f"- The saved sources can be compared within their recorded scope. [evidence:{evidence}]\n\n"
                "## Gaps\n- Original sources were not freshly revalidated.\n\n## Next\nReview the source coverage before choosing a next task.\n")

    def test_requires_both_source_kinds_and_known_asset(self):
        with self.assertRaisesRegex(ValueError, "requires at least one Zotero capture"):
            start_source_review(self.project, task_id="docs-only", question="q",
                                asset_refs=[self.documentation["task_packet"]["asset_refs"][0]])
        with self.assertRaisesRegex(ValueError, "unknown asset_ref"):
            start_source_review(self.project, task_id="unknown", question="q",
                                asset_refs=["missing"])
        store = ResearchStore(self.project)
        with self.assertRaisesRegex(ValueError, "not bound to selected Asset"):
            _payload_record(store, self.refs()[0], [self.documentation["task_packet"]["evidence_refs"][0]])

    def test_changed_evidence_revision_requires_new_source_review(self):
        started = self.start()
        evidence_id = started["task_packet"]["evidence_refs"][0]
        store = ResearchStore(self.project)
        evidence = store.latest_record(evidence_id, "Evidence")
        changed = copy.deepcopy(evidence)
        changed["revision"] += 1
        changed["status"] = "scope_changed"
        from mining_research_kernel.r2_workflow import _relationship
        asset = store.latest_record(evidence["asset_ref"], "Asset")
        provenance = _relationship("changed-evidence-provenance", "evidence_derived_from_asset",
                                   changed, asset, store.project_id, ["test:evidence-change"])
        store.commit("change-source-evidence", {"role": "test", "model": "fixture"}, [changed], [provenance],
                     expected_revisions={evidence_id: evidence["revision"]})
        with self.assertRaisesRegex(ValueError, "Evidence revision changed"):
            record_source_review(self.project, task_id="combined-review", operation_id="review-changed",
                                 note=self.note(evidence_id))
        with self.assertRaisesRegex(ValueError, "revision or hash changed"):
            self.start()

    def test_production_rejects_synthetic_capture(self):
        with self.assertRaisesRegex(ValueError, "synthetic source records"):
            self.start(context="production")

    def test_start_replay_conflict_and_source_version_binding(self):
        first = self.start()
        self.assertEqual("evidence_review", first["task_packet"]["task_type"].rsplit(".", 1)[-1])
        self.assertEqual(2, len(first["sources"]))
        self.assertEqual(2, len(first["task_packet"]["relevant_decision_refs"]))
        self.assertFalse(first["replayed"])
        again = self.start()
        self.assertTrue(again["replayed"])
        self.assertEqual(first["task_packet"], again["task_packet"])
        with self.assertRaisesRegex(ValueError, "different source review inputs"):
            start_source_review(self.project, task_id="combined-review", question="different",
                                asset_refs=self.refs(), task_context="synthetic")
        store = ResearchStore(self.project)
        asset = store.latest_record(self.refs()[0], "Asset")
        changed = copy.deepcopy(asset)
        changed["revision"] += 1
        changed["payload"]["request"]["capture"]["item"]["title"] = "newer source revision"
        store.commit("source-payload-tamper", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={asset["id"]: asset["revision"]})
        with self.assertRaisesRegex(ValueError, "embedded payload hash mismatch"):
            self.start()
        changed = store.latest_record(asset["id"], "Asset")
        changed["revision"] += 1
        changed["content_sha256"] = _sha256_json(changed["payload"])
        store.commit("source-revision-3", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={asset["id"]: asset["revision"] + 1})
        with self.assertRaisesRegex(ValueError, "source Asset or Evidence revision or hash changed"):
            self.start()

    def test_legacy_combined_review_fingerprint_replays(self):
        started = self.start()
        store = ResearchStore(self.project)
        original = store.latest_record("combined-review", "TaskState")
        changed = copy.deepcopy(original)
        changed["revision"] += 1
        inputs = changed["packet"]["input"]
        inputs.pop("review_mode", None)
        inputs.pop("dimensions", None)
        inputs.pop("review_question", None)
        inputs["source_review_fingerprint"] = _sha256_json({
            "question": "How does the saved literature relate to the documentation?",
            "context": "synthetic", "bindings": inputs["source_bindings"],
        })
        store.commit("legacy-combined-review-state", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={original["id"]: original["revision"]})
        replay = self.start()
        self.assertTrue(replay["replayed"])
        self.assertEqual(started["task_packet"]["task_id"], replay["task_packet"]["task_id"])

    def test_malformed_embedded_capture_is_rejected_by_capture_validator(self):
        store = ResearchStore(self.project)
        asset = store.latest_record(self.refs()[0], "Asset")
        changed = copy.deepcopy(asset)
        changed["revision"] += 1
        changed["payload"]["request"]["capture"]["pages"] = "malformed"
        changed["content_sha256"] = _sha256_json(changed["payload"])
        store.commit("malformed-capture-revision", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={asset["id"]: asset["revision"]})
        with self.assertRaisesRegex(ValueError, "invalid Zotero capture payload"):
            start_source_review(self.project, task_id="malformed-capture", question="Validate saved capture",
                                asset_refs=self.refs(), task_context="synthetic")

    def test_review_enforces_citations_scope_and_idempotence(self):
        started = self.start()
        selected = started["task_packet"]["evidence_refs"]
        with self.assertRaisesRegex(ValueError, "unknown or unselected"):
            record_source_review(self.project, task_id="combined-review", operation_id="bad-ref",
                                 note=self.note("evidence:unknown"))
        result = record_source_review(self.project, task_id="combined-review", operation_id="record-1",
                                      note=self.note(selected[0]))
        replay = record_source_review(self.project, task_id="combined-review", operation_id="record-1",
                                      note=self.note(selected[0]))
        self.assertEqual(result["review_record_ref"], replay["review_record_ref"])
        packet = replay["task_packet"]
        self.assertEqual("completed", packet["state"])
        decision = ResearchStore(self.project).latest_record(result["review_record_ref"], "Decision")
        self.assertEqual("material_reading_and_evidence_synthesis_only", decision["scope"]["kind"])
        self.assertTrue(all(row["reading"]["scientific_validation_status"] == "NOT_VERIFIED"
                            and row["reading"]["numeric_check_status"] == "NOT_APPLICABLE"
                            for row in decision["assessment"]["material_reads"]))
        self.assertTrue(any("synthetic source" in gap for gap in decision["judgment"]["gaps"]))
        self.assertTrue(any("source version unknown or zero" in gap for gap in decision["judgment"]["gaps"]))
        self.assertTrue(any("coverage_scope=command_name_only" in gap for gap in decision["judgment"]["gaps"]))
        with self.assertRaisesRegex(ValueError, "different note"):
            record_source_review(self.project, task_id="combined-review", operation_id="record-1",
                                 note=self.note(selected[1]))

    def test_empty_findings_next_action_and_resume_unknown_citation(self):
        self.start()
        next_text = "Compare the captured passage with a complete source."
        note = ("## Summary\nNo interpretation is recorded yet.\n\n## Findings\n\n"
                "## Gaps\n- Interpretation is absent.\n\n## Next\n" + next_text + "\n")
        result = record_source_review(self.project, task_id="combined-review", operation_id="empty-findings",
                                      note=note)
        decision = ResearchStore(self.project).latest_record(result["review_record_ref"], "Decision")
        self.assertEqual("INSUFFICIENT", decision["judgment"]["status"])
        self.assertEqual({"action": next_text, "executable": False, "requires_user_choice": True},
                         decision["judgment"]["next_action"])
        resumed = resume_task(self.project, "combined-review")
        self.assertTrue(any(item.get("action") == next_text for item in resumed["candidate_actions"]))
        replay = record_source_review(self.project, task_id="combined-review", operation_id="empty-findings",
                                      note=note)
        self.assertEqual(result["review_record_ref"], replay["review_record_ref"])
        summary_with_unknown_ref = note.replace("No interpretation is recorded yet.",
                                                "No interpretation. [evidence:unknown]")
        with self.assertRaisesRegex(ValueError, "unknown or unselected Evidence"):
            record_source_review(self.project, task_id="combined-review", operation_id="unknown-summary-cite",
                                 note=summary_with_unknown_ref)

    def test_legacy_flac3d_project_starts_research_workflow(self):
        legacy = self.root / "legacy"
        init_project(legacy, "legacyresearch")
        literature = record_zotero_reading(
            legacy, task_id="legacy-lit", question="Read this supplied capture",
            capture=capture(origin="external_mcp"), task_context="production",
        )
        documentation = record_documentation_query(
            legacy, task_id="legacy-doc", question="Check the saved documentation query",
            registration=self.registration, page=PAGE, command="zone list",
            product="flac3d", product_version="9.6",
        )
        packet = start_source_review(
            legacy, task_id="legacy-review", question="Compare selected records",
            asset_refs=[literature["task_packet"]["asset_refs"][0],
                        documentation["task_packet"]["asset_refs"][0]],
        )["task_packet"]
        self.assertEqual("mining_research_kernel.workflow.research", packet["workflow_id"])

    def test_failed_and_unverified_documentation_keeps_limits_in_gaps(self):
        page = {"attachment_key": "ATTACH01", "attachment_version": 0,
                "start_page": 1, "end_page": 1, "status": "unavailable",
                "text_sha256": None, "excerpt": ""}
        failed_literature = record_zotero_reading(
            self.project, task_id="source-lit-failed", question="Read failed capture",
            capture=capture(pages=[page], metadata_status="unavailable"), task_context="synthetic",
        )
        registration = json.loads(self.registration.read_text(encoding="utf-8"))
        registration["pages"][PAGE] = "0" * 64
        self.registration.write_text(json.dumps(registration), encoding="utf-8")
        failed_documentation = record_documentation_query(
            self.project, task_id="source-doc-failed", question="Check unavailable page",
            registration=self.registration, page=PAGE, command="zone list",
            product="flac3d", product_version="9.6",
        )
        refs = [failed_literature["task_packet"]["asset_refs"][0],
                failed_documentation["task_packet"]["asset_refs"][0]]
        started = start_source_review(
            self.project, task_id="failed-review", question="What is supported by the saved records?",
            asset_refs=refs, task_context="synthetic",
        )
        selected = started["task_packet"]["evidence_refs"]
        note = ("## Summary\nThe selected records do not support a substantive finding.\n\n"
                "## Findings\n\n## Gaps\n- Query and capture scope are limited.\n\n"
                "## Next\nInspect broader source material if the user chooses.\n")
        result = record_source_review(self.project, task_id="failed-review", operation_id="record-2",
                                      note=note, judgment_status="INSUFFICIENT")
        decision = ResearchStore(self.project).latest_record(result["review_record_ref"], "Decision")
        gaps = " ".join(decision["judgment"]["gaps"])
        self.assertIn("no successfully captured page content", gaps)
        self.assertIn("documentation query was unverified or failed", gaps)
        self.assertIn("coverage_scope=none", gaps)
        self.assertIn("command='zone list'", gaps)
        self.assertEqual("INSUFFICIENT", decision["judgment"]["status"])

    def test_discovery_only_is_preserved_but_not_citable_as_read_text(self):
        store = ResearchStore(self.project)
        docs_id = self.refs()[1]
        original = store.latest_record(docs_id, "Asset")
        changed = copy.deepcopy(original)
        changed["revision"] += 1
        result = changed["payload"]["documentation_result"]
        uncovered = ["official_source_identity_unverified", "mcp_version_unverified",
                     "reference_version_applicability_unverified"]
        result.update(status="DISCOVERY_ONLY", coverage_scope="discovery_only", uncovered=uncovered,
                      passages=[{"text": "Saved bounded discovery result", "locator": "zone list"}])
        changed["content_sha256"] = _sha256_json(changed["payload"])
        store.commit("discovery-only-doc-revision", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={docs_id: original["revision"]})
        started = start_source_review(self.project, task_id="discovery-review",
                                      question="What can these saved observations support?",
                                      asset_refs=self.refs(), task_context="synthetic")
        docs_source = next(item for item in started["sources"] if item["asset_ref"] == docs_id)
        self.assertEqual("DISCOVERY_ONLY", docs_source["query_result"]["status"])
        self.assertEqual("Saved bounded discovery result", docs_source["saved_passages"][0]["text"])
        note_with_discovery_claim = (
            "## Summary\nA discovery result is available.\n\n## Findings\n"
            f"- The passage establishes the claim. [evidence:{docs_source['evidence_refs'][0]}]\n\n"
            "## Gaps\n- Discovery is not passage reading.\n\n## Next\nThe user chooses whether to read further.\n")
        with self.assertRaisesRegex(ValueError, "unknown or unselected Evidence"):
            record_source_review(self.project, task_id="discovery-review", operation_id="discovery-citation",
                                 note=note_with_discovery_claim)
        note_without_claim = (
            "## Summary\nThe saved records are insufficient for a supported comparison.\n\n"
            "## Findings\n\n## Gaps\n- Discovery does not establish passage content.\n\n"
            "## Next\nThe user chooses whether to read a specific source passage.\n")
        recorded = record_source_review(self.project, task_id="discovery-review", operation_id="discovery-gaps",
                                        note=note_without_claim, judgment_status="INSUFFICIENT")
        decision = ResearchStore(self.project).latest_record(recorded["review_record_ref"], "Decision")
        self.assertEqual("READ_INSUFFICIENT", next(row for row in decision["assessment"]["material_reads"]
                                                     if row["asset_id"] == docs_id)["reading_status"])
        self.assertTrue(set(uncovered).issubset(set(decision["judgment"]["gaps"])))
        self.assertFalse(any("query was unverified or failed" in gap for gap in decision["judgment"]["gaps"]))


if __name__ == "__main__":
    unittest.main()
