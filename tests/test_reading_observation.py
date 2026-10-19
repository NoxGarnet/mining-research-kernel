from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import jsonschema

from mining_research_kernel.reading_observation import (
    record_reading_observation,
    validate_observation,
)
from mining_research_kernel.records import ResearchStore


def _sample():
    return {
        "schema_version": 1,
        "kind": "reading_observation",
        "origin": "agent_supplied",
        "captured_at": "2026-10-19T01:00:00Z",
        "source": {
            "source_id": "library:item-42", "title": "Synthetic test article",
            "doi": "10.1234/abc.x", "url": "https://example.org/paper",
            "version": None, "source_kind": "web_article", "source_sha256": None,
            "authority": "original_publication",
        },
        "reader": {"tool": "test reader", "method": "visual"},
        "passages": [
            {"locator": {"kind": "section", "value": "Methods, paragraph 2"},
             "status": "read", "text_sha256": None, "excerpt": "A bounded observed excerpt.",
             "limitations": ["figure labels were not inspected"]},
            {"locator": {"kind": "pdf_pages", "value": "pages 8–9", "start_page": 8, "end_page": 9},
             "status": "unavailable", "text_sha256": None, "excerpt": "", "limitations": ["page image unreadable"]},
        ],
        "limitations": ["caller supplied observation; semantic correctness is not verified"],
    }


class ReadingObservationTests(unittest.TestCase):
    def test_schema_accepts_contract_and_rejects_unknown_fields(self):
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "reading_observation.schema.json").read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(_sample(), schema)
        jsonschema.validate(validate_observation(_sample()), schema)
        malformed = _sample()
        malformed["source"]["private_path"] = "should fail closed"
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(malformed, schema)

    def test_normalization_deep_copy_and_hash_domains_remain_distinct(self):
        raw = _sample()
        raw["source"]["doi"] = "https://doi.org/10.1234/ABC.X"
        validated = validate_observation(raw)
        self.assertEqual(validated["source"]["doi"], "10.1234/abc.x")
        self.assertIn("source_version_unknown", validated["limitations"])
        self.assertIn("original_source_sha256_unknown", validated["limitations"])
        self.assertIn("one_or_more_reading_text_sha256_unknown", validated["limitations"])
        self.assertNotIn("source_version_unknown", raw["limitations"])
        self.assertIsNone(validated["source"]["source_sha256"])
        self.assertIsNone(validated["passages"][0]["text_sha256"])
        self.assertEqual(validate_observation(validated), validated)

    def test_bad_enum_types_raise_value_error_and_scientific_slashes_are_allowed(self):
        cases = (
            lambda d: d.update(origin=[]),
            lambda d: d["source"].update(source_kind={}),
            lambda d: d["source"].update(authority=[]),
            lambda d: d["reader"].update(method={}),
            lambda d: d["passages"][0]["locator"].update(kind=[]),
        )
        for mutate in cases:
            item = _sample()
            mutate(item)
            with self.assertRaises(ValueError):
                validate_observation(item)
        item = _sample()
        item["source"]["title"] = "Calibration, kg / m3 and Methods / Parameter calibration"
        item["passages"][0]["excerpt"] = "Density is reported in kg / m3."
        item["passages"][0]["locator"]["value"] = "Methods / Parameter calibration"
        self.assertEqual(validate_observation(item)["passages"][0]["locator"]["value"],
                         "Methods / Parameter calibration")
        for local_path in ("/home/research/paper.pdf", "notes at /Users/person/paper.pdf", "file:///Users/person/paper.pdf"):
            item = _sample()
            item["source"]["title"] = local_path
            with self.subTest(local_path=local_path), self.assertRaises(ValueError):
                validate_observation(item)

    def test_derived_limitations_cannot_exceed_normalized_schema_bound(self):
        item = _sample()
        item["limitations"] = [f"caller gap {n}" for n in range(31)]
        with self.assertRaisesRegex(ValueError, "normalized maximum"):
            validate_observation(item)

    def test_rejects_extra_fields_types_paths_and_invalid_read_states(self):
        bad = _sample()
        bad["surprise"] = True
        with self.assertRaises(ValueError):
            validate_observation(bad)
        for mutate in (
            lambda d: d["reader"].update(tool=7),
            lambda d: d["source"].update(source_id=r"C:\private\paper.pdf"),
            lambda d: d["passages"][0].update(status="unavailable"),
            lambda d: d["passages"][1].update(text_sha256="a" * 64),
            lambda d: d["passages"][0]["locator"].update(start_page=0),
        ):
            item = _sample()
            mutate(item)
            with self.assertRaises(ValueError):
                validate_observation(item)

    def test_atomic_pair_replay_and_request_conflict(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            root = Path(tmp)
            (root / "research_project.json").write_text(json.dumps({"schema_version": 1, "project_id": "reading-test"}), encoding="utf-8")
            first = record_reading_observation(root, observation_id="capture-1", observation=_sample())
            replay = record_reading_observation(root, observation_id="capture-1", observation=_sample())
            self.assertEqual(first["status"], "recorded")
            self.assertEqual(replay["status"], "replayed")
            self.assertEqual(first["asset_ref"], replay["asset_ref"])
            self.assertEqual(first["evidence_ref"], replay["evidence_ref"])
            self.assertFalse(first["query_performed"])
            self.assertFalse(first["source_revalidated"])
            store = ResearchStore(root)
            txs = store.list_transactions()
            self.assertEqual(len(txs), 1)
            self.assertEqual([r["type"] for r in txs[0]["records"]], ["Asset", "Evidence"])
            self.assertEqual(len(txs[0]["relationships"]), 1)
            asset = store.latest_record(first["asset_ref"], "Asset")
            payload = asset["payload"]
            expected_hash = __import__("hashlib").sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self.assertEqual(asset["authority"], "derived")
            self.assertEqual(asset["content_sha256"], expected_hash)
            self.assertIsNone(payload["request"]["observation"]["source"]["source_sha256"])
            changed = _sample()
            changed["passages"][0]["excerpt"] = "changed request"
            with self.assertRaises(ValueError):
                record_reading_observation(root, observation_id="capture-1", observation=changed)

    def test_unavailable_capture_is_saved_and_synthetic_is_gated(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            root = Path(tmp)
            (root / "research_project.json").write_text(json.dumps({"schema_version": 1, "project_id": "reading-test"}), encoding="utf-8")
            data = _sample()
            for p in data["passages"]:
                p.update(status="unavailable", excerpt="", text_sha256=None)
            result = record_reading_observation(root, observation_id="failed-read", observation=data)
            self.assertEqual(result["status"], "recorded")
            self.assertEqual(result["reading_status"], "UNAVAILABLE")
            data["origin"] = "synthetic"
            with self.assertRaises(ValueError):
                record_reading_observation(root, observation_id="synthetic-prod", observation=data)

    def test_replay_rejects_damaged_asset_or_evidence(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            root = Path(tmp)
            (root / "research_project.json").write_text(json.dumps({"schema_version": 1, "project_id": "reading-test"}), encoding="utf-8")
            observation = _sample()
            created = record_reading_observation(root, observation_id="damage-check", observation=observation)
            original = ResearchStore.latest_record

            def damaged(store, record_id, record_type=None):
                value = original(store, record_id, record_type)
                if record_id == created["asset_ref"]:
                    value["content_sha256"] = "0" * 64
                return value

            with patch.object(ResearchStore, "latest_record", damaged):
                with self.assertRaisesRegex(ValueError, "Asset is damaged"):
                    record_reading_observation(root, observation_id="damage-check", observation=observation)

            def damaged_evidence(store, record_id, record_type=None):
                value = original(store, record_id, record_type)
                if record_id == created["evidence_ref"]:
                    value["asset_ref"] = "another.asset"
                return value

            with patch.object(ResearchStore, "latest_record", damaged_evidence):
                with self.assertRaisesRegex(ValueError, "Evidence is damaged"):
                    record_reading_observation(root, observation_id="damage-check", observation=observation)

    def test_concurrent_same_id_commits_one_pair(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            root = Path(tmp)
            (root / "research_project.json").write_text(json.dumps({"schema_version": 1, "project_id": "reading-test"}), encoding="utf-8")
            results, errors = [], []
            def run():
                try:
                    results.append(record_reading_observation(root, observation_id="parallel", observation=_sample()))
                except Exception as exc:  # surfaced below with the original exception
                    errors.append(exc)
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(errors, [])
            self.assertEqual({r["status"] for r in results}, {"recorded", "replayed"})
            self.assertEqual(len(ResearchStore(root).list_transactions()), 1)


if __name__ == "__main__":
    unittest.main()
