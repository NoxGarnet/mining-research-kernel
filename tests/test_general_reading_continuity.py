from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mining_research_kernel.literature_comparison import (
    record_literature_comparison, start_literature_comparison,
)
from mining_research_kernel.reading_observation import record_reading_observation
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.research_continuation import continue_research, begin_research
from mining_research_kernel.research_report import render_research_report
from mining_research_kernel.r2_workflow import _sha256_json
from mining_research_kernel.source_review import start_source_review, record_source_review
from mining_research_kernel import source_review as source_review_module
from research_project import enable_research
from mining_research_kernel.zotero_records import record_zotero_reading
from tests.test_zotero_records import capture


REPO = Path(__file__).resolve().parents[1]


def observation(source_id="paper-a", doi="10.1234/example.a", *, origin="agent_supplied", passages=None):
    return {
        "schema_version": 1, "kind": "reading_observation", "origin": origin,
        "captured_at": "2026-10-19T02:00:00Z",
        "source": {"source_id": source_id, "title": f"Title {source_id}", "doi": doi,
                   "url": None, "version": None, "source_kind": "local_pdf",
                   "source_sha256": None, "authority": "original_publication"},
        "reader": {"tool": "fixture reader", "method": "text"},
        "passages": passages or [
            {"locator": {"kind": "pdf_pages", "value": "pages 2-3", "start_page": 2, "end_page": 3},
             "status": "read", "text_sha256": None, "excerpt": "Observed result excerpt.",
             "limitations": ["Only selected pages were read."]},
            {"locator": {"kind": "section", "value": "Appendix B"}, "status": "unavailable",
             "text_sha256": None, "excerpt": "", "limitations": ["Appendix unavailable."]},
        ],
        "limitations": ["Caller supplied reading; source not independently checked."],
    }


class GeneralReadingContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="general-reading-", dir=REPO / "tests")
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        enable_research(self.project, "general.reading.project")
        self.assets, self.evidence = [], []
        for n in (1, 2):
            result = record_reading_observation(
                self.project, observation_id=f"obs-{n}",
                observation=observation(f"paper-{n}", f"10.1234/example.{n}"),
            )
            self.assets.append(result["asset_ref"])
            self.evidence.append(result["evidence_ref"])

    def tearDown(self):
        self.temp.cleanup()

    def test_two_rounds_keep_question_and_parent_decision(self):
        started = begin_research(self.project, task_id="reading-round-1",
                                 question="Compare the reported outcomes", asset_refs=self.assets,
                                 dimensions=["results"])
        store = ResearchStore(self.project)
        rows = []
        for aid, eid in zip(self.assets, self.evidence):
            rows.append({"asset_ref": aid, "dimensions": {"results": {
                "status": "reported", "value": "Observed outcome", "interpretation": "As stated in captured passage.",
                "citations": [{"evidence_id": eid, "locator": "pages 2-3"}]}}})
        comparison = {"schema_version": 1, "question": "Compare the reported outcomes",
                      "summary": "Both observations report outcomes within the captured scope.",
                      "summary_cells": [{"asset_ref": x, "dimension": "results"} for x in self.assets],
                      "next": "The user can choose another reading step.", "sources": rows,
                      "differences": [], "limitations": ["Version and original source hashes are unknown."]}
        record_literature_comparison(self.project, task_id="reading-round-1", operation_id="compare-1",
                                     comparison=comparison)
        next_step = continue_research(self.project, task_id="reading-round-2", from_task_id="reading-round-1")
        self.assertEqual(started["question_id"], next_step["question_id"])
        packet = next_step["task_packet"]
        continuation = packet["input"]["research_continuation"]
        self.assertEqual("reading-round-1", continuation["previous_task_id"])
        self.assertTrue(continuation["previous_decision_id"])
        decision = store.latest_record(continuation["previous_decision_id"], "Decision")
        self.assertEqual(continuation["previous_decision_revision"], decision["revision"])

    def test_unavailable_locator_and_external_evidence_cannot_be_cited(self):
        started = start_literature_comparison(self.project, task_id="locator-check",
                                              question="Compare outcomes", asset_refs=self.assets,
                                              dimensions=["results"])
        packet = started["task_packet"]
        rows = []
        for aid, eid in zip(self.assets, self.evidence):
            rows.append({"asset_ref": aid, "dimensions": {"results": {
                "status": "reported", "value": "Outcome", "interpretation": "Observed excerpt.",
                "citations": [{"evidence_id": eid, "locator": "pages 2-3"}]}}})
        base = {"schema_version": 1, "question": "Compare outcomes", "summary": "Bounded summary.",
                "summary_cells": [{"asset_ref": x, "dimension": "results"} for x in self.assets],
                "next": "Choose whether to read further.", "sources": rows, "differences": [],
                "limitations": ["Only captured passages are represented."]}
        bad = copy.deepcopy(base)
        bad["sources"][0]["dimensions"]["results"]["citations"][0]["locator"] = "Appendix B"
        with self.assertRaisesRegex(ValueError, "successful captured passage"):
            from mining_research_kernel.literature_comparison import _validate_comparison
            _validate_comparison(ResearchStore(self.project), packet, bad)
        bad = copy.deepcopy(base)
        bad["sources"][0]["dimensions"]["results"]["citations"][0]["evidence_id"] = "outside-evidence"
        with self.assertRaisesRegex(ValueError, "bound to the cited Asset"):
            from mining_research_kernel.literature_comparison import _validate_comparison
            _validate_comparison(ResearchStore(self.project), packet, bad)

    def test_doi_identity_and_payload_integrity_are_enforced(self):
        duplicate = record_reading_observation(
            self.project, observation_id="same-doi", observation=observation("different-source", "10.1234/example.1"))
        with self.assertRaisesRegex(ValueError, "distinct paper identities"):
            start_literature_comparison(self.project, task_id="doi-duplicate", question="Compare",
                                        asset_refs=[self.assets[0], duplicate["asset_ref"]], dimensions=["results"])
        store = ResearchStore(self.project)
        asset = store.latest_record(self.assets[0], "Asset")
        changed = copy.deepcopy(asset)
        changed["revision"] += 1
        changed["payload"]["request"]["observation"]["source"]["version"] = "2"
        changed["content_sha256"] = _sha256_json(changed["payload"])
        store.commit("tamper-reading", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={asset["id"]: asset["revision"]})
        with self.assertRaisesRegex(ValueError, "request hash mismatch"):
            start_literature_comparison(self.project, task_id="after-payload-change", question="Compare",
                                        asset_refs=[self.assets[0], self.assets[1]], dimensions=["results"])

    def test_source_id_alias_blocks_mixed_doi_presence_and_conflicts_are_explained(self):
        no_doi = record_reading_observation(
            self.project, observation_id="stable-no-doi", observation=observation("stable-paper", None))
        with_doi = record_reading_observation(
            self.project, observation_id="stable-with-doi",
            observation=observation("stable-paper", "10.1234/new-doi"))
        with self.assertRaisesRegex(ValueError, "distinct paper identities"):
            start_literature_comparison(self.project, task_id="stable-id-duplicate", question="Compare",
                                        asset_refs=[no_doi["asset_ref"], with_doi["asset_ref"]],
                                        dimensions=["results"])

        conflicting = record_reading_observation(
            self.project, observation_id="stable-conflicting-doi",
            observation=observation("stable-paper", "10.1234/other-doi"))
        with self.assertRaisesRegex(ValueError, "stable source_id.*different DOIs"):
            start_literature_comparison(self.project, task_id="stable-id-conflict", question="Compare",
                                        asset_refs=[with_doi["asset_ref"], conflicting["asset_ref"]],
                                        dimensions=["results"])

    def test_distinct_source_ids_and_dois_remain_independent_papers(self):
        result = start_literature_comparison(self.project, task_id="distinct-identities", question="Compare",
                                             asset_refs=self.assets, dimensions=["results"])
        self.assertEqual(self.assets, [item["asset_ref"] for item in result["sources"]])

    def test_doi_upgrade_keeps_report_source_and_pins_each_citation_revision(self):
        old_b = record_reading_observation(
            self.project, observation_id="stable-b-v1", observation=observation("stable-b", None))
        first_assets = [self.assets[0], old_b["asset_ref"]]
        first = begin_research(self.project, task_id="identity-round-1", question="Compare the reported outcomes",
                               asset_refs=first_assets, dimensions=["results"])

        def comparison(packet, asset_refs, summary):
            store = ResearchStore(self.project)
            rows = []
            for aid in asset_refs:
                evidence_id = next(ref for ref in packet["evidence_refs"]
                                   if store.latest_record(ref, "Evidence")["asset_ref"] == aid)
                rows.append({"asset_ref": aid, "dimensions": {"results": {
                    "status": "reported", "value": "Observed outcome", "interpretation": "Within saved scope.",
                    "citations": [{"evidence_id": evidence_id, "locator": "pages 2-3"}]}}})
            return {"schema_version": 1, "question": "Compare the reported outcomes", "summary": summary,
                    "summary_cells": [{"asset_ref": aid, "dimension": "results"} for aid in asset_refs],
                    "next": "The user may choose another reading step.", "sources": rows,
                    "differences": [], "limitations": ["Only saved passages are represented."]}

        record_literature_comparison(self.project, task_id="identity-round-1", operation_id="identity-review-1",
                                     comparison=comparison(first["task_packet"], first_assets, "First bounded reading."))
        previous_report = render_research_report(self.project, task_id="identity-round-1")
        new_b = record_reading_observation(
            self.project, observation_id="stable-b-v2",
            observation=observation("stable-b", "10.1234/stable-b"))
        next_assets = [self.assets[0], new_b["asset_ref"]]
        second = continue_research(self.project, task_id="identity-round-2", from_task_id="identity-round-1",
                                   asset_refs=next_assets, reason="Add DOI metadata to the same stable source.")
        record_literature_comparison(self.project, task_id="identity-round-2", operation_id="identity-review-2",
                                     comparison=comparison(second["task_packet"], next_assets,
                                                           "The same source now has DOI metadata."))

        report = render_research_report(self.project, task_id="identity-round-2")
        self.assertIn("新增 无；移除 无", report)
        self.assertIn("paper:source:stable-b：Asset 更换", report)
        self.assertIn(old_b["evidence_ref"], report)
        self.assertIn(new_b["evidence_ref"], report)
        self.assertIn(new_b["evidence_ref"] + " r1", report)
        self.assertEqual(previous_report, render_research_report(self.project, task_id="identity-round-1"))

    def test_two_round_report_preserves_doi_primary_identity_label(self):
        question = "Compare the reported outcomes"

        def comparison(packet, asset_refs, summary):
            store = ResearchStore(self.project)
            rows = []
            for aid in asset_refs:
                evidence_id = next(ref for ref in packet["evidence_refs"]
                                   if store.latest_record(ref, "Evidence")["asset_ref"] == aid)
                rows.append({"asset_ref": aid, "dimensions": {"results": {
                    "status": "reported", "value": "Observed outcome", "interpretation": "Within saved scope.",
                    "citations": [{"evidence_id": evidence_id, "locator": "pages 2-3"}]}}})
            return {"schema_version": 1, "question": question, "summary": summary,
                    "summary_cells": [{"asset_ref": aid, "dimension": "results"} for aid in asset_refs],
                    "next": "The user may choose another reading step.", "sources": rows,
                    "differences": [], "limitations": ["Only saved passages are represented."]}

        first_assets = list(self.assets)
        first = begin_research(self.project, task_id="doi-label-round-1", question=question,
                               asset_refs=first_assets, dimensions=["results"])
        record_literature_comparison(self.project, task_id="doi-label-round-1", operation_id="doi-label-review-1",
                                     comparison=comparison(first["task_packet"], first_assets, "First saved reading."))

        reread_a = record_reading_observation(
            self.project, observation_id="paper-a-doi-reread",
            observation=observation("paper-1", "10.1234/example.1"))
        next_assets = [reread_a["asset_ref"], self.assets[1]]
        second = continue_research(self.project, task_id="doi-label-round-2", from_task_id="doi-label-round-1",
                                   asset_refs=next_assets, reason="Reread paper A within the same DOI identity.")
        record_literature_comparison(self.project, task_id="doi-label-round-2", operation_id="doi-label-review-2",
                                     comparison=comparison(second["task_packet"], next_assets,
                                                           "Paper A has expanded saved coverage."))

        report = render_research_report(self.project, task_id="doi-label-round-2")
        self.assertIn("paper:doi:10.1234/example.1：Asset 更换", report)
        self.assertIn("新增 无；移除 无", report)

    def test_duplicate_doi_between_zotero_and_general_observation_is_rejected(self):
        paper = capture()
        paper["item"]["doi"] = "10.1234/example.1"
        zotero_asset = record_zotero_reading(
            self.project, task_id="legacy-doi-paper", question="Capture a legacy Zotero paper",
            capture=paper, task_context="synthetic",
        )["task_packet"]["asset_refs"][0]
        with self.assertRaisesRegex(ValueError, "distinct paper identities"):
            start_literature_comparison(self.project, task_id="mixed-doi-duplicate",
                                        question="Compare the same paper twice",
                                        asset_refs=[self.assets[0], zotero_asset], dimensions=["results"],
                                        task_context="synthetic")

    def test_sources_mode_retains_failed_source_without_citation_privilege(self):
        failed = observation("failed-doc", "10.1234/failed", passages=[
            {"locator": {"kind": "section", "value": "Results"}, "status": "unavailable",
             "text_sha256": None, "excerpt": "", "limitations": ["Could not read this section."]}])
        record = record_reading_observation(self.project, observation_id="failed-only", observation=failed)
        started = start_source_review(self.project, task_id="sources-with-failure", question="Review selected reading",
                                      asset_refs=[record["asset_ref"]], review_mode="selected_sources")
        self.assertEqual(record["asset_ref"], started["sources"][0]["asset_ref"])
        self.assertEqual("READ_INSUFFICIENT", started["sources"][0]["reading_status"])
        with self.assertRaisesRegex(ValueError, "unknown or unselected Evidence"):
            record_source_review(self.project, task_id="sources-with-failure", operation_id="failed-cite",
                                 note=("## Summary\nNo support.\n\n## Findings\n- Failed source. [evidence:"
                                       + record["evidence_ref"] + "]\n\n## Gaps\n- Unavailable.\n\n## Next\nRead the source.\n"))

    def test_overview_exposes_reader_capture_time_and_source_location_hashes(self):
        value = observation("meta-paper", "10.1234/meta")
        value["captured_at"] = "2026-10-18T12:30:00Z"
        value["reader"] = {"tool": "local parser", "method": "mixed"}
        value["source"]["url"] = "https://example.org/paper"
        value["source"]["source_sha256"] = "a" * 64
        item = record_reading_observation(self.project, observation_id="meta-observation", observation=value)
        started = start_source_review(self.project, task_id="overview-metadata", question="Review source metadata",
                                      asset_refs=[item["asset_ref"]], review_mode="selected_sources")
        source = started["sources"][0]
        self.assertEqual(value["reader"], source["reader"])
        self.assertEqual(value["captured_at"], source["captured_at"])
        self.assertEqual(value["source"]["url"], source["identity"]["url"])
        self.assertEqual(value["source"]["source_sha256"], source["identity"]["source_sha256"])

    def test_source_start_uses_asset_and_evidence_revision_cas(self):
        store = ResearchStore(self.project)
        original_task_start = source_review_module.task_start

        def race_before_commit(root, request, *args, **kwargs):
            asset = store.latest_record(self.assets[0], "Asset")
            changed = copy.deepcopy(asset)
            changed["revision"] += 1
            changed["payload"]["request"]["observation"]["source"]["version"] = "2"
            changed["payload"]["provenance"]["request_sha256"] = _sha256_json(changed["payload"]["request"])
            changed["content_sha256"] = _sha256_json(changed["payload"])
            store.commit("source-start-race", {"role": "test", "model": "fixture"}, [changed],
                         expected_revisions={asset["id"]: asset["revision"]})
            return original_task_start(root, request, *args, **kwargs)

        with patch.object(source_review_module, "task_start", side_effect=race_before_commit):
            with self.assertRaisesRegex(ValueError, "record revision changed"):
                start_source_review(self.project, task_id="cas-source-start", question="Check source CAS",
                                    asset_refs=self.assets, review_mode="selected_sources")

    def test_synthetic_observation_requires_synthetic_context(self):
        from mining_research_kernel.reading_observation import validate_observation
        value = observation("synthetic-paper", "10.1234/synthetic", origin="synthetic")
        normalized = validate_observation(value)
        self.assertEqual("synthetic", normalized["origin"])
        with self.assertRaisesRegex(ValueError, "cannot be recorded in production"):
            record_reading_observation(self.project, observation_id="synthetic-prod", observation=value)


if __name__ == "__main__":
    unittest.main()
