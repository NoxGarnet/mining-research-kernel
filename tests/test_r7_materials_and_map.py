import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.records import ResearchStore, ResearchStoreError
from mining_research_kernel.r2_workflow import research_map_rebuild


class R7MaterialsAndMapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        init_project(self.root, "r7_materials")
        self.store = ResearchStore(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def material(self, name, content):
        path = self.root / "materials" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_registers_kinds_hashes_relations_and_is_idempotent(self):
        primary = self.material("primary.txt", "primary source\n")
        project_record = self.material("decision.md", "project decision\n")
        reading_note = self.material("reading-card.md", "derived note\n")
        claim = {
            "schema_version": 1, "type": "Claim", "id": "r7-claim", "revision": 1,
            "project_id": "r7_materials", "scope": {"study": "r7"},
            "source_refs": ["r7:claim"], "statement": "A bounded claim.",
            "status": "proposed",
        }
        self.store.commit("seed-claim", {"role": "planning_agent", "model": "r7-test"}, [claim])

        results = [
            self.store.register_local_material(
                primary, "primary/original", citation_locator={"page": 1},
                source_documents_claim="r7-claim"),
            self.store.register_local_material(
                project_record, "project_record", source_documents_claim="r7-claim"),
            self.store.register_local_material(
                reading_note, "derived_reading_note", source_documents_claim="r7-claim"),
        ]
        self.assertEqual(
            {"authoritative", "derived"},
            {result["asset"]["authority"] for result in results},
        )
        self.assertEqual("derived", results[2]["asset"]["authority"])
        self.assertTrue(results[0]["asset"]["id"].startswith("asset.local."))
        self.assertEqual(
            hashlib.sha256(primary.read_bytes()).hexdigest(),
            results[0]["asset"]["content_sha256"],
        )
        self.assertEqual("materials/primary.txt", results[0]["asset"]["locator"]["path"])
        self.assertTrue(any(
            relation["relation"] == "source_documents_claim"
            for relation in results[0]["relationships"]
        ))
        before = primary.read_bytes()
        repeated = self.store.register_local_material(
            primary, "primary/original", citation_locator={"page": 1},
            source_documents_claim="r7-claim",
        )
        self.assertEqual(results[0]["asset"]["id"], repeated["asset"]["id"])
        self.assertEqual(before, primary.read_bytes())
        with self.assertRaisesRegex(ResearchStoreError, "conflicting payload"):
            self.store.register_local_material(primary, "primary/original")
        self.assertEqual(4, len(self.store.list_transactions()))

    def test_external_path_is_explicit_and_persisted_without_absolute_path(self):
        external = Path(self.temp.name) / "external" / "source.txt"
        external.parent.mkdir()
        external.write_text("external source\n", encoding="utf-8")
        result = self.store.register_local_material(external, "project_record")
        self.assertEqual("caller_label", result["asset"]["locator"]["path_kind"])
        self.assertTrue(result["asset"]["locator"]["path"].startswith("caller:"))
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertNotIn(str(external), serialized)

    def test_material_path_and_claim_boundaries_fail_closed(self):
        source = self.material("source.txt", "source\n")
        with self.assertRaisesRegex(ResearchStoreError, "escapes project root"):
            self.store.register_local_material("../outside.txt", "project_record")
        with self.assertRaisesRegex(ResearchStoreError, "existing file"):
            self.store.register_local_material(source.parent, "project_record")
        with self.assertRaisesRegex(ResearchStoreError, "existing Claim"):
            self.store.register_local_material(source, "project_record", source_documents_claim="missing-claim")
        with self.assertRaises(ResearchStoreError):
            self.store.register_local_material(source, "derived_reading_note", source_refs=[""])

    def test_default_cli_persists_map_explicit_output_and_low_level_pure_view(self):
        map_path = self.root / "research" / "map.json"
        if map_path.exists():
            map_path.unlink()
        pure = self.store.rebuild_research_map()
        self.assertEqual("ResearchMap", pure["type"])
        self.assertFalse(map_path.exists())

        cli = subprocess.run(
            [sys.executable, "-B", "mining_kernel.py", "research-map-rebuild",
             "--project-root", str(self.root)],
            cwd=Path(__file__).parents[1], capture_output=True, text=True,
        )
        self.assertEqual(0, cli.returncode, cli.stderr)
        returned = json.loads(cli.stdout)
        self.assertEqual({"nodes", "edges"}, set(returned) - {"schema_version", "type", "project_id"})
        self.assertTrue(map_path.is_file())
        self.assertEqual(returned, json.loads(map_path.read_text(encoding="utf-8")))

        explicit = self.store.rebuild_research_map("research/alternate-map.json")
        self.assertEqual(explicit, json.loads(
            (self.root / "research" / "alternate-map.json").read_text(encoding="utf-8")
        ))


if __name__ == "__main__":
    unittest.main()
