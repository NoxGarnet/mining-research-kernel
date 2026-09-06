import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
PACKAGE = ROOT / "mining_research_kernel"


class ModuleBoundaryTests(unittest.TestCase):
    def _tree(self, name):
        path = PACKAGE / name
        return path, ast.parse(path.read_text(encoding="utf-8"))

    def test_contract_package_has_no_concrete_domain_dependencies(self):
        forbidden = ("flac3d", "zotero", "itasca", "paperqa2", "llm_wiki")
        for name in ("interfaces.py", "core.py", "registry.py"):
            path, tree = self._tree(name)
            source = path.read_text(encoding="utf-8").lower()
            self.assertFalse(any(token in source for token in forbidden), path)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    modules = [alias.name for alias in node.names]
                    if isinstance(node, ast.ImportFrom) and node.module:
                        modules.append(node.module)
                    self.assertFalse(any(any(token in module.lower() for token in forbidden)
                                        for module in modules), (path, modules))

    def test_core_and_registry_only_depend_on_contract_layer_or_stdlib(self):
        allowed_internal = {"mining_research_kernel.interfaces", "mining_research_kernel.registry"}
        local_roots = {path.stem for path in ROOT.glob("*.py")}
        local_roots.update({"adapters", "providers", "workflows"})
        for name in ("core.py", "registry.py"):
            _, tree = self._tree(name)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    if node.level == 1 and node.module:
                        self.assertIn(f"mining_research_kernel.{node.module}", allowed_internal)
                    elif node.module:
                        self.assertNotIn(node.module.split(".", 1)[0], local_roots)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".", 1)[0], local_roots)

    def test_adapters_do_not_import_cli_shim(self):
        for path in (ROOT / "adapters").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            self.assertNotIn("from mining_kernel", source)
            self.assertNotIn("import mining_kernel", source)

    def test_providers_do_not_import_each_other(self):
        for path in (ROOT / "providers").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse(node.module and node.module.startswith("providers."), path)
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name.startswith("providers.") for alias in node.names), path)

    def test_package_internal_import_graph_has_no_cycles(self):
        modules = {"mining_research_kernel": PACKAGE / "__init__.py"}
        modules.update({path.stem: path for path in PACKAGE.glob("*.py") if path.name != "__init__.py"})
        qualified = {"mining_research_kernel" if name == "mining_research_kernel" else
                     f"mining_research_kernel.{name}": path for name, path in modules.items()}
        graph = {name: set() for name in qualified}
        for name, path in qualified.items():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    graph[name].update(alias.name for alias in node.names if alias.name in qualified)
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 1 and node.module:
                        target = f"mining_research_kernel.{node.module}"
                    elif node.level == 1:
                        target = "mining_research_kernel"
                    else:
                        target = node.module or ""
                    if target in qualified:
                        graph[name].add(target)

        visiting, visited = set(), set()

        def visit(module):
            if module in visiting:
                self.fail(f"package import cycle detected at {module}")
            if module in visited:
                return
            visiting.add(module)
            for dependency in graph[module]:
                visit(dependency)
            visiting.remove(module)
            visited.add(module)

        for module in graph:
            visit(module)


if __name__ == "__main__":
    unittest.main()
