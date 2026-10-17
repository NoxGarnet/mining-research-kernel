from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema

from mining_research_kernel.documentation_records import record_documentation_query
from mining_research_kernel.records import ResearchStore
from mining_research_kernel.r2_workflow import task_inspect
from research_project import enable_research
from tests.test_r1_documentation import PAGE, html_page


REPO = Path(__file__).resolve().parents[1]


class DocumentationRecordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="documentation-records-", dir=REPO / "tests")
        self.base = Path(self.temp.name)
        self.project = self.base / "project"
        self.project.mkdir()
        self.docs = self.base / "host-docs"
        self.page_path = self.docs / Path(*PAGE.split("/"))
        self.page_path.parent.mkdir(parents=True)
        self.page_path.write_bytes(html_page())
        self.registration_path = self.base / "host-registration.json"
        enable_research(self.project, "docs.project")
        self.register()

    def tearDown(self):
        self.temp.cleanup()

    def register(self, *, trust="official_local", family="9.6", build="9.6.44", digest=None):
        # The hand-built page only exercises provider mechanics; it is not
        # evidence from an actual official documentation source.
        body = self.page_path.read_bytes()
        registration = {
            "schema_version": 1,
            "source_id": "example.docs.local",
            "root": str(self.docs),
            "product": "flac3d",
            "document_family": family,
            "document_build": build,
            "trust_class": trust,
            "product_subdir": "flac3d",
            "pages": {PAGE: digest or hashlib.sha256(body).hexdigest()},
        }
        self.registration_path.write_text(json.dumps(registration), encoding="utf-8")

    def query(self, task_id="doc-query-1", **overrides):
        args = {
            "task_id": task_id,
            "question": "Does the selected syntax page name this command?",
            "registration": self.registration_path,
            "page": PAGE,
            "command": "zone list",
            "product": "flac3d",
            "product_version": "9.6",
        }
        args.update(overrides)
        return record_documentation_query(self.project, **args)

    def test_unenabled_project_fails_without_writing(self):
        unenabled = self.base / "unenabled"
        unenabled.mkdir()
        with self.assertRaisesRegex(ValueError, "research records are not enabled"):
            record_documentation_query(
                unenabled, task_id="unenabled-1", question="q",
                registration=self.registration_path, page=PAGE, command="zone list",
                product="flac3d", product_version="9.6",
            )
        self.assertFalse((unenabled / "research").exists())

    def test_records_matching_query_and_replays_without_source_read(self):
        original = self.page_path.read_bytes()
        result = self.query()
        self.assertEqual(original, self.page_path.read_bytes())
        self.assertEqual("VERIFIED", result["documentation_result"]["status"])
        self.assertTrue(result["query_performed"])
        self.assertFalse(result["replayed"])
        packet = result["task_packet"]
        self.assertEqual("completed", packet["state"])
        self.assertFalse(packet["execution_authorized"])
        self.assertFalse(packet["documentation_required"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", packet["research_judgment_status"])

        store = ResearchStore(self.project)
        records = store.list_transactions()[0]["records"]
        by_type = {record["type"]: record for record in records}
        asset = by_type["Asset"]
        evidence = by_type["Evidence"]
        decision = by_type["Decision"]
        self.assertEqual(hashlib.sha256(json.dumps(
            asset["payload"], ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")).hexdigest(), asset["content_sha256"])
        self.assertNotEqual(result["documentation_result"]["citation"]["sha256_body"],
                            asset["content_sha256"])
        self.assertEqual("PROVISIONAL_WITH_GAPS", decision["judgment"]["status"])
        self.assertIn("zone list", decision["statement"])
        self.assertIn("requested version 9.6", decision["statement"])
        self.assertIn("VERIFIED", decision["statement"])
        self.assertIn("coverage=command_name_only", decision["statement"])
        self.assertFalse(decision["judgment"]["next_action"]["executable"])
        self.assertTrue(decision["judgment"]["next_action"]["requires_user_choice"])
        self.assertEqual(asset["id"], evidence["asset_ref"])
        self.assertEqual(f"record:{asset['id']}#payload", asset["locator"]["path"])
        self.assertEqual("record_embedded", asset["locator"]["path_kind"])
        self.assertEqual(asset["id"], asset["locator"]["record_id"])
        self.assertEqual("payload", asset["locator"]["field"])
        packet_schema = json.loads((REPO / "schemas" / "task_packet.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(packet_schema).validate(packet)
        asset_schema = json.loads((REPO / "schemas" / "research_asset.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(asset_schema).validate(asset)
        evidence_schema = json.loads((REPO / "schemas" / "research_evidence.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator(evidence_schema).validate(evidence)

        # The page is gone on replay, proving recovery uses the persisted snapshot.
        self.page_path.unlink()
        replay = self.query()
        self.assertTrue(replay["replayed"])
        self.assertFalse(replay["query_performed"])
        self.assertEqual(result["documentation_result"], replay["documentation_result"])
        resumed = task_inspect(self.project, "doc-query-1")
        self.assertEqual("completed", resumed["state"])
        self.assertEqual(result["decision_id"], resumed["review_record_ref"])
        self.assertEqual(result["documentation_result"], resumed["documentation_result"])

    def test_reusing_task_id_for_different_question_or_registration_is_rejected(self):
        self.query()
        with self.assertRaisesRegex(ValueError, "different documentation query"):
            self.query(question="A different question")
        self.register(build="9.6.45")
        with self.assertRaisesRegex(ValueError, "different documentation query"):
            self.query()
        self.assertEqual(1, len(ResearchStore(self.project).list_transactions()))

    def test_failed_provider_observation_is_recorded_with_unverified_scope(self):
        self.page_path.write_bytes(b"<html>changed</html>")
        result = self.query()
        self.assertEqual("CANNOT_VERIFY", result["documentation_result"]["status"])
        self.assertEqual("page_hash_drift", result["documentation_result"]["stop_reason"])
        self.assertEqual("completed", result["task_packet"]["state"])
        self.assertEqual("INSUFFICIENT", result["task_packet"]["research_judgment_status"])
        self.assertEqual("CANNOT_VERIFY", result["task_packet"]["documentation_status"])
        self.assertTrue(result["task_packet"]["material_gaps"])

    def test_page_version_mismatch_is_preserved(self):
        result = self.query(product_version="9.5")
        self.assertEqual("CANNOT_VERIFY", result["documentation_result"]["status"])
        self.assertEqual("target_product_version_mismatch", result["documentation_result"]["stop_reason"])
        self.assertIsNone(result["documentation_result"]["citation"]["sha256_body"])

    def test_synthetic_source_cannot_become_production_verified(self):
        self.register(trust="synthetic")
        result = self.query()
        self.assertEqual("CANNOT_VERIFY", result["documentation_result"]["status"])
        self.assertEqual("synthetic_source_not_for_production",
                         result["documentation_result"]["stop_reason"])
        self.assertEqual("INSUFFICIENT", result["decision"]["judgment"]["status"])

    def test_synthetic_context_keeps_synthetic_trust_class(self):
        self.register(trust="synthetic")
        result = self.query(task_context="synthetic")
        self.assertEqual("SYNTHETIC_VERIFIED", result["documentation_result"]["status"])
        self.assertEqual("synthetic", result["documentation_result"]["citation"]["trust_class"])

    def test_registration_path_and_source_body_are_not_persisted(self):
        body = self.page_path.read_bytes()
        registration_path = str(self.registration_path.resolve())
        root_path = str(self.docs.resolve())
        self.query()
        all_records = json.dumps(ResearchStore(self.project).list_transactions(), ensure_ascii=False)
        self.assertNotIn(registration_path, all_records)
        self.assertNotIn(root_path, all_records)
        self.assertNotIn(body.decode("utf-8"), all_records)
        self.assertEqual(body, self.page_path.read_bytes())

    def test_concurrent_identical_requests_commit_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.query("same-task"), range(2)))
        self.assertEqual(1, sum(bool(item["query_performed"]) for item in results))
        self.assertEqual(1, len(ResearchStore(self.project).list_transactions()))


if __name__ == "__main__":
    unittest.main()
