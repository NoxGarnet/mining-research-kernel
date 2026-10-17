from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from mining_research_kernel.records import ResearchStore
from mining_research_kernel.zotero_workflow import read_zotero, search_zotero
from providers.zotero import ZoteroHostError, ZoteroReader, load_registration, validate_registration
from research_project import enable_research


REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "fixtures" / "zotero_stdio_server.py"


class ZoteroWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="zotero-stdio-", dir=REPO / "tests")
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        enable_research(self.project, "zotero.workflow.project")
        self.registration_file = self.root / "host.json"
        self.profile = {
            "schema_version": 1, "kind": "zotero_stdio",
            "instance_id": "0123456789abcdef0123456789abcdef", "library_id": "users/12345",
            "command": str(Path(sys.executable).resolve()),
            "args": [str(FIXTURE), "normal"],
        }
        self.write_profile()

    def tearDown(self):
        self.temp.cleanup()

    def write_profile(self):
        self.registration_file.write_text(json.dumps(self.profile), encoding="utf-8")

    def test_strict_registration_rejects_bad_values_before_process_launch(self):
        bad_profiles = [
            {**self.profile, "schema_version": True},
            {**self.profile, "timeout_seconds": True},
            {**self.profile, "unexpected": "field"},
            {**self.profile, "args": ["ok", 2]},
            {**self.profile, "instance_id": "not-hex"},
            {**self.profile, "command": str(REPO / "missing-executable")},
        ]
        with patch("providers.zotero.subprocess.Popen") as popen:
            for item in bad_profiles:
                with self.subTest(item=item), self.assertRaises(ValueError):
                    validate_registration(item)
            popen.assert_not_called()
        self.registration_file.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "strict UTF-8 JSON"):
            load_registration(self.registration_file)

    def test_schema_and_loader_normalize_defaults_without_persisting_profile(self):
        schema = json.loads((REPO / "schemas" / "zotero_stdio_registration.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        loaded = load_registration(self.registration_file)
        self.assertEqual(30, loaded["timeout_seconds"])
        self.assertNotIn("cwd", loaded)
        self.assertEqual(self.profile["instance_id"], loaded["instance_id"])

    def test_live_read_returns_ephemeral_bounded_text_and_replay_does_not_launch(self):
        result = read_zotero(self.project, registration=self.registration_file,
                             task_id="live-read-1", question="What does page 1 report?",
                             item_key="PAPER001", attachment_key="ATTACH01", pages="1",
                             max_reading_chars=180)
        self.assertEqual("PASS", result["status"])
        self.assertTrue(result["source_read_performed"])
        self.assertTrue(result["source_read_attempted"])
        self.assertTrue(result["query_performed"])
        self.assertEqual(180, len(result["reading_texts"][0]["text"]))
        self.assertTrue(result["reading_texts"][0]["truncated"])
        self.assertGreater(result["reading_texts"][0]["original_char_count"], 180)
        stored_asset = json.dumps(ResearchStore(self.project).latest_record(
            result["task_packet"]["asset_refs"][0], "Asset"))
        self.assertNotIn("reading_texts", stored_asset)
        self.assertNotIn(str(FIXTURE), stored_asset)
        self.assertNotIn(str(self.registration_file), stored_asset)
        with patch("mining_research_kernel.zotero_workflow.ZoteroReader") as reader_cls:
            replay = read_zotero(self.project, registration=self.registration_file,
                                 task_id="live-read-1", question="What does page 1 report?",
                                 item_key="PAPER001", attachment_key="ATTACH01", pages="1")
            reader_cls.assert_not_called()
        self.assertTrue(replay["replayed"])
        self.assertEqual("PASS", replay["status"])
        self.assertEqual([], replay["reading_texts"])
        self.assertTrue(replay["originaltext_not_reread"])
        self.assertFalse(replay["query_performed"])
        self.assertFalse(replay["source_read_performed"])
        self.assertFalse(replay["source_read_attempted"])

    def test_search_preflights_collections_and_returns_raw_bounded_search_result(self):
        result = search_zotero(self.registration_file, query="roof support", limit=4)
        self.assertEqual("PASS", result["status"])
        self.assertTrue(result["query_performed"])
        self.assertEqual("[]", result["result"]["content"][0]["text"])

    def test_source_failure_is_sanitized_and_saved_as_unavailable_capture(self):
        self.profile["args"] = [str(FIXTURE), "rpc_error"]
        self.write_profile()
        result = read_zotero(self.project, registration=self.registration_file,
                             task_id="failed-read-1", question="Read page 1",
                             item_key="PAPER001", attachment_key="ATTACH01", pages="1")
        self.assertEqual("INSUFFICIENT", result["decision"]["judgment"]["status"])
        self.assertEqual("CANNOT_VERIFY", result["status"])
        self.assertTrue(result["source_read_attempted"])
        self.assertFalse(result["source_read_performed"])
        self.assertTrue(result["task_packet"])
        self.assertFalse(result["reading_texts"])
        self.assertNotIn("fixture secret", json.dumps(result))
        replay = read_zotero(self.project, registration=self.registration_file,
                             task_id="failed-read-1", question="Read page 1",
                             item_key="PAPER001", attachment_key="ATTACH01", pages="1")
        self.assertEqual("CANNOT_VERIFY", replay["status"])
        self.assertTrue(replay["originaltext_not_reread"])

    def test_host_timeout_and_malformed_response_are_bounded_and_cleaned(self):
        for mode, expected in (("timeout", "host_timeout"), ("malformed", "malformed_response")):
            profile = {**self.profile, "args": [str(FIXTURE), mode], "timeout_seconds": 1}
            with self.subTest(mode=mode):
                reader = ZoteroReader(profile)
                with self.assertRaises(ZoteroHostError):
                    reader.__enter__()
                self.assertIsNone(reader.process)

    def test_tool_list_pagination_is_complete_and_missing_page_fails_closed(self):
        for mode in ("paginated", "missing_tools"):
            profile = {**self.profile, "args": [str(FIXTURE), mode]}
            with self.subTest(mode=mode):
                reader = ZoteroReader(profile)
                if mode == "paginated":
                    with reader:
                        self.assertIn("zotero_read_pdf_pages", reader._tools)
                else:
                    profile_file = self.root / "partial-host.json"
                    profile_file.write_text(json.dumps(profile), encoding="utf-8")
                    partial = read_zotero(self.project, registration=profile_file,
                                          task_id="metadata-partial-1", question="Paper title?",
                                          item_key="PAPER001")
                    self.assertEqual("PASS", partial["status"])
                    reader = ZoteroReader(load_registration(profile_file))
                    with reader:
                        with self.assertRaisesRegex(ZoteroHostError, "required_read_tools_missing"):
                            reader("zotero_read_pdf_pages", {"item_key": "ATTACH01"})

    def test_pdf_key_is_required_before_launch_and_metadata_only_is_supported(self):
        with patch("providers.zotero.subprocess.Popen") as popen:
            with self.assertRaisesRegex(ValueError, "explicit attachment_key"):
                read_zotero(self.project, registration=self.registration_file,
                            task_id="auto-pdf-1", question="Read a page", item_key="PAPER001",
                            pages="1")
            popen.assert_not_called()
        metadata = read_zotero(self.project, registration=self.registration_file,
                               task_id="metadata-only-1", question="What is the paper title?",
                               item_key="PAPER001")
        self.assertEqual("METADATA_ONLY", metadata["capture_summary"]["reading_status"])
        self.assertEqual([], metadata["reading_texts"])

    def test_non_allowlisted_operation_is_rejected(self):
        with ZoteroReader(load_registration(self.registration_file)) as reader:
            with self.assertRaisesRegex(ZoteroHostError, "operation_not_allowed"):
                reader("zotero_delete_items", {})

    def test_invalid_limits_and_page_ranges_fail_before_ledger_write(self):
        for kwargs in ({"max_reading_chars": True}, {"max_reading_chars": 48001},
                       {"pages": "1-11", "attachment_key": "ATTACH01"},
                       {"pages": "1,", "attachment_key": "ATTACH01"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                read_zotero(self.project, registration=self.registration_file,
                            task_id="invalid-input", question="q", item_key="PAPER001", **kwargs)
        with patch("providers.zotero.subprocess.Popen") as popen:
            with self.assertRaisesRegex(ValueError, "task_id is invalid"):
                read_zotero(self.project, registration=self.registration_file,
                            task_id="bad task id", question="q", item_key="PAPER001")
            popen.assert_not_called()
        self.assertIsNone(ResearchStore(self.project).latest_record("invalid-input", "TaskState"))

    def test_stalled_and_oversized_requests_close_the_launched_host(self):
        stalled = {**self.profile, "args": [str(FIXTURE), "stall_stdin"], "timeout_seconds": 1}
        reader = ZoteroReader(stalled)
        with self.assertRaisesRegex(ZoteroHostError, "host_timeout"):
            with reader:
                reader("zotero_get_item_metadata", {"value": "x" * 1024 * 1024})
        self.assertIsNone(reader.process)

        oversized = ZoteroReader(self.profile)
        with self.assertRaisesRegex(ZoteroHostError, "request_too_large"):
            with oversized:
                oversized("zotero_get_item_metadata", {"value": "x" * (2 * 1024 * 1024)})
        self.assertIsNone(oversized.process)


if __name__ == "__main__":
    unittest.main()
