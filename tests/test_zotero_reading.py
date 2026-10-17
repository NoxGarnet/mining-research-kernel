import copy
import json
import sys
import unittest
from pathlib import Path

import jsonschema

REPO = Path(__file__).parents[1]
sys.path.insert(0, str(REPO))

from adapters.zotero_mcp_readonly import READ_OPERATIONS
from mining_research_kernel.zotero_reading import CaptureValidationError, collect_reading, validate_capture


ITEM_KEY = "PAPER001"
ATTACHMENT_KEY = "PDFKEY01"


def metadata(key=ITEM_KEY, *, parent=None, version=0, library_id=0,
             title="A synthetic paper", collections=None):
    data = {"key": key, "version": version, "itemType": "journalArticle",
            "title": title, "DOI": "https://doi.org/10.1234/Example",
            "collections": [] if collections is None else collections}
    if parent is not None:
        data["parentItem"] = parent
        data["itemType"] = "attachment"
        data["contentType"] = "application/pdf"
    return {"structuredContent": {"result": json.dumps({
        "key": key, "version": version, "library": {"id": library_id, "type": "user"}, "data": data
    })}}


def page_text(key=ATTACHMENT_KEY, start=1, end=1, body="Selected synthetic page text"):
    return {"content": [{"type": "text", "text":
        f"# PDF Pages {start}-{end} of PDF\n**Item Key:** {key}\n**Total pages in PDF:** 23\n\n## Page {start}\n{body}"}]}


def reader_for(*, mismatch=False, page_response=None, metadata_response=None,
               parent_version=None, collections=None, omit_collections=False):
    calls = []

    def reader(operation, params):
        calls.append((operation, params))
        if operation == "zotero_get_item_metadata":
            if metadata_response is not None and params["item_key"] == ITEM_KEY:
                return metadata_response
            if params["item_key"] == ITEM_KEY:
                response = metadata(collections=collections)
                if omit_collections:
                    payload = json.loads(response["structuredContent"]["result"])
                    payload["data"].pop("collections", None)
                    response["structuredContent"]["result"] = json.dumps(payload)
                return response
            return metadata(ATTACHMENT_KEY, parent="OTHER001" if mismatch else ITEM_KEY,
                            version=parent_version)
        if operation == "zotero_read_pdf_pages":
            return page_response if page_response is not None else page_text(
                params["item_key"], params["start_page"], params["end_page"])
        raise AssertionError(f"unexpected operation {operation}")

    return reader, calls


class ZoteroReadingTests(unittest.TestCase):
    def collect(self, reader, **kwargs):
        return collect_reading(reader, instance_id="a" * 16, library_id="users/0",
                               item_key=ITEM_KEY, **kwargs)

    def test_metadata_only_retains_raw_metadata_fields_and_zero_version(self):
        reader, calls = reader_for()
        capture = self.collect(reader)
        self.assertEqual("read", capture["metadata_status"])
        self.assertEqual({"key": ITEM_KEY, "version": 0, "title": "A synthetic paper",
                          "item_type": "journalArticle", "doi": "10.1234/example"}, capture["item"])
        self.assertEqual([], capture["pages"])
        self.assertEqual(["zotero_get_item_metadata"], [op for op, _ in calls])

    def test_doi_url_is_not_mistaken_for_a_drive_path(self):
        capture = {"schema_version": 1, "kind": "zotero_reading_capture",
                   "origin": "synthetic", "instance_id": "a" * 16,
                   "library_id": "users/0", "captured_at": "2026-10-17T00:00:00Z",
                   "item": {"key": ITEM_KEY, "version": 0,
                            "title": "https://doi.org/10.1234/example",
                            "item_type": "journalArticle", "doi": "10.1234/example"},
                   "collection_key": None, "metadata_status": "read", "pages": [], "diagnostics": []}
        self.assertEqual(capture, validate_capture(capture))

    def test_supplied_collection_must_be_confirmed_before_attachment_or_page_reads(self):
        for reader_kwargs, expected_ops in (
            ({"collections": []}, ["zotero_get_item_metadata"]),
            ({"omit_collections": True}, ["zotero_get_item_metadata"]),
        ):
            with self.subTest(reader_kwargs=reader_kwargs):
                reader, calls = reader_for(**reader_kwargs)
                capture = self.collect(reader, collection_key="COLLECT1", pages=[{
                    "attachment_key": ATTACHMENT_KEY, "start_page": 1, "end_page": 1,
                }])
                self.assertEqual("collection_unavailable",
                                 next((d["code"] for d in capture["diagnostics"]
                                       if d["code"] == "collection_unavailable"), None))
                self.assertEqual("unavailable", capture["pages"][0]["status"])
                self.assertEqual(expected_ops, [op for op, _ in calls])

        reader, calls = reader_for(collections=["COLLECT1"])
        capture = self.collect(reader, collection_key="COLLECT1", pages=[{
            "attachment_key": ATTACHMENT_KEY, "start_page": 1, "end_page": 1,
        }])
        self.assertEqual("read", capture["pages"][0]["status"])
        self.assertNotIn("collection_unavailable", [d["code"] for d in capture["diagnostics"]])
        self.assertIn("zotero_read_pdf_pages", [op for op, _ in calls])

    def test_page_capture_binds_attachment_and_hashes_selected_pages(self):
        reader, calls = reader_for(parent_version=None)
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        page = capture["pages"][0]
        self.assertEqual(("read", None), (page["status"], page["attachment_version"]))
        self.assertEqual("Selected synthetic page text", page["excerpt"])
        self.assertEqual(64, len(page["text_sha256"]))
        expected_text = page_text()["content"][0]["text"]
        import hashlib
        self.assertEqual(hashlib.sha256(expected_text.encode("utf-8")).hexdigest(), page["text_sha256"])
        self.assertNotIn("Total pages in PDF", page["excerpt"])
        self.assertEqual(["zotero_get_item_metadata", "zotero_get_item_metadata",
                          "zotero_read_pdf_pages"], [op for op, _ in calls])

    def test_parent_mismatch_never_reads_page(self):
        reader, calls = reader_for(mismatch=True)
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        self.assertEqual("read", capture["metadata_status"])
        self.assertEqual("unavailable", capture["pages"][0]["status"])
        self.assertNotIn("zotero_read_pdf_pages", [op for op, _ in calls])

    def test_error_result_and_error_text_never_become_successful_metadata(self):
        for response in (
            {"isError": True, "content": [{"type": "text", "text": "title: fake success"}]},
            {"content": [{"type": "text", "text": "Error: permission denied"}]},
        ):
            with self.subTest(response=response):
                reader, calls = reader_for(metadata_response=response)
                capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                                       "start_page": 1, "end_page": 1}])
                self.assertEqual("unavailable", capture["metadata_status"])
                self.assertEqual("", capture["item"]["title"])
                self.assertEqual("unavailable", capture["pages"][0]["status"])
                self.assertNotIn("zotero_read_pdf_pages", [op for op, _ in calls])
                self.assertIn("metadata_unavailable", [d["code"] for d in capture["diagnostics"]])

    def test_duplicate_or_conflicting_response_keys_fail_closed(self):
        response = {"content": [{"type": "text", "text":
            '{"key":"PAPER001","key":"OTHER001","library":{"id":0,"type":"user"},'
            '"data":{"key":"PAPER001","itemType":"journalArticle","title":"fake"}}'}]}
        reader, _ = reader_for(metadata_response=response)
        capture = self.collect(reader)
        self.assertEqual("unavailable", capture["metadata_status"])

        conflicting = {"key": ITEM_KEY, "itemKey": "OTHER001",
                       "library": {"id": 0, "type": "user"},
                       "data": {"key": ITEM_KEY, "itemType": "journalArticle", "title": "fake"}}
        reader, _ = reader_for(metadata_response=conflicting)
        self.assertEqual("unavailable", self.collect(reader)["metadata_status"])

    def test_page_key_and_range_must_match_before_capture(self):
        reader, _ = reader_for(page_response=page_text(key="OTHER001"))
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        page = capture["pages"][0]
        self.assertEqual(("unavailable", None, ""),
                         (page["status"], page["text_sha256"], page["excerpt"]))

    def test_heading_only_page_is_unavailable_and_article_error_words_are_text(self):
        reader, _ = reader_for(page_response=page_text(body="  "))
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        self.assertEqual("unavailable", capture["pages"][0]["status"])

        reader, _ = reader_for(page_response=page_text(body="Error: this sentence is article content."))
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        self.assertEqual("read", capture["pages"][0]["status"])

    def test_missing_versions_are_unknown_and_null_is_valid(self):
        response = {"key": ITEM_KEY, "library": {"id": 0, "type": "user"},
                    "data": {"key": ITEM_KEY, "itemType": "journalArticle", "title": "Synthetic"}}
        reader, _ = reader_for(metadata_response=response)
        capture = self.collect(reader)
        self.assertIsNone(capture["item"]["version"])
        known_zero = json.loads(metadata()["structuredContent"]["result"])["version"]
        self.assertEqual(0, known_zero)

    def test_strict_runtime_and_json_schema_accept_same_valid_capture(self):
        reader, _ = reader_for()
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        schema = json.loads((REPO / "schemas/zotero_reading_capture.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(schema).validate(capture)
        returned = validate_capture(capture)
        self.assertEqual(capture, returned)
        self.assertIsNot(capture, returned)
        returned["item"]["title"] = "changed copy"
        self.assertNotEqual("changed copy", capture["item"]["title"])

    def test_schema_structural_and_runtime_field_validation(self):
        reader, _ = reader_for()
        capture = self.collect(reader)
        schema = json.loads((REPO / "schemas/zotero_reading_capture.schema.json").read_text(encoding="utf-8"))
        for mutate in (
            lambda x: x.update(extra="forbidden"),
            lambda x: x.update(schema_version=True),
            lambda x: x["item"].update(version=True),
            lambda x: x.update(captured_at="2026-10-17T00:00:00"),
            lambda x: x["item"].update(title=""),
        ):
            bad = copy.deepcopy(capture)
            mutate(bad)
            with self.subTest(bad=bad):
                with self.assertRaises(CaptureValidationError):
                    validate_capture(bad)
                self.assertFalse(jsonschema.Draft202012Validator(schema).is_valid(bad))

    def test_runtime_enforces_relational_page_bounds_beyond_json_schema(self):
        reader, _ = reader_for()
        capture = self.collect(reader, pages=[{"attachment_key": ATTACHMENT_KEY,
                                               "start_page": 1, "end_page": 1}])
        invalid_range = copy.deepcopy(capture)
        invalid_range["pages"][0]["start_page"] = 2
        invalid_range["pages"][0]["end_page"] = 1
        schema = json.loads((REPO / "schemas/zotero_reading_capture.schema.json").read_text(encoding="utf-8"))
        self.assertTrue(jsonschema.Draft202012Validator(schema).is_valid(invalid_range))
        with self.assertRaises(CaptureValidationError):
            validate_capture(invalid_range)

    def test_bool_ranges_and_resource_bounds_are_rejected_before_reader(self):
        called = []
        reader = lambda op, params: called.append((op, params))
        bad_inputs = (
            [{"attachment_key": ATTACHMENT_KEY, "start_page": True, "end_page": 1}],
            [{"attachment_key": ATTACHMENT_KEY, "start_page": 3, "end_page": 2}],
            [{"attachment_key": ATTACHMENT_KEY, "start_page": 1, "end_page": 11}],
            [{"attachment_key": ATTACHMENT_KEY, "start_page": 1, "end_page": 1}] * 11,
        )
        for pages in bad_inputs:
            with self.subTest(pages=len(pages)):
                with self.assertRaises(ValueError):
                    self.collect(reader, pages=pages)
        self.assertEqual([], called)

    def test_invalid_identity_and_origin_are_rejected_before_reader(self):
        called = []
        reader = lambda op, params: called.append((op, params))
        for overrides in ({"instance_id": None}, {"library_id": 0}, {"origin": "local"}):
            args = {"instance_id": "a" * 16, "library_id": "users/0", "item_key": ITEM_KEY}
            args.update(overrides)
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                collect_reading(reader, **args)
        self.assertEqual([], called)

    def test_only_allowlisted_read_operations_are_present(self):
        self.assertEqual({"zotero_get_collections", "zotero_get_collection_items",
                          "zotero_get_item_metadata", "zotero_get_item_children",
                          "zotero_get_item_fulltext", "zotero_search_items",
                          "zotero_read_pdf_pages"}, READ_OPERATIONS)
        self.assertTrue(all("write" not in operation and "update" not in operation and
                            "delete" not in operation and "create" not in operation
                            for operation in READ_OPERATIONS))


if __name__ == "__main__":
    unittest.main()
