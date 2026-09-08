import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from adapters.flac3d import discover
from flac3d_project import init_project, load_config
from mining_kernel import discover_all


class Phase1ContractTests(unittest.TestCase):
    def test_schema_contracts_have_strict_top_level_shape(self):
        root = Path(__file__).parents[1] / "schemas"
        for name in ("task_packet", "route", "research_map", "failure", "cognition_proposal", "provider_capability"):
            schema = json.loads((root / f"{name}.schema.json").read_text(encoding="utf-8"))
            self.assertEqual("object", schema["type"])
            self.assertIn("schema_version", schema["required"])
            self.assertIn("schema_version", schema["properties"])
            self.assertIn("const", schema["properties"]["schema_version"])
            self.assertIn("additionalProperties", schema)
        self.assertIn("enum", json.loads((root / "failure.schema.json").read_text())["properties"]["severity"])
        required = {
            "task_packet": {"task_id", "workflow_id", "task_type", "maturity", "documentation_status", "execution_authorized"},
            "route": {"parent_route_id", "research_question_id", "hypothesis_id", "workflow_id", "method_id", "status", "stop_conditions"},
            "research_map": {"project_id", "nodes", "edges"},
            "failure": {"project_id", "run_id", "route_id", "observable_failure", "applicability"},
            "cognition_proposal": {"project_id", "statement", "evidence_refs", "scope", "requested_status"},
            "provider_capability": {"provider_kind", "available", "host_local", "authorization_required"},
        }
        for name, fields in required.items():
            schema = json.loads((root / f"{name}.schema.json").read_text(encoding="utf-8"))
            self.assertTrue(fields.issubset(set(schema["required"])))

    def test_init_blank_and_synthetic_are_portable_and_non_overwriting(self):
        for template in ("blank", "synthetic"):
            with tempfile.TemporaryDirectory() as td:
                root = Path(td) / "project"
                init_project(root, "demo_project", template)
                config = load_config(root)
                self.assertEqual("demo_project", config["project_id"])
                self.assertEqual("disabled", config["execution"]["provider"])
                self.assertEqual("auto", config["documentation"]["provider"])
                self.assertEqual(hashlib.sha256((root / config["entry"]).read_bytes()).hexdigest(),
                                 discover(root)["assets"][0]["sha256"])
                with self.assertRaises(ValueError): init_project(root, "demo_project", template)

    def test_configured_discovery_and_old_discovery_boundary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "project"
            init_project(root, "portable_flac3d")
            result = discover_all(root)
            portable = next(row for row in result if row["project_id"] == "portable_flac3d")
            self.assertEqual("disabled", portable["providers"]["execution"]["provider"])
            self.assertEqual("CANNOT_VERIFY", portable["verification_gates"][0]["status"])
        with tempfile.TemporaryDirectory() as td:
            synthetic = Path(__file__).parents[1] / "examples" / "synthetic_workspace"
            # The existing fixture has no portable config and remains unchanged.
            self.assertEqual({"flac3d_coal_roadway", "ceramsite_research"},
                             {row["project_id"] for row in discover_all(synthetic)})

    def test_invalid_schema_missing_id_and_path_escape_have_clear_errors(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            init_project(root, "valid_project")
            config_path = root / "flac3d_project.yaml"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            config["schema_version"] = 99
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unsupported FLAC3D project schema_version"):
                load_config(root)
            config["schema_version"] = 1
            del config["project_id"]
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing required config fields: project_id"):
                load_config(root)
            config["project_id"] = "valid_project"
            config["entry"] = "../outside.dat"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "entry contains an unsafe relative path"):
                load_config(root)

    def test_limited_yaml_subset_is_supported_without_code_execution(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            lines = [
                "schema_version: 1", "project_id: yaml_project", "domain: mining geomechanics",
                "product: FLAC3D", "product_version: unspecified", "entry: model/entry.dat",
                "baseline: model/baseline.dat", "errors: notes/errors.md", "decisions: notes/decisions.md",
                "research_map: research_map.json", "documentation:", "  provider: auto",
                "execution:", "  provider: disabled", "verification:", "  project_checks:",
                "    - entry_exists", "    - baseline_exists"]
            (root / "flac3d_project.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
            self.assertEqual("yaml_project", load_config(root)["project_id"])

    def test_cli_matches_completion_plan_and_discovers_project_root(self):
        cli = Path(__file__).parents[1] / "mining_kernel.py"
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "cli-project"
            result = subprocess.run(
                [sys.executable, str(cli), "init-flac3d-project", str(target),
                 "--project-id", "cli_project", "--template", "synthetic"],
                capture_output=True, text=True, cwd=str(cli.parent))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("cli_project", json.loads(result.stdout)["project_id"])
            discovered = subprocess.run(
                [sys.executable, str(cli), "--workspace", str(target), "discover"],
                capture_output=True, text=True, cwd=str(cli.parent))
            self.assertEqual(0, discovered.returncode, discovered.stderr)
            rows = json.loads(discovered.stdout)
            self.assertEqual(["cli_project"], [row["project_id"] for row in rows])
            self.assertEqual([], rows[0]["diagnostics"])


if __name__ == "__main__":
    unittest.main()
