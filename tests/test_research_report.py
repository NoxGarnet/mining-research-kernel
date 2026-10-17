from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mining_research_kernel.literature_comparison import start_literature_comparison, record_literature_comparison
from mining_research_kernel.documentation_records import record_documentation_query
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.research_report import (
    _render_bound_sources, _render_comparison, _source_decision_ancestor, _text,
    render_research_report,
)
from mining_research_kernel.r2_workflow import task_record_judgment_update
from mining_research_kernel.r2_workflow import _sha256_json
from mining_research_kernel.research_continuation import continue_research
from mining_research_kernel.source_review import start_source_review, record_source_review
from mining_research_kernel.zotero_records import record_zotero_reading
from research_project import enable_research
from tests.test_zotero_records import capture
from tests.test_r1_documentation import ANCHOR, PAGE, html_page


REPO = Path(__file__).resolve().parents[1]


class ResearchReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="research-report-", dir=REPO / "tests")
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        enable_research(self.root, "research.report.project")
        self.assets = []
        for n in (1, 2):
            item = capture()
            item["item"].update(key=f"RPT0000{n}", title=f"Report source {n}", version=n)
            item["pages"][0].update(attachment_key=f"ATT{n:05}", start_page=4, end_page=5)
            result = record_zotero_reading(self.root, task_id=f"paper-{n}", question="Read pages",
                                           capture=item, task_context="synthetic")
            self.assets.append(result["task_packet"]["asset_refs"][0])

    def tearDown(self):
        self.temp.cleanup()

    def _comparison_value(self, packet, asset_refs, summary="Saved observations differ within the captured pages."):
        store = ResearchStore(self.root)
        rows = []
        for aid in asset_refs:
            eid = next(ref for ref in packet["evidence_refs"]
                       if store.latest_record(ref, "Evidence")["asset_ref"] == aid)
            rows.append({"asset_ref": aid, "dimensions": {
                "methods": {"status": "not_reported_in_read_scope", "value": None,
                             "interpretation": "Methods are outside captured pages.", "citations": []},
                "results": {"status": "reported", "value": f"Observed {aid}",
                            "interpretation": "Limited <script>alert(1)</script> `fence` | row",
                            "citations": [{"evidence_id": eid, "attachment_key": f"ATT{asset_refs.index(aid)+1:05}",
                                           "page_range": {"start_page": 4, "end_page": 5}}]},
            }})
        comp = {"schema_version": 1, "question": "Compare reported methods and outcomes",
                "summary": summary,
                "summary_cells": [{"asset_ref": a, "dimension": "results"} for a in asset_refs],
                "next": "User may choose to read further.", "sources": rows,
                "differences": [{"dimension": "results", "explanation": "Recorded result descriptions differ.",
                                 "transferability": "Transferability remains unresolved.",
                                 "compared_cells": [{"asset_ref": a, "dimension": "results"} for a in asset_refs]}],
                "limitations": ["Only pages 4–5 are captured."]}
        return comp

    def _comparison(self, task_id="report-task"):
        started = start_literature_comparison(self.root, task_id=task_id,
            question="Compare reported methods and outcomes", asset_refs=self.assets,
            dimensions=["methods", "results"], task_context="synthetic")
        comp = self._comparison_value(started["task_packet"], self.assets)
        saved = record_literature_comparison(self.root, task_id=task_id, operation_id="report-op", comparison=comp)
        return saved["review_record_ref"]

    def test_report_is_stable_read_only_and_uses_saved_citations_and_scope(self):
        self._comparison()
        before = ResearchStore(self.root).list_transactions()
        first = render_research_report(self.root, task_id="report-task")
        second = render_research_report(self.root, task_id="report-task")
        self.assertEqual(first, second)
        self.assertEqual(before, ResearchStore(self.root).list_transactions())
        self.assertIn("ATT00001 pp. 4–5", first)
        self.assertIn("当前阅读范围未报告", first)
        self.assertIn("capture 1", first)
        self.assertIn("| 来源 | 维度 | 状态、观察与解释 | 引文 |", first)
        self.assertEqual(1, first.count("Report source 1"))
        self.assertEqual(1, first.count("Compare reported methods and outcomes"))
        self.assertEqual(1, first.count("Saved observations differ within the captured pages."))
        self.assertIn("&#124;", first)
        self.assertIn("&lt;script&gt;", first)
        self.assertNotIn("<script>", first)
        self.assertIn("未重新读取来源", first)
        self.assertNotIn(str(self.root), first)
        self.assertNotIn("E:/private", _text("E:/private/material.pdf"))
        self.assertIn("https://example.test/source", _text("https://example.test/source"))

    def test_report_without_decision_shows_pending_question_and_bound_sources(self):
        started = start_literature_comparison(self.root, task_id="pending-report",
            question="Compare the selected papers", asset_refs=self.assets,
            dimensions=["results"], task_context="synthetic")
        report = render_research_report(self.root, task_id="pending-report")
        self.assertIn("尚未形成新判断", report)
        self.assertIn("Compare the selected papers", report)
        self.assertIn(self.assets[0], report)
        self.assertNotIn("Decision：", report)

    def test_documentation_source_keeps_build_trust_and_locator(self):
        docs = Path(self.temp.name) / "docs"
        page_path = docs / Path(*PAGE.split("/"))
        page_path.parent.mkdir(parents=True)
        page_path.write_bytes(html_page())
        registration = Path(self.temp.name) / "registration.json"
        registration.write_text(json.dumps({
            "schema_version": 1, "source_id": "synthetic.official.docs", "root": str(docs),
            "product": "flac3d", "document_family": "9.6", "document_build": "9.6.44",
            "trust_class": "official_local", "product_subdir": "flac3d",
            "pages": {PAGE: hashlib.sha256(page_path.read_bytes()).hexdigest()},
        }), encoding="utf-8")
        doc_result = record_documentation_query(self.root, task_id="official-doc-query",
            question="Check the saved command reference", registration=registration,
            page=PAGE, command="zone list", product="flac3d", product_version="9.6",
            task_context="production")
        doc_asset = doc_result["task_packet"]["asset_refs"][0]
        started = start_source_review(self.root, task_id="docs-comparison",
            question="Compare papers with the official command reference", asset_refs=[*self.assets, doc_asset],
            task_context="synthetic")
        store = ResearchStore(self.root)
        paper_evidence = next(ref for ref in started["task_packet"]["evidence_refs"]
                              if store.latest_record(ref, "Evidence")["asset_ref"] == self.assets[0])
        note = ("## Summary\nThe saved paper and documentation query have bounded scopes.\n\n"
                f"## Findings\n- The saved paper evidence is available for its captured pages. [evidence:{paper_evidence}]\n\n"
                "## Gaps\n- The official documentation query covers only its recorded scope.\n\n"
                "## Next\nChoose whether to read more source material.\n")
        record_source_review(self.root, task_id="docs-comparison", operation_id="docs-report-op", note=note)
        report = render_research_report(self.root, task_id="docs-comparison")
        self.assertIn("9.6.44", report)
        self.assertIn("official&#95;local", report)
        self.assertIn(ANCHOR, report)
        self.assertIn(PAGE.replace("_", "&#95;"), report)

    def test_community_mcp_version_gap_and_locator_are_visible_in_comparison(self):
        aid, eid, locator = "community.asset", "community.evidence", "Zone List section"
        asset = {"id": aid, "asset_kind": "documentation_query_snapshot", "payload": {
            "request": {}, "documentation_result": {"citation": {
                "source_id": "community.manual", "document_family": None, "document_build": None,
                "trust_class": "community_mcp", "page": "zone.html", "anchor": locator},
                "passages": [{"locator": locator}], "uncovered": []}}}
        comparison = {"question": "Check the recorded community passage", "summary": "A bounded passage is saved.",
            "sources": [{"asset_ref": aid, "dimensions": {"syntax": {"status": "reported", "value": "Observed",
                "interpretation": "Saved passage only.", "citations": [{"evidence_id": eid, "locator": locator}]}}}],
            "differences": [], "limitations": []}
        bindings = {aid: {"evidence_refs": [eid], "evidence_revisions": {eid: 1}}}
        lines = []
        _render_comparison(lines, comparison, {aid: asset}, {eid: {"id": eid}}, bindings)
        rendered = "\n".join(lines)
        provenance = []
        _render_bound_sources(provenance, {"source_bindings": [{"asset_ref": aid, "revision": 1,
            "evidence_refs": [eid], "evidence_revisions": {eid: 1}}]},
            {aid: asset}, {eid: {"id": eid}})
        rendered += "\n" + "\n".join(provenance)
        self.assertIn("community&#95;mcp", rendered)
        self.assertIn("社区 MCP 返回未给出版本", rendered)
        self.assertIn(locator, rendered)

    def test_corrupt_or_unbound_historical_pins_never_fall_back_to_latest(self):
        self._comparison("pin-report")
        original = ResearchStore(self.root).list_transactions()
        damaged = copy.deepcopy(original)
        target = next(record for transaction in damaged for record in transaction["records"]
                      if record["type"] == "Asset" and record["id"] == self.assets[0])
        target["payload"]["request"]["capture"]["item"]["title"] = "tampered historical title"
        with patch.object(ResearchStore, "list_transactions", return_value=damaged):
            with self.assertRaisesRegex(ValueError, "payload hash is corrupt"):
                render_research_report(self.root, task_id="pin-report")

        unbound = copy.deepcopy(original)
        decision = next(record for transaction in unbound for record in transaction["records"]
                        if record["type"] == "Decision" and "literature_comparison" in record.get("assessment", {}))
        decision["assessment"]["source_bindings"] = [b for b in decision["assessment"]["source_bindings"]
                                                       if b["asset_ref"] != self.assets[0]]
        with patch.object(ResearchStore, "list_transactions", return_value=unbound):
            with self.assertRaisesRegex(ValueError, "no saved historical binding"):
                render_research_report(self.root, task_id="pin-report")

        store = ResearchStore(self.root)
        old = store.latest_record(self.assets[0], "Asset")
        changed = copy.deepcopy(old)
        changed["revision"] += 1
        changed["payload"]["request"]["capture"]["item"]["title"] = "newer unbound Asset revision"
        changed["content_sha256"] = _sha256_json(changed["payload"])
        store.commit("newer-unbound-asset", {"role": "test", "model": "fixture"}, [changed],
                     expected_revisions={self.assets[0]: old["revision"]})
        report = render_research_report(self.root, task_id="pin-report")
        self.assertIn("Report source 1", report)
        self.assertNotIn("newer unbound Asset revision", report)

        corrupt_evidence = copy.deepcopy(ResearchStore(self.root).list_transactions())
        evidence_record = next(record for transaction in corrupt_evidence for record in transaction["records"]
                               if record["type"] == "Evidence" and record["asset_ref"] == self.assets[0])
        evidence_record["asset_ref"] = self.assets[1]
        with patch.object(ResearchStore, "list_transactions", return_value=corrupt_evidence):
            with self.assertRaisesRegex(ValueError, "does not bind to saved Asset"):
                render_research_report(self.root, task_id="pin-report")

    def test_incremental_inheritance_cycle_fails_explicitly(self):
        decision = {"id": "decision_cycle", "revision": 1, "type": "Decision",
                    "assessment": {}, "judgment": {"inherited_from": {
                        "decision_id": "decision_cycle", "revision": 1}}}
        with self.assertRaisesRegex(ValueError, "inheritance contains a cycle"):
            _source_decision_ancestor(decision, {("decision_cycle", 1): decision})

    def test_incremental_decision_and_pending_task_keep_completed_base_judgment(self):
        decision_id = self._comparison()
        decision = ResearchStore(self.root).latest_record(decision_id, "Decision")
        store = ResearchStore(self.root)
        packet = store.latest_record("report-task", "TaskState")["packet"]
        evidence_id = packet["evidence_refs"][0]
        task_record_judgment_update(self.root, "report-task", "report-delta", {
            "base_decision_id": decision_id, "base_revision": decision["revision"],
            "change_kind": "supplement", "status": "PROVISIONAL_WITH_GAPS",
            "statement": "A bounded incremental observation was added.",
            "supported_evidence": [evidence_id], "gaps": ["Scientific validation remains open."],
            "next_action": {"action": "User may choose another reading step.", "executable": False},
            "changed_fields": ["summary", "supported_evidence", "gaps", "next_action"],
        })
        report = render_research_report(self.root, task_id="report-task")
        self.assertIn("A bounded incremental observation was added.", report)
        self.assertIn("User may choose another reading step.", report)
        self.assertIn("继承的已完成判断", report)
        self.assertIn(decision_id, report)
        self.assertIn("ATT00001", report)

        first_delta = store.latest_record("report-task", "TaskState")["packet"]["review_record_ref"]
        first_delta_record = store.latest_record(first_delta, "Decision")
        task_record_judgment_update(self.root, "report-task", "report-delta-two", {
            "base_decision_id": first_delta, "base_revision": first_delta_record["revision"],
            "change_kind": "supplement", "status": "PROVISIONAL_WITH_GAPS",
            "statement": "A second bounded update narrows the next reading step.",
            "supported_evidence": [packet["evidence_refs"][1]],
            "gaps": ["Independent validation remains open."],
            "next_action": {"action": "Next, read the specified method pages.", "executable": False},
            "changed_fields": ["summary", "supported_evidence", "gaps", "next_action"],
        })
        continue_research(self.root, task_id="after_two_deltas", from_task_id="report-task",
                          reason="Continue after two bounded judgment updates.")
        continued_report = render_research_report(self.root, task_id="after_two_deltas")
        self.assertIn("ATT00001", continued_report)
        self.assertIn("A second bounded update narrows the next reading step.", continued_report)
        self.assertIn("Next, read the specified method pages.", continued_report)
        self.assertIn("继承的来源比较", continued_report)

    def test_pending_continuation_shows_bound_prior_judgment_and_lineage(self):
        self._comparison("first-report-task")
        continued = continue_research(self.root, task_id="second_report_task",
                                      from_task_id="first-report-task", reason="Add a second reading step.")
        report = render_research_report(self.root, task_id="second_report_task")
        self.assertIn("尚未形成新判断", report)
        self.assertIn("已完成并按版本绑定的历史判断", report)
        self.assertIn("研究过程与变化", report)
        self.assertIn("Add a second reading step.", report)
        self.assertIn("`second_report_task`", report)
        self.assertEqual(continued["question_id"], ResearchStore(self.root).latest_record(
            "second_report_task", "TaskState")["packet"]["input"]["research_question_id"])

    def test_continuation_reports_same_paper_when_new_reading_creates_new_asset(self):
        self._comparison("first-version-task")
        store = ResearchStore(self.root)
        old_b = store.latest_record(self.assets[1], "Asset")
        reread = copy.deepcopy(old_b["payload"]["request"]["capture"])
        reread["pages"][0].update(start_page=4, end_page=7)
        new_b = record_zotero_reading(self.root, task_id="paper-b-method-reread",
            question="Read additional pages for the same paper", capture=reread,
            task_context="synthetic")["task_packet"]["asset_refs"][0]
        continuing_assets = [self.assets[0], new_b]
        continued = continue_research(self.root, task_id="second-version-task",
                                      from_task_id="first-version-task", asset_refs=continuing_assets,
                                      reason="Read paper B method pages and compare the expanded coverage.")
        comp = self._comparison_value(continued["task_packet"], continuing_assets,
                                      "The additional saved pages expand paper B coverage.")
        record_literature_comparison(self.root, task_id="second-version-task",
                                     operation_id="record-second-version", comparison=comp)
        report = render_research_report(self.root, task_id="second-version-task")
        self.assertIn("文献身份保持", report)
        self.assertIn("覆盖从", report)
        self.assertIn("4, 7", report)
        self.assertIn("The additional saved pages expand paper B coverage.", report)


if __name__ == "__main__":
    unittest.main()
