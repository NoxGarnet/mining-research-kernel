import json
import tempfile
import unittest
from pathlib import Path

from flac3d_project import init_project, load_config
from providers.documentation import CANNOT_VERIFY, resolve_documentation
from workflows.flac3d import build_flac3d_workflow_pack


class Phase2DocumentationTests(unittest.TestCase):
    def _legacy_fixture(self, root, version="9.0"):
        docs = root / "docs-fixture"
        docs.mkdir()
        (docs / "index.json").write_text(json.dumps({
            "product_version": version,
            "entries": [{"product": "FLAC3D", "product_version": version,
                         "topic": "gridpoint", "commands": ["list"],
                         "location": "synthetic-fixture:gridpoint"}],
        }), encoding="utf-8")
        return docs

    def test_legacy_metadata_index_cannot_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._legacy_fixture(root)
            provider = resolve_documentation({"provider": "local", "root": "docs-fixture",
                                              "version": "9.0"}, project_root=root)
            result = provider.verify_syntax("flac3d/gridpoint.html", "list", product="flac3d",
                                            product_version="9.0")
            self.assertEqual(CANNOT_VERIFY, result["status"])
            self.assertEqual("registration_required", result["stop_reason"])

    def test_legacy_callbacks_are_not_a_verified_source(self):
        calls = []

        def forged(_query):
            calls.append(True)
            raise AssertionError("legacy callback must not execute")

        provider = resolve_documentation({"provider": "auto", "version": "9.0"},
                                         installed_lookup=forged, official_lookup=forged)
        self.assertEqual(CANNOT_VERIFY, provider.verify_syntax(
            "flac3d/zone/page.html", "zone list", product="flac3d", product_version="9.0")["status"])
        self.assertFalse(calls)

        provider = resolve_documentation({"provider": "installed"}, installed_lookup=forged)
        self.assertFalse(provider.capability()["available"])
        self.assertFalse(calls)

    def test_explicit_web_and_installed_modes_remain_unavailable(self):
        for mode in ("installed", "official_web"):
            provider = resolve_documentation({"provider": mode},
                                             installed_lookup=lambda *_: {},
                                             official_lookup=lambda *_: {})
            self.assertFalse(provider.capability()["available"])
            self.assertEqual(CANNOT_VERIFY, provider.verify_syntax(
                "flac3d/zone/page.html", "zone list", product="flac3d",
                product_version="9.6")["status"])

    def test_project_config_reads_documentation_options_without_weakening_paths(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            init_project(root, "phase2_project")
            config_path = root / "flac3d_project.yaml"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["documentation"] = {"provider": "local", "root": "docs", "version": "9.0",
                                        "lookup": "index.json"}
            config_path.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual("docs", load_config(root)["documentation"]["root"])
            config["documentation"]["root"] = "../outside"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "documentation.root contains an unsafe relative path"):
                load_config(root)

    def test_workflow_is_read_only_and_has_verification_layers(self):
        pack = build_flac3d_workflow_pack()
        self.assertEqual(["existing_project", "known_workflow", "exploratory_inputs", "syntax_verification"],
                         pack["read_order"])
        self.assertEqual(["mcp_connectivity", "execution", "numerical", "physical", "engineering"],
                         pack["verification_layers"])
        self.assertFalse(pack["execution_authorized"])
        self.assertFalse(pack["mutation_allowed"])
        rendered = json.dumps(pack)
        self.assertNotIn("liner_v16", rendered)
        self.assertNotIn("coal_roadway", rendered)
        self.assertNotIn("E:\\\\", rendered)


if __name__ == "__main__":
    unittest.main()
