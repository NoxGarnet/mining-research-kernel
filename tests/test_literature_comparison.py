from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from mining_research_kernel.literature_comparison import (
    _validate_comparison, record_literature_comparison, start_literature_comparison,
)
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.zotero_records import record_zotero_reading
from research_project import enable_research
from tests.test_zotero_records import capture


REPO = Path(__file__).resolve().parents[1]


class LiteratureComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="literature_comparison-", dir=REPO / "tests")
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        enable_research(self.project, "literature.comparison.project")
        self.assets = []
        self.read_attachments = {}
        for n in (1, 2):
            paper = capture()
            paper["item"]["key"] = f"PAPER00{n}"
            paper["item"]["title"] = f"Example paper {n}"
            read_page = paper["pages"][0]
            read_page.update(attachment_key=f"ATTACH0{n}", start_page=1, end_page=1)
            if n == 1:
                unavailable = copy.deepcopy(read_page)
                unavailable.update(attachment_key="ATTACH09", status="unavailable",
                                   text_sha256=None, excerpt="")
                paper["pages"].append(unavailable)
            self.read_attachments[f"PAPER00{n}"] = f"ATTACH0{n}"
            result = record_zotero_reading(
                self.project, task_id=f"paper-{n}", question="Read selected paper pages",
                capture=paper, task_context="synthetic",
            )
            self.assets.append(result["task_packet"]["asset_refs"][0])

    def tearDown(self):
        self.temp.cleanup()

    def start(self, task_id="lit-compare"):
        return start_literature_comparison(
            self.project, task_id=task_id,
            question="How do studies differ in their reported results?",
            asset_refs=self.assets, dimensions=["materials", "results"], task_context="synthetic",
        )

    def comparison(self, packet):
        store = ResearchStore(self.project)
        rows = []
        for aid in self.assets:
            evidence = next(item for item in packet["evidence_refs"]
                            if store.latest_record(item, "Evidence")["asset_ref"] == aid)
            rows.append({"asset_ref": aid, "dimensions": {
                "materials": {"status": "not_reported_in_read_scope", "value": None,
                              "interpretation": "Materials are not stated in the saved pages.", "citations": []},
                "results": {"status": "reported", "value": f"Finding from {aid}",
                            "interpretation": "A bounded interpretation of the captured page.",
                            "citations": [{"evidence_id": evidence,
                                           "attachment_key": self.read_attachments[
                                               store.latest_record(aid, "Asset")["payload"]["request"]["capture"]["item"]["key"]],
                                           "page_range": {"start_page": 1, "end_page": 1}}]},
            }})
        return {"schema_version": 1,
                "question": "How do studies differ in their reported results?",
                "summary": "The two saved passages give different result observations.",
                "summary_cells": [{"asset_ref": row["asset_ref"], "dimension": "results"}
                                  for row in rows],
                "next": "User chooses whether to read further or set the next goal.",
                "sources": rows,
                "differences": [{"dimension": "results", "explanation": "The saved interpretations differ.",
                                 "transferability": "Transfer remains provisional because conditions need comparison.",
                                 "compared_cells": [{"asset_ref": row["asset_ref"], "dimension": "results"}
                                                    for row in rows]}],
                "limitations": ["Only pages 12-13 were read for each paper.",
                                "Units and experimental conditions remain unverified gaps."]}

    def test_distinct_identity_and_replay(self):
        first = self.start()
        replay = self.start()
        self.assertTrue(replay["replayed"])
        self.assertEqual(first["task_packet"], replay["task_packet"])
        with self.assertRaisesRegex(ValueError, "unique list"):
            start_literature_comparison(self.project, task_id="duplicates", question="Compare captures",
                                        asset_refs=[self.assets[0], self.assets[0]],
                                        dimensions=["results"], task_context="synthetic")

    def test_record_checks_page_scope_binding_and_provisional_status(self):
        started = self.start()
        comparison = self.comparison(started["task_packet"])
        bad = copy.deepcopy(comparison)
        bad["sources"][0]["dimensions"]["results"]["citations"][0]["page_range"]["start_page"] = 9
        bad["sources"][0]["dimensions"]["results"]["citations"][0]["page_range"]["end_page"] = 9
        with self.assertRaisesRegex(ValueError, "outside actual saved read coverage"):
            record_literature_comparison(self.project, task_id="lit-compare", operation_id="bad-page",
                                         comparison=bad)
        bad = copy.deepcopy(comparison)
        bad["sources"][0]["dimensions"]["results"]["citations"][0]["evidence_id"] = \
            comparison["sources"][1]["dimensions"]["results"]["citations"][0]["evidence_id"]
        with self.assertRaisesRegex(ValueError, "bound to the cited Asset"):
            record_literature_comparison(self.project, task_id="lit-compare", operation_id="bad-binding",
                                         comparison=bad)
        bad = copy.deepcopy(comparison)
        bad["sources"][0]["dimensions"]["results"]["citations"][0]["attachment_key"] = "ATTACH09"
        with self.assertRaisesRegex(ValueError, "attachment and page range"):
            record_literature_comparison(self.project, task_id="lit-compare", operation_id="wrong-attachment",
                                         comparison=bad)
        bad = copy.deepcopy(comparison)
        bad["schema_version"] = True
        with self.assertRaisesRegex(ValueError, "schema_version"):
            record_literature_comparison(self.project, task_id="lit-compare", operation_id="bool-schema",
                                         comparison=bad)
        bad = copy.deepcopy(comparison)
        bad["sources"].append(copy.deepcopy(bad["sources"][0]))
        with self.assertRaisesRegex(ValueError, "exactly match"):
            record_literature_comparison(self.project, task_id="lit-compare", operation_id="duplicate-row",
                                         comparison=bad)
        bad = copy.deepcopy(comparison)
        bad["differences"][0]["compared_cells"] = [{"asset_ref": self.assets[0], "dimension": "results"}]
        with self.assertRaisesRegex(ValueError, "references to compared source cells"):
            record_literature_comparison(self.project, task_id="lit-compare", operation_id="unbound-difference",
                                         comparison=bad)
        recorded = record_literature_comparison(
            self.project, task_id="lit-compare", operation_id="record-compare", comparison=comparison,
        )
        decision = ResearchStore(self.project).latest_record(recorded["review_record_ref"], "Decision")
        self.assertEqual("PROVISIONAL_WITH_GAPS", decision["judgment"]["status"])
        self.assertEqual("NOT_PERFORMED", decision["assessment"]["semantic_claim_verification"])
        self.assertEqual(comparison["summary"], decision["judgment"]["summary"])
        self.assertEqual(comparison["next"], decision["judgment"]["next_action"]["action"])
        self.assertIn("not_reported_in_read_scope",
                      [cell["status"] for row in decision["assessment"]["literature_comparison"]["sources"]
                       for cell in row["dimensions"].values()])
        self.assertTrue(decision["judgment"]["next_action"]["requires_user_choice"])
        replay = record_literature_comparison(
            self.project, task_id="lit-compare", operation_id="record-compare", comparison=comparison,
        )
        self.assertEqual(recorded["review_record_ref"], replay["review_record_ref"])

    def test_source_revision_drift_after_start_is_rejected(self):
        self.start()
        store = ResearchStore(self.project)
        original = store.latest_record(self.assets[0], "Asset")
        changed = copy.deepcopy(original)
        changed["revision"] += 1
        changed["payload"]["request"]["capture"]["item"]["title"] += " revised"
        from mining_research_kernel.r2_workflow import _sha256_json
        changed["content_sha256"] = _sha256_json(changed["payload"])
        store.commit("paper-source-drift", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={self.assets[0]: original["revision"]})
        with self.assertRaisesRegex(ValueError, "source Asset revision or payload changed"):
            record_literature_comparison(
                self.project, task_id="lit-compare", operation_id="after-drift",
                comparison={"schema_version": 1},
            )

    def test_duplicate_paper_with_different_asset_is_rejected(self):
        duplicate = record_zotero_reading(
            self.project, task_id="paper-copy", question="Duplicate capture",
            capture=capture(), task_context="synthetic",
        )["task_packet"]["asset_refs"][0]
        with self.assertRaisesRegex(ValueError, "distinct paper identities"):
            start_literature_comparison(self.project, task_id="same-paper", question="Compare same paper",
                                        asset_refs=[self.assets[0], duplicate], dimensions=["results"],
                                        task_context="synthetic")

    def test_discovery_only_documentation_passage_cannot_support_cited_cell(self):
        asset = {"id": "docs-asset", "asset_kind": "documentation_query_snapshot", "payload": {
            "documentation_result": {"status": "DISCOVERY_ONLY", "coverage_scope": "discovery_only",
                                     "passages": [{"text": "Saved discovery text", "locator": "zone list"}]}}}

        class Store:
            def latest_record(self, record_id, record_type):
                return asset if record_id == "docs-asset" and record_type == "Asset" else None

        packet = {"input": {"review_question": "Compare documentation observations",
                            "source_bindings": [{"asset_ref": "docs-asset", "evidence_refs": ["docs-ev"]}],
                            "dimensions": ["results"]}}
        comparison = {"schema_version": 1, "question": packet["input"]["review_question"],
                      "summary": "A discovery observation is available.",
                      "summary_cells": [{"asset_ref": "docs-asset", "dimension": "results"}],
                      "next": "The user chooses whether to read an applicable passage.",
                      "sources": [{"asset_ref": "docs-asset", "dimensions": {"results": {
                          "status": "reported", "value": "Discovery text", "interpretation": "Observed in discovery output.",
                          "citations": [{"evidence_id": "docs-ev", "locator": "zone list"}]}}}],
                      "differences": [], "limitations": ["Discovery output is not passage reading."]}
        with self.assertRaisesRegex(ValueError, "readable saved result"):
            _validate_comparison(Store(), packet, comparison)


if __name__ == "__main__":
    unittest.main()
