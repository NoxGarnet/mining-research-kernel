from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import _record, task_inspect, task_start
from mining_research_kernel.zotero_records import record_zotero_reading
from research_project import enable_research
import jsonschema


REPO = Path(__file__).resolve().parents[1]


def capture(*, pages=None, metadata_status="read", origin="synthetic"):
    if pages is None:
        text = "The observed result is limited to this captured page."
        pages = [{
            "attachment_key": "ATTACH01", "attachment_version": None,
            "start_page": 12, "end_page": 13, "status": "read",
            "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "excerpt": text,
        }]
    return {
        "schema_version": 1,
        "kind": "zotero_reading_capture",
        "origin": origin,
        "instance_id": "0123456789abcdef0123456789abcdef",
        "library_id": "users/12345",
        "captured_at": "2026-10-17T01:02:03Z",
        "item": {"key": "PAPER001", "version": None, "title": "Example paper",
                 "item_type": "journalArticle", "doi": None},
        "collection_key": None,
        "metadata_status": metadata_status,
        "pages": pages,
        "diagnostics": [],
    }


class ZoteroRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zotero-records-", dir=REPO / "tests")
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        enable_research(self.project, "zotero.records.project")

    def tearDown(self):
        self.temp.cleanup()

    def record(self, task_id="reading-1", **kwargs):
        values = {
            "task_id": task_id,
            "question": "What does the selected page report?",
            "capture": capture(),
            "task_context": "synthetic",
        }
        values.update(kwargs)
        return record_zotero_reading(self.project, **values)

    def test_metadata_only_does_not_claim_pdf_reading(self):
        result = self.record(capture=capture(pages=[], metadata_status="read"))
        self.assertEqual("METADATA_ONLY", result["capture_summary"]["reading_status"])
        self.assertEqual("INSUFFICIENT", result["decision"]["judgment"]["status"])
        self.assertEqual("NOT_VERIFIED", result["task_packet"]["material_reads"][0]["verification_status"])
        self.assertEqual(0, result["capture_summary"]["read_page_range_count"])

    def test_synthetic_capture_is_rejected_in_production_context(self):
        with self.assertRaisesRegex(ValueError, "require synthetic task_context"):
            self.record(task_context="production")
        self.assertEqual([], ResearchStore(self.project).list_transactions())

    def test_external_capture_is_recorded_without_requery_or_revalidation(self):
        result = self.record(capture=capture(origin="external_mcp"), task_context="production")
        self.assertFalse(result["query_performed"])
        asset = ResearchStore(self.project).latest_record(result["task_packet"]["asset_refs"][0], "Asset")
        provenance = asset["payload"]["provenance"]
        self.assertTrue(provenance["capture_supplied_by_caller"])
        self.assertFalse(provenance["source_revalidated"])
        self.assertTrue(provenance["uncertain_version_fields"])

    def test_page_bounded_findings_allow_contained_ranges_only(self):
        finding = {"statement": "A bounded observation.", "citation": {
            "attachment_key": "ATTACH01", "start_page": 13, "end_page": 13,
        }}
        result = self.record(findings=[finding])
        recorded = result["decision"]["assessment"]["findings"][0]
        self.assertEqual("agent_interpretation_unverified", recorded["interpretation_status"])
        self.assertFalse(any(edge["relation"] == "evidence_supports_claim"
                             for edge in result["transaction"]["relationships"]))
        bad = copy.deepcopy(finding)
        bad["citation"]["start_page"] = 11
        with self.assertRaisesRegex(ValueError, "not covered by a read capture page"):
            self.record("reading-bad-citation", findings=[bad])
        with self.assertRaisesRegex(ValueError, "not covered by a read capture page"):
            self.record("reading-other-attachment", findings=[{
                "statement": "Metadata alone cannot cite a page.",
                "citation": {"attachment_key": "OTHER001", "start_page": 1, "end_page": 1},
            }])

    def test_unavailable_observations_are_preserved_as_gaps(self):
        page = {"attachment_key": "ATTACH01", "attachment_version": 0,
                "start_page": 1, "end_page": 1, "status": "unavailable",
                "text_sha256": None, "excerpt": ""}
        result = self.record(capture=capture(pages=[page], metadata_status="unavailable"))
        self.assertEqual("NO_READABLE_CONTENT", result["capture_summary"]["reading_status"])
        self.assertEqual("INSUFFICIENT", result["decision"]["judgment"]["status"])
        self.assertEqual(1, result["capture_summary"]["unavailable_page_range_count"])
        self.assertTrue(result["task_packet"]["material_gaps"])

    def test_identical_replay_and_conflicting_request(self):
        original = self.record()
        replay = self.record()
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["query_performed"])
        self.assertEqual(original["decision_id"], replay["decision_id"])
        with self.assertRaisesRegex(ValueError, "different Zotero reading request"):
            self.record(question="A different question")
        with self.assertRaisesRegex(ValueError, "different Zotero reading request"):
            self.record(findings=[{"statement": "An added interpretation", "citation": {
                "attachment_key": "ATTACH01", "start_page": 12, "end_page": 12}}])
        changed_capture = capture()
        changed_capture["item"]["version"] = 2
        with self.assertRaisesRegex(ValueError, "different Zotero reading request"):
            self.record(capture=changed_capture)
        self.assertEqual(1, len(ResearchStore(self.project).list_transactions()))

    def test_fresh_store_recovers_question_capture_and_decision(self):
        result = self.record()
        packet = task_inspect(self.project, "reading-1")
        self.assertEqual("What does the selected page report?", packet["input"]["question"])
        self.assertEqual("PAPER001", packet["input"]["source_observation"]["item_key"])
        jsonschema.Draft202012Validator(json.loads(
            (REPO / "schemas/task_packet.schema.json").read_text(encoding="utf-8"))).validate(packet)
        reloaded = ResearchStore(self.project)
        self.assertEqual(result["decision_id"], reloaded.latest_record("reading-1", "TaskState")["packet"]["review_record_ref"])

    def test_followup_linkage_blocks_a_tampered_embedded_capture(self):
        result = self.record()
        store = ResearchStore(self.project)
        asset = store.latest_record(result["task_packet"]["asset_refs"][0], "Asset")
        changed = copy.deepcopy(asset)
        changed["revision"] += 1
        changed["payload"]["request"]["question"] = "tampered"
        store.commit("tamper-reading-asset", {"role": "test", "model": "fixture"}, [changed], [])
        packet = task_start(self.project, {
            "task_id": "reading-followup",
            "workflow_id": "research",
            "task_type": "mining_research_kernel.task.evidence_review",
            "question_statement": "Review the earlier observation.",
            "claim_statement": "A new review claim.",
            "asset_refs": result["task_packet"]["asset_refs"],
            "evidence_refs": result["task_packet"]["evidence_refs"],
        })
        self.assertEqual("blocked", packet["state"])
        self.assertEqual("material_content_changed", packet["stop_reason"])

    def test_concurrent_identical_requests_commit_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.record("same-reading"), range(2)))
        self.assertEqual(1, sum(not item["replayed"] for item in results))
        self.assertEqual(1, len(ResearchStore(self.project).list_transactions()))


if __name__ == "__main__":
    unittest.main()
