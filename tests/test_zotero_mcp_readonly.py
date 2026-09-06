import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))

from adapters.zotero_mcp_readonly import FulltextUnavailableError, ItemReadError
from extension_registry import DEFAULT_REGISTRY, ExtensionRecord, ExtensionRegistry
from mining_kernel import discover_all, discover_sources, inspect_source
from support import make_synthetic_workspace


class ZoteroMcpReadonlyTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.workspace = make_synthetic_workspace(self._temp.name)
        self.fixture = json.loads(
            (Path(__file__).parent / "fixtures" / "zotero_mcp_readonly_success.json").read_text(encoding="utf-8")
        )

    def test_default_registry_exposes_only_readonly_source_capabilities(self):
        records = DEFAULT_REGISTRY.by_kind("source")
        self.assertEqual(["mining_research_kernel.source.zotero_readonly"], [row.extension_id for row in records])
        self.assertEqual(frozenset({"discover", "inspect", "read_only"}), records[0].capabilities)
        source = discover_sources(self.workspace)[0]
        self.assertEqual("REGISTERED_READ_ONLY", source["status"])
        self.assertNotIn("write", " ".join(source["allowed_operations"]).lower())

    def test_synthetic_read_success_preserves_item_and_attachment_keys(self):
        calls = []

        def reader(operation, params):
            calls.append((operation, params))
            return self.fixture["result"]

        result = inspect_source(
            self.workspace,
            "zotero_mcp_readonly",
            reader=reader,
            operation=self.fixture["operation"],
            params=self.fixture["params"],
        )
        self.assertEqual("PASS", result["status"])
        self.assertEqual("SYNTH001", result["result"]["item_key"])
        self.assertEqual("SYNTHATT1", result["result"]["attachment_key"])
        self.assertEqual([(self.fixture["operation"], self.fixture["params"])], calls)

    def test_write_operation_is_rejected_before_reader(self):
        called = []
        result = inspect_source(
            self.workspace,
            "zotero_mcp_readonly",
            reader=lambda operation, params: called.append((operation, params)),
            operation="zotero_update_item",
            params={"item_key": "SYNTH001"},
        )
        self.assertEqual("CANNOT_VERIFY", result["status"])
        self.assertEqual("operation_not_allowed", result["diagnostics"][0]["code"])
        self.assertEqual([], called)

    def test_expected_failures_degrade_with_stable_diagnostics(self):
        cases = (
            (None, None, "extension_not_running"),
            (lambda operation, params: (_ for _ in ()).throw(ConnectionError("Zotero closed")), "zotero_get_collections", "zotero_closed"),
            (lambda operation, params: (_ for _ in ()).throw(PermissionError("Local API 403")), "zotero_get_collections", "local_api_403"),
            (lambda operation, params: (_ for _ in ()).throw(FulltextUnavailableError("no PDF text")), "zotero_get_item_fulltext", "fulltext_unavailable"),
            (lambda operation, params: (_ for _ in ()).throw(ItemReadError("synthetic bad item")), "zotero_get_item_metadata", "item_read_failed"),
        )
        for reader, operation, code in cases:
            with self.subTest(code=code):
                result = inspect_source(self.workspace, "zotero_mcp_readonly", reader=reader, operation=operation)
                self.assertEqual("CANNOT_VERIFY", result["status"])
                self.assertEqual(code, result["diagnostics"][0]["code"])

    def test_source_failure_does_not_block_existing_projects(self):
        registry = ExtensionRegistry(tuple(DEFAULT_REGISTRY.by_kind("project")) + (
            ExtensionRecord("broken_source", "source", frozenset({"discover", "read_only"}),
                            lambda workspace, **kwargs: (_ for _ in ()).throw(RuntimeError("synthetic"))),
        ))
        projects = discover_all(self.workspace, registry)
        sources = discover_sources(self.workspace, registry)
        self.assertEqual(["flac3d_coal_roadway", "ceramsite_research"], [row["project_id"] for row in projects])
        self.assertEqual("CANNOT_VERIFY", sources[0]["status"])
        self.assertEqual("source_discovery_failed", sources[0]["diagnostics"][0]["code"])


if __name__ == "__main__":
    unittest.main()
