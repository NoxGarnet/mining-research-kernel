import json
import unittest
from pathlib import Path
from unittest.mock import patch

from default_extensions import DEFAULT_REGISTRY
from mining_research_kernel.interfaces import (
    AgentHostAdapter, ArtifactStore, CognitionPolicy, DocumentationProvider,
    ExecutionProvider, KnowledgeProvider, ProjectAdapter, SourceProvider,
    TransformProvider, WorkflowPack,
)
from mining_research_kernel.registry import ALLOWED_KINDS, ExtensionRecord, ExtensionRegistry, RegistryError
from workflows.flac3d import METHOD_IDS, WORKFLOW_ID, build_flac3d_workflow_pack


class ExtensionConformanceTests(unittest.TestCase):
    def test_default_records_expose_contract_metadata_and_namespaced_ids(self):
        self.assertEqual([], DEFAULT_REGISTRY.validate())
        self.assertTrue(DEFAULT_REGISTRY.records)
        self.assertEqual({"workflow", "project", "documentation", "source", "execution", "knowledge",
                          "transform", "cognition_policy", "artifact_store", "agent_host"}, set(ALLOWED_KINDS))
        self.assertEqual(1, len(DEFAULT_REGISTRY.by_kind("workflow")))
        self.assertEqual(1, len(DEFAULT_REGISTRY.by_kind("documentation")))
        for record in DEFAULT_REGISTRY.records:
            self.assertRegex(record.extension_id, r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
            self.assertEqual(1, record.contract_version)
            self.assertTrue(record.capabilities)
            self.assertTrue(callable(DEFAULT_REGISTRY.resolve(record)))
        workflow = DEFAULT_REGISTRY.resolve(DEFAULT_REGISTRY.by_kind("workflow")[0])()
        self.assertEqual(WORKFLOW_ID, workflow["workflow_id"])
        documentation = DEFAULT_REGISTRY.resolve(DEFAULT_REGISTRY.by_kind("documentation")[0])(
            {"provider": "unavailable"})
        self.assertEqual("documentation", documentation.capability()["provider_kind"])

    def test_unknown_id_rejects_before_import(self):
        registry = ExtensionRegistry()
        with patch("mining_research_kernel.registry.importlib.import_module") as importer:
            with self.assertRaisesRegex(RegistryError, "unknown extension_id"):
                registry.resolve("untrusted.module.call")
        importer.assert_not_called()

    def test_legacy_alias_resolves_only_when_explicitly_registered(self):
        record = ExtensionRecord("test.project.synthetic", "project", frozenset({"discover"}), lambda _: {})
        registry = ExtensionRegistry((record,), aliases={"legacy_project": record.extension_id})
        self.assertIs(registry.resolve("legacy_project"), record.implementation)
        with self.assertRaises(RegistryError):
            ExtensionRegistry((record,)).resolve("legacy_project")

    def test_production_registry_rejects_unnamespaced_registration(self):
        with self.assertRaisesRegex(RegistryError, "namespaced"):
            ExtensionRegistry((ExtensionRecord("legacy_project", "project", frozenset(), lambda _: {}),))

    def test_capabilities_accept_schema_style_lists_and_empty_collections(self):
        records = (
            ExtensionRecord("test.project.empty", "project", [], lambda request: request),
            ExtensionRecord("test.source.list", "source", ["read", "inspect"], lambda request: request),
        )
        registry = ExtensionRegistry(records)
        self.assertEqual(frozenset(), records[0].capabilities)
        self.assertEqual(frozenset({"read", "inspect"}), records[1].capabilities)
        self.assertEqual([], registry.validate())

    def test_synthetic_structural_conformance_for_public_interfaces(self):
        class Synthetic:
            def discover(self, workspace): return {"workspace": workspace}
            def build(self, project=None): return {"project": project}
            def capability(self): return {"provider_kind": "documentation"}
            def verify_syntax(self, topic, command=None, **kwargs): return {"topic": topic}
            def dispatch(self, workspace, **kwargs): return {"workspace": workspace}
            def execute(self, request): return request
            def query(self, request): return request
            def transform(self, value, **kwargs): return value
            def evaluate(self, proposal): return proposal
            def put(self, artifact): return artifact
            def get(self, artifact_id): return {"artifact_id": artifact_id}
            def submit(self, task): return task

        synthetic = Synthetic()
        self.assertEqual({"workspace": "w"}, synthetic.discover("w"))
        self.assertEqual({"project": None}, synthetic.build())
        self.assertEqual({"provider_kind": "documentation"}, synthetic.capability())
        self.assertEqual({"topic": "topic"}, synthetic.verify_syntax("topic"))
        self.assertEqual({"workspace": "w"}, synthetic.dispatch("w"))
        self.assertEqual({"request": 1}, synthetic.execute({"request": 1}))
        self.assertEqual({"request": 1}, synthetic.query({"request": 1}))
        self.assertEqual("value", synthetic.transform("value"))
        self.assertEqual({"statement": "s"}, synthetic.evaluate({"statement": "s"}))
        self.assertEqual({"artifact_id": "a"}, synthetic.put({"artifact_id": "a"}))
        self.assertEqual({"artifact_id": "a"}, synthetic.get("a"))
        self.assertEqual({"task_id": "t"}, synthetic.submit({"task_id": "t"}))
        for interface in (ProjectAdapter, WorkflowPack, DocumentationProvider, SourceProvider,
                          ExecutionProvider, KnowledgeProvider, TransformProvider, CognitionPolicy,
                          ArtifactStore, AgentHostAdapter):
            self.assertTrue(getattr(interface, "_is_protocol", False))
        self.assertEqual("documentation", synthetic.capability()["provider_kind"])

    def test_workflow_and_method_ids_are_namespaced_without_core_enumeration(self):
        self.assertRegex(WORKFLOW_ID, r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
        self.assertTrue(all("." in method_id for method_id in METHOD_IDS))
        pack = build_flac3d_workflow_pack()
        self.assertEqual(WORKFLOW_ID, pack["workflow_id"])
        self.assertEqual(list(METHOD_IDS), pack["method_ids"])

    def test_updated_schemas_remove_concrete_route_method_enum(self):
        root = Path(__file__).parents[1] / "schemas"
        task = json.loads((root / "task_packet.schema.json").read_text(encoding="utf-8"))
        route = json.loads((root / "route.schema.json").read_text(encoding="utf-8"))
        provider = json.loads((root / "provider_capability.schema.json").read_text(encoding="utf-8"))
        self.assertIn("workflow_id", task["required"])
        self.assertIn("task_type", task["required"])
        self.assertIn("workflow_id", route["required"])
        self.assertIn("method_id", route["required"])
        self.assertNotIn("method", route["properties"])
        self.assertNotIn("source_kind", provider["required"])
        self.assertEqual({"documentation", "source", "execution", "knowledge", "transform"},
                         set(provider["properties"]["provider_kind"]["enum"]))

    def test_all_planned_kinds_register_and_resolve_synthetic_callables(self):
        def implementation(request):
            return {"kind": request["kind"], "value": request["value"]}

        records = tuple(ExtensionRecord(f"test.synthetic.{kind}", kind,
                                         frozenset({"synthetic.capability"}), implementation)
                        for kind in sorted(ALLOWED_KINDS))
        registry = ExtensionRegistry(records)
        for record in records:
            result = registry.resolve(record)({"kind": record.extension_kind, "value": "ok"})
            self.assertEqual({"kind": record.extension_kind, "value": "ok"}, result)

    def test_third_workflow_does_not_change_core_bytes(self):
        core_path = Path(__file__).parents[1] / "mining_research_kernel" / "core.py"
        before = core_path.read_bytes()
        registry = ExtensionRegistry((ExtensionRecord(
            "test.workflow.third", "workflow", frozenset({"synthetic"}),
            lambda project=None: {"workflow_id": "test.workflow.third", "project": project}),))
        pack = registry.resolve("test.workflow.third")()
        self.assertEqual("test.workflow.third", pack["workflow_id"])
        self.assertEqual(before, core_path.read_bytes())

    def test_provider_replacements_preserve_generic_registry_call_shape(self):
        def provider_a(request):
            return {"provider_kind": request["provider_kind"], "payload": request["payload"]}

        def provider_b(request):
            return {"provider_kind": request["provider_kind"], "payload": request["payload"]}

        kinds = ("documentation", "source", "execution", "knowledge", "transform")
        records = tuple(ExtensionRecord(f"test.{kind}.a", kind, frozenset({"synthetic"}), provider_a)
                        for kind in kinds) + tuple(
            ExtensionRecord(f"test.{kind}.b", kind, frozenset({"synthetic"}), provider_b)
            for kind in kinds)
        registry = ExtensionRegistry(records)
        for kind in kinds:
            request = {"provider_kind": kind, "payload": {"stable": True}}
            self.assertEqual(registry.resolve(f"test.{kind}.a")(request),
                             registry.resolve(f"test.{kind}.b")(request))

    def test_agent_host_replacements_persist_identical_task_results(self):
        packet = {"schema_version": 1, "type": "TaskPacket", "task_id": "task-1",
                  "project_id": "project-1", "workflow_id": "test.workflow.host",
                  "task_type": "test.task.inspect"}

        class MemoryStore:
            def __init__(self):
                self.rows = {}

            def put(self, row):
                self.rows[row["artifact_id"]] = dict(row)
                return dict(row)

            def get(self, artifact_id):
                return self.rows.get(artifact_id)

        def make_host(store):
            def submit(task):
                result = {"artifact_id": "task-1.result", "task_id": task["task_id"],
                          "workflow_id": task["workflow_id"], "status": "submitted"}
                store.put(result)
                return result
            return submit

        first_store, second_store = MemoryStore(), MemoryStore()
        registry = ExtensionRegistry((
            ExtensionRecord("test.agent_host.first", "agent_host", frozenset({"submit"}), make_host(first_store)),
            ExtensionRecord("test.agent_host.second", "agent_host", frozenset({"submit"}), make_host(second_store)),
        ))
        first = registry.resolve("test.agent_host.first")(packet)
        second = registry.resolve("test.agent_host.second")(packet)
        self.assertEqual(first, second)
        self.assertEqual(first_store.get("task-1.result"), second_store.get("task-1.result"))


if __name__ == "__main__":
    unittest.main()
