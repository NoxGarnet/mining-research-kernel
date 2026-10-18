from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from mining_research_kernel.documentation_reading import record_documentation_reading
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.script_review import (
    record_script_review, render_script_review_report, script_review_progress, start_script_review,
)
from mining_research_kernel.script_review import _read_script
from providers.documentation import load_registration
from research_project import enable_research

REPO = Path(__file__).resolve().parents[1]
DOC_PAGE = "flac3d/zone/doc/manual/zone_commands/itasca_reading_fixture.html"
DOC_BYTES = (REPO / "tests/fixtures/itasca_manual.html").read_bytes()


class ScriptReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR"))
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        enable_research(self.project, "script.review.test")
        self.docs = self.base / "docs"
        self.doc_path = self.docs / DOC_PAGE
        self.doc_path.parent.mkdir(parents=True)
        self.doc_path.write_bytes(DOC_BYTES)
        self.registration = self.base / "registration.json"
        self._register()
        self.script = self.project / "model.dat"
        self.original = ("; intro\nzone cmodel assign elastic\nzone cmodel assign elastic range group 'rock mass'\n"
                         "fish define fake\n  zone cmodel assign elastic\nend\n")
        self.script.write_text(self.original, encoding="utf-8")
        doc = record_documentation_reading(
            self.project, task_id="doc-read", question="Read selected FLAC3D passage",
            registration=self.registration, provider="local", page=DOC_PAGE, product="flac3d",
            product_version="9.6", anchor="kwd:zone.cmodel.assign.elastic", task_context="synthetic")
        self.doc_asset = doc["task_packet"]["asset_refs"][0]

    def tearDown(self):
        self.temp.cleanup()

    def _register(self, trust="synthetic"):
        self.registration.write_text(json.dumps({
            "schema_version": 1, "source_id": "example.docs", "root": str(self.docs),
            "product": "flac3d", "document_family": "9.6", "document_build": "9.6.44",
            "trust_class": trust, "product_subdir": "flac3d",
            "pages": {DOC_PAGE: hashlib.sha256(self.doc_path.read_bytes()).hexdigest()},
        }), encoding="utf-8")

    def _start(self, **kw):
        args = dict(task_id="review", question="Review the selected assignment", script="model.dat",
                    start_line=1, end_line=6, product_version="9.6",
                    documentation_asset_refs=[self.doc_asset], task_context="synthetic")
        args.update(kw)
        return start_script_review(self.project, **args)

    def test_snapshot_line_binding_recovery_and_offline_report(self):
        result = self._start()
        snap = result["script_snapshot"]
        self.assertEqual("flac3d_script_review", result["task_packet"]["input"]["review_mode"])
        self.assertEqual([1, 2, 3, 4, 5, 6], [row["line"] for row in snap["lines"]])
        self.assertEqual("candidate", snap["lines"][1]["classification"])
        self.assertEqual("uncertain", snap["lines"][2]["classification"])
        self.assertEqual(self.original.splitlines()[1], snap["lines"][1]["text"])
        self.assertNotIn(str(self.project), json.dumps(ResearchStore(self.project).list_transactions()))
        self.script.write_text(self.original + "; changed after capture\n", encoding="utf-8")
        self.assertEqual("changed", script_review_progress(self.project, task_id="review", script="model.dat")["source_status"])
        self.script.unlink()
        progress = script_review_progress(self.project, task_id="review")
        self.assertEqual("not_checked", progress["source_status"])
        self.assertEqual(snap, progress["script_snapshot"])
        self.assertEqual("missing", script_review_progress(self.project, task_id="review", script="model.dat")["source_status"])
        self.assertTrue(self._start()["replayed"])
        report = render_script_review_report(self.project, task_id="review")
        self.assertIn("No fresh source query", report)
        self.assertEqual("missing", script_review_progress(self.project, task_id="review", script="model.dat")["source_status"])

    def test_selected_slice_inherits_fish_python_and_continuation_context(self):
        fish = self._start(task_id="fish-slice", start_line=5, end_line=5)
        self.assertEqual("uncertain", fish["script_snapshot"]["lines"][0]["classification"])
        py_script = self.project / "python.dat"
        py_script.write_text("python\nzone cmodel assign elastic\nend_python\n", encoding="utf-8")
        py = self._start(task_id="python-slice", script="python.dat", start_line=2, end_line=2)
        self.assertEqual("uncertain", py["script_snapshot"]["lines"][0]["classification"])
        continuation = self.project / "continuation.dat"
        continuation.write_text("zone cmodel assign elastic ...\nzone cmodel assign elastic\n; zone cmodel assign fake ...\nzone cmodel assign elastic\n", encoding="utf-8")
        result = self._start(task_id="continuation-slice", script="continuation.dat", start_line=2, end_line=4)
        self.assertEqual(["uncertain", "none", "candidate"], [x["classification"] for x in result["script_snapshot"]["lines"]])

    def test_review_validation_replay_and_no_run_or_verification(self):
        self._start()
        store = ResearchStore(self.project)
        state = store.latest_record("review", "TaskState")
        evidence = state["packet"]["input"]["script_review"]["documentation_sources"][0]["evidence"][0]["id"]
        bad = {"summary": "checked", "findings": [{"start_line": 4, "end_line": 4,
               "statement": "Looks valid", "documentation_evidence_refs": [evidence]}],
               "gaps": ["semantic behavior not established"], "next_action": "ask user"}
        with self.assertRaisesRegex(ValueError, "complete literal candidate"):
            record_script_review(self.project, task_id="review", operation_id="op", review=bad)
        review = {**bad, "findings": [{**bad["findings"][0], "start_line": 2, "end_line": 2}]}
        result = record_script_review(self.project, task_id="review", operation_id="op", review=review)
        self.assertTrue(result["requires_user_choice"])
        self.assertIn("semantic correctness", render_script_review_report(self.project, task_id="review"))
        self.assertEqual(review["summary"], script_review_progress(self.project, task_id="review")["decision"]["judgment"]["summary"])
        replay = record_script_review(self.project, task_id="review", operation_id="op", review=review)
        self.assertEqual(result["review_record_ref"], replay["review_record_ref"])
        records = [r for tx in ResearchStore(self.project).list_transactions() for r in tx["records"]]
        self.assertFalse(any(r["type"] in {"Run", "Verification"} for r in records))
        packet = result["task_packet"]
        self.assertIn(self.doc_asset, packet["asset_refs"])
        self.assertIn(evidence, packet["evidence_refs"])
        progress = script_review_progress(self.project, task_id="review")
        self.assertEqual(review, progress["review"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", progress["decision"]["judgment"]["status"])
        report = render_script_review_report(self.project, task_id="review")
        self.assertIn("Trust: synthetic", report)
        self.assertIn("Saved passage locator", report)
        for gap in progress["decision"]["judgment"]["gaps"]:
            self.assertIn(gap, report)

    def test_empty_findings_are_insufficient_and_references_are_bounded(self):
        notes = self.project / "notes.dat"
        notes.write_text("; no command in this selected range\n", encoding="utf-8")
        started = self._start(task_id="empty", script="notes.dat", start_line=1, end_line=1)
        self.assertFalse(any(row["classification"] == "candidate" for row in started["script_snapshot"]["lines"]))
        empty_review = {"summary": "No confirmed findings", "findings": [],
                        "gaps": ["No candidate command was established in the selected range"], "next_action": "user chooses another range"}
        result = record_script_review(self.project, task_id="empty", operation_id="empty-op", review=empty_review)
        self.assertEqual("INSUFFICIENT", script_review_progress(self.project, task_id="empty")["decision"]["judgment"]["status"])
        self._start(task_id="bad-citations")
        base = {"summary": "review", "findings": [{"start_line": 2, "end_line": 2, "statement": "finding",
                "documentation_evidence_refs": ["not-selected"]}], "gaps": ["gap"], "next_action": "user decides"}
        with self.assertRaisesRegex(ValueError, "Evidence IDs"):
            record_script_review(self.project, task_id="bad-citations", operation_id="bad1", review=base)
        for refs in ([], [" "], [None], ["x" * 500]):
            malformed = {**base, "findings": [{**base["findings"][0], "documentation_evidence_refs": refs}]}
            with self.assertRaises(ValueError):
                record_script_review(self.project, task_id="bad-citations", operation_id="bad2", review=malformed)
        malformed = {**base, "findings": [{**base["findings"][0], "documentation_evidence_refs": ["x"] * 101}]}
        with self.assertRaisesRegex(ValueError, "Evidence IDs"):
            record_script_review(self.project, task_id="bad-citations", operation_id="bad4", review=malformed)
        too_many = {**base, "findings": [{}] * 101}
        with self.assertRaisesRegex(ValueError, "at most"):
            record_script_review(self.project, task_id="bad-citations", operation_id="bad3", review=too_many)

    def test_docs_revision_change_rejects_record_but_preserves_historical_progress(self):
        self._start(task_id="stale-doc")
        store = ResearchStore(self.project)
        evidence = next(r for tx in store.list_transactions() for r in tx["records"]
                        if r["type"] == "Evidence" and r.get("asset_ref") == self.doc_asset)
        evidence = store.latest_record(evidence["id"], "Evidence")
        asset = store.latest_record(self.doc_asset, "Asset")
        old_edge = next(rel for tx in store.list_transactions() for rel in tx["relationships"]
                        if rel.get("from_id") == evidence["id"] and rel.get("relation") == "evidence_derived_from_asset")
        asset2 = {**asset, "revision": asset["revision"] + 1}
        evidence2 = {**evidence, "revision": evidence["revision"] + 1}
        edge2 = {**old_edge, "revision": old_edge["revision"] + 1,
                 "from_revision": evidence2["revision"], "to_revision": asset2["revision"]}
        store.commit("test-doc-revision", {"role": "test", "model": "test"}, [asset2, evidence2], [edge2])
        review = {"summary": "review", "findings": [{"start_line": 2, "end_line": 2, "statement": "finding",
                  "documentation_evidence_refs": [evidence["id"]]}], "gaps": ["gap"], "next_action": "user decides"}
        with self.assertRaisesRegex(ValueError, "changed since review start"):
            record_script_review(self.project, task_id="stale-doc", operation_id="stale-op", review=review)
        progress = script_review_progress(self.project, task_id="stale-doc")
        self.assertIsNone(progress["review"])
        self.assertEqual(asset["revision"], progress["documentation_sources"][0]["asset_revision"])

    def test_bounded_read_and_external_path_replay_identity(self):
        oversized = self.base / "oversized.dat"
        oversized.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        with self.assertRaisesRegex(ValueError, "2 MiB"):
            _read_script(oversized, "utf-8")
        bad_encoding = self.base / "bad-encoding.dat"
        bad_encoding.write_bytes(b"\xff")
        with self.assertRaisesRegex(ValueError, "decoded"):
            _read_script(bad_encoding, "utf-8")
        directory = self.base / "script-directory"
        directory.mkdir()
        with self.assertRaisesRegex(ValueError, "script path"):
            _read_script(directory, "utf-8")
        first = self.base / "first" / "same.dat"
        second = self.base / "second" / "same.dat"
        first.parent.mkdir(); second.parent.mkdir()
        first.write_text("zone cmodel assign elastic\n", encoding="utf-8")
        second.write_text("zone cmodel assign elastic\n", encoding="utf-8")
        self._start(task_id="outside", script=str(first), start_line=1, end_line=1)
        with self.assertRaisesRegex(ValueError, "different script review"):
            self._start(task_id="outside", script=str(second), start_line=1, end_line=1)

    def test_replay_conflict_bounds_and_documentation_gates(self):
        self._start()
        self.assertTrue(self._start()["replayed"])
        with self.assertRaisesRegex(ValueError, "different script review"):
            self._start(question="different")
        with self.assertRaises(ValueError):
            self._start(task_id="bool-line", start_line=True)
        with self.assertRaises(ValueError):
            self._start(task_id="too-many", end_line=202)
        with self.assertRaises(ValueError):
            self._start(task_id="wrong-version", product_version="9.5")
        with self.assertRaises(ValueError):
            self._start(task_id="production-synthetic", task_context="production")
        with self.assertRaises(ValueError):
            self._start(task_id="bad-ref", documentation_asset_refs=["missing.asset"])
        import mining_research_kernel.script_review as script_review_module
        actual = script_review_module._payload_record
        def discovery_payload(store, asset_id, evidence_ids):
            asset, evidences, payload = actual(store, asset_id, evidence_ids)
            payload = json.loads(json.dumps(payload))
            payload["documentation_result"]["status"] = "DISCOVERY_ONLY"
            payload["documentation_result"]["coverage_scope"] = "discovery_only"
            return asset, evidences, payload
        with patch.object(script_review_module, "_payload_record", side_effect=discovery_payload):
            with self.assertRaisesRegex(ValueError, "passage reading"):
                self._start(task_id="discovery-only")


if __name__ == "__main__":
    unittest.main()
