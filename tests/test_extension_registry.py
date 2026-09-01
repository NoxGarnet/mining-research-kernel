import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from extension_registry import ExtensionRecord, ExtensionRegistry, RegistryError
from mining_kernel import discover_all
from support import make_synthetic_workspace


class ExtensionRegistryTests(unittest.TestCase):
    def test_default_projects_are_explicit_and_ordered(self):
        registry = ExtensionRegistry((
            ExtensionRecord("one", "project", frozenset({"discover", "read_only"}), lambda workspace: {"project_id": "one"}),
            ExtensionRecord("two", "project", frozenset({"discover", "read_only"}), lambda workspace: {"project_id": "two"}),
        ))
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            result = discover_all(make_synthetic_workspace(td), registry=registry)
        self.assertEqual(["one", "two"], [row["project_id"] for row in result])

    def test_third_project_requires_no_core_change_and_registration_is_isolated(self):
        def fake_project_discover(workspace):
            return {"project_id": "fake_project", "diagnostics": []}

        registry = ExtensionRegistry()
        registry.register(ExtensionRecord("fake_project", "project", frozenset({"discover"}), fake_project_discover))
        self.assertEqual(["fake_project"], [row["project_id"] for row in discover_all(Path("."), registry)])
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(["flac3d_coal_roadway", "ceramsite_research"],
                             [row["project_id"] for row in discover_all(make_synthetic_workspace(td))])

    def test_validation_diagnostics_are_stable(self):
        registry = ExtensionRegistry()
        registry._records.append(ExtensionRecord("dup", "bad", frozenset({"unknown"}), "broken"))
        registry._records.append(ExtensionRecord("dup", "project", frozenset(), lambda workspace: {}))
        self.assertEqual([
            "unknown kind: bad",
            "unknown capability: unknown",
            "missing or invalid implementation entry",
            "duplicate extension_id: dup",
        ], registry.validate())
        with self.assertRaisesRegex(RegistryError, "duplicate extension_id: dup"):
            registry.register(ExtensionRecord("dup", "project", frozenset(), lambda workspace: {}))

    def test_execution_failure_has_extension_id_and_continues(self):
        def broken(workspace):
            raise RuntimeError("synthetic failure")

        registry = ExtensionRegistry((
            ExtensionRecord("broken_project", "project", frozenset({"discover"}), broken),
            ExtensionRecord("healthy_project", "project", frozenset({"discover"}), lambda workspace: {"project_id": "healthy_project"}),
        ))
        result = discover_all(Path("."), registry=registry)
        self.assertIn("extension broken_project failed: RuntimeError: synthetic failure", result[0]["diagnostics"])
        self.assertEqual("healthy_project", result[1]["project_id"])

    def test_registration_rejects_unknown_kind_capability_and_entry(self):
        cases = (
            ("bad_kind", "wat", frozenset(), lambda workspace: {}),
            ("bad_cap", "project", frozenset({"wat"}), lambda workspace: {}),
            ("bad_entry", "project", frozenset(), "not-an-import-path"),
        )
        for extension_id, kind, capabilities, implementation in cases:
            with self.assertRaises(RegistryError):
                ExtensionRegistry().register(ExtensionRecord(extension_id, kind, capabilities, implementation))

    def test_validate_reports_unresolvable_import_entry(self):
        registry = ExtensionRegistry()
        registry._records.append(ExtensionRecord("missing_entry", "tool", frozenset(), "not_a_real_module:call"))
        self.assertEqual(["invalid implementation entry for missing_entry: not_a_real_module:call"], registry.validate())


if __name__ == "__main__":
    unittest.main()
