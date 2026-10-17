import json
import os
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project
from mining_research_kernel.config import load_route_policy
from mining_research_kernel.project_context import project_context
from mining_research_kernel.records import ResearchStore, ResearchStoreError
from research_project import enable_research, load_config
from test_workspace_starter import make_directory_link, remove_directory_link


REPO = Path(__file__).resolve().parents[1]


class ResearchProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=REPO / "tests")
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self, value, name="research_project.json"):
        (self.root / name).write_text(json.dumps(value), encoding="utf-8")

    def test_enabling_nonempty_project_adds_only_config_and_preserves_bytes(self):
        (self.root / "START.md").write_bytes(b"# existing\r\n\xff")
        (self.root / "README.md").write_bytes(b"user material\x00")
        (self.root / "inputs").mkdir()
        (self.root / "inputs" / "source.dat").write_bytes(b"MODEL INPUT\r\n")
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in self.root.rglob("*") if p.is_file()}
        result = enable_research(self.root, "paper-01")
        after = {p.relative_to(self.root).as_posix(): p.read_bytes()
                 for p in self.root.rglob("*") if p.is_file() and p.name != "research_project.json"}
        self.assertEqual("enabled", result["status"])
        self.assertEqual(before, after)
        self.assertEqual({*before, "research_project.json"}, set(
            p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()))
        self.assertFalse((self.root / "research").exists())

    def test_repeat_same_id_is_read_only_and_different_id_rejected(self):
        enable_research(self.root, "paper-01")
        config_bytes = (self.root / "research_project.json").read_bytes()
        self.assertEqual("already_enabled", enable_research(self.root, "paper-01")["status"])
        self.assertEqual(config_bytes, (self.root / "research_project.json").read_bytes())
        with self.assertRaisesRegex(ValueError, "different project_id"):
            enable_research(self.root, "paper-02")

    def test_bad_configs_conflicts_and_existing_unclaimed_records_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "project_id"):
            enable_research(self.root, "../bad")
        (self.root / "research").mkdir()
        (self.root / "research" / "records").mkdir()
        with self.assertRaisesRegex(ValueError, "without a project config"):
            enable_research(self.root, "paper-01")
        (self.root / "research" / "records").rmdir()
        (self.root / "research").rmdir()
        self.write_config({"schema_version": 1, "project_id": "paper-01", "entry": "../outside"})
        with self.assertRaisesRegex(ValueError, "entry"):
            load_config(self.root)
        (self.root / "flac3d_project.yaml").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "both"):
            load_config(self.root)
        with self.assertRaisesRegex(ValueError, "both"):
            enable_research(self.root, "paper-01")

    def test_symlinked_project_chain_is_rejected(self):
        target = Path(self.temp.name) / "actual"
        target.mkdir()
        linked = Path(self.temp.name) / "linked"
        kind, failure = make_directory_link(linked, target)
        if kind is None:
            self.skipTest(f"directory symlink/junction unavailable: {failure}")
        try:
            with self.assertRaisesRegex(ValueError, "symlink or junction"):
                enable_research(linked, "paper-01")
        finally:
            remove_directory_link(linked, kind)

    def test_legacy_project_remains_valid_and_unmodified(self):
        init_project(self.root, "legacy_project")
        config_before = (self.root / "flac3d_project.yaml").read_bytes()
        result = enable_research(self.root, "legacy_project")
        self.assertEqual("legacy_present", result["status"])
        self.assertEqual(config_before, (self.root / "flac3d_project.yaml").read_bytes())
        self.assertFalse((self.root / "research_project.json").exists())
        store = ResearchStore(self.root)
        saved = store.commit("legacy-claim", {"role": "researcher", "model": "test"}, [{
            "schema_version": 1, "type": "Claim", "id": "legacy-claim", "revision": 1,
            "project_id": "legacy_project", "scope": {"study": "compat"},
            "source_refs": ["fixture:one"], "statement": "Legacy records still work.",
            "status": "proposed",
        }])
        self.assertEqual("legacy-claim", saved["records"][0]["id"])

    def test_neutral_research_store_commit_is_visible_to_context_without_map_write(self):
        (self.root / "START.md").write_text("# Study\n", encoding="utf-8")
        enable_research(self.root, "paper-01")
        config = load_config(self.root)
        self.assertEqual(("research", "unknown", "mining research"),
                         (config["product"], config["product_version"], config["domain"]))
        self.assertEqual({"provider": "disabled"}, config["execution"])
        source = self.root / "source.txt"
        source.write_text("source bytes\n", encoding="utf-8")
        store = ResearchStore(self.root)
        registered = store.register_local_material(source, "project_record")
        view = project_context(self.root)
        self.assertEqual("paper-01", view["project_id"])
        self.assertEqual("recorded", view["store_state"])
        self.assertTrue(any(item.get("id") == registered["asset"]["id"] for item in view["items"]))
        self.assertFalse((self.root / "research" / "map.json").exists())
        self.assertTrue((self.root / "research" / "records" / "00000001.json").is_file())

    def test_neutral_route_policy_and_navigation_without_config_do_not_write(self):
        self.write_config({"schema_version": 1, "project_id": "paper-01",
                           "route_policy": {"max_active_routes": 2}})
        self.assertEqual({"max_active_routes": 2}, load_route_policy(self.root))
        files_before = {p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()}
        project_context(self.root)
        self.assertEqual(files_before, {p.relative_to(self.root).as_posix()
                                        for p in self.root.rglob("*") if p.is_file()})
        empty = Path(self.temp.name) / "navigation-only"
        empty.mkdir()
        (empty / "START.md").write_text("# No writes\n", encoding="utf-8")
        project_context(empty)
        self.assertEqual(["START.md"], [p.name for p in empty.iterdir()])

    def test_legacy_route_policy_keeps_small_yaml_compatibility(self):
        (self.root / "flac3d_project.yaml").write_text(
            "route_policy:\n  max_active_routes: 2\n", encoding="utf-8")
        self.assertEqual({"max_active_routes": 2}, load_route_policy(self.root))

    def test_config_schema_and_loader_agree_on_relative_paths(self):
        from jsonschema import Draft202012Validator
        schema = json.loads((REPO / "schemas/research_project.schema.json").read_text(encoding="utf-8"))
        validator = Draft202012Validator(schema)
        for path in ("START.md", "notes/current.md", "x"):
            with self.subTest(path=path):
                config = {"schema_version": 1, "project_id": "study", "entry": path}
                self.assertTrue(validator.is_valid(config))
                self.write_config(config)
                self.assertEqual(path, load_config(self.root)["entry"])
        for path in ("../START.md", "./START.md", "notes//current.md", "notes/", "/START.md",
                     "notes:current.md", "notes\\current.md", "notes/../current.md", "x\x00.md"):
            with self.subTest(path=path):
                config = {"schema_version": 1, "project_id": "study", "entry": path}
                self.assertFalse(validator.is_valid(config))
                self.write_config(config)
                with self.assertRaises(ValueError):
                    load_config(self.root)


if __name__ == "__main__":
    unittest.main()
