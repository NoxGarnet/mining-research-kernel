import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import quote

from flac3d_project import init_project
from mining_research_kernel.project_context import project_context
from mining_research_kernel.workspace_context import workspace_context
from workspace_init import init_workspace


REPO = Path(__file__).resolve().parents[1]


def make_directory_link(link: Path, target: Path):
    """Try a symlink, then use the repository's PowerShell junction fallback."""
    try:
        link.symlink_to(target, target_is_directory=True)
        return "symlink", None
    except (OSError, NotImplementedError) as exc:
        failure = f"symlink:{exc}"
    if sys.platform != "win32":
        return None, failure
    command = (f"New-Item -ItemType Junction -Path '{str(link).replace(chr(39), chr(39) * 2)}' "
               f"-Target '{str(target).replace(chr(39), chr(39) * 2)}' | Out-Null")
    try:
        result = subprocess.run(["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
                                capture_output=True, check=False, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"junction:{exc}"
    if result.returncode == 0 and link.is_dir():
        return "junction", None
    detail = (result.stderr or result.stdout).decode("utf-8", errors="replace")[-500:]
    return None, f"junction:exit={result.returncode}: {detail}"


def remove_directory_link(link: Path, kind: str):
    if kind == "symlink" and link.is_symlink():
        link.unlink()
    elif kind == "junction" and link.exists():
        link.rmdir()


class WorkspaceStarterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=REPO)
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_init_creates_exact_three_files_and_escapes_user_text(self):
        root = self.base / "矿业 workspace"
        init_workspace(root, "roadway-1", "巷道 [支护](evil)\n指令 `x` {{PROJECT_ID}} <岩层> & 参数")
        files = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
        self.assertEqual(["AGENTS.md", "INDEX.md", "projects/roadway-1/START.md"], files)
        start = (root / "projects/roadway-1/START.md").read_text(encoding="utf-8")
        self.assertIn(r"\[支护\]\(evil\)", start)
        self.assertIn(r"\`x\`", start)
        self.assertIn(r"\{\{PROJECT\_ID\}\}", start)
        self.assertIn("&lt;岩层&gt; &amp; 参数", start)
        self.assertIn("Software and version: unknown", start)
        self.assertIn("Inputs: not yet located", start)
        self.assertNotIn("knowledge", [p.name for p in root.iterdir()])

    def test_init_protects_existing_files_nonempty_and_invalid_ids(self):
        root = self.base / "protected"
        root.mkdir()
        sentinel = root / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        for project_id in ("../escape", "Upper", "x", "a" * 65):
            with self.subTest(project_id=project_id), self.assertRaises(ValueError):
                init_workspace(root, project_id, "question")
        with self.assertRaisesRegex(ValueError, "non-empty"):
            init_workspace(root, "valid-id", "question")
        self.assertEqual("keep", sentinel.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            init_workspace(self.base / "fresh", "valid-id", "")

    def test_init_rejects_duplicate_project_and_directory_link_chain(self):
        root = self.base / "workspace"
        init_workspace(root, "first-project", "question")
        with self.assertRaises(ValueError):
            init_workspace(root, "first-project", "another")
        outside = self.base / "outside"
        outside.mkdir()
        link = self.base / "linked"
        kind, failure = make_directory_link(link, outside)
        if kind is None:
            self.skipTest(f"directory symlink/junction unavailable: {failure}")
        self.addCleanup(remove_directory_link, link, kind)
        with self.assertRaisesRegex(ValueError, "symlink or reparse"):
            init_workspace(link / "new", "valid-id", "question")
        self.assertEqual([], list(outside.iterdir()))

    def test_navigation_recognizes_only_project_entry_links_and_returns_argv(self):
        root = self.base / "workspace with spaces 雪"
        project_name = "FLAC3D 模型雪"
        (root / "projects" / project_name).mkdir(parents=True)
        (root / "projects" / project_name / "START.md").write_text("DO NOT OPEN", encoding="utf-8")
        (root / "INDEX.md").write_text(
            f"[flac](<projects/{quote(project_name)}/START.md>)\n"
            "[knowledge](knowledge/method.md)\n"
            "[web](https://example.invalid/projects/two/START.md)\n"
            "```md\n[fenced](projects/two/README.md)\n```\n"
            "[code](projects/x/notes.py)\n", encoding="utf-8")
        source = root / "projects" / project_name / "START.md"
        original = Path.open

        def guarded(path, *args, **kwargs):
            if path == source:
                raise AssertionError("project entry was opened")
            return original(path, *args, **kwargs)

        with patch.object(Path, "open", guarded):
            view = workspace_context(root)
        self.assertEqual(1, len(view["projects"]))
        candidate = view["projects"][0]
        self.assertEqual(project_name, candidate["project_id"])
        self.assertEqual("exists", candidate["existence"])
        self.assertFalse(candidate["entry_read"])
        self.assertFalse(candidate["entry_verified"])
        self.assertIn("雪", candidate["argv"][-1])
        self.assertIn("workspace with spaces", candidate["argv"][-1])
        self.assertEqual("project-context", candidate["argv"][5])
        self.assertEqual(str(root / "projects" / project_name), candidate["argv"][-1])

    def test_navigation_is_read_only_and_supports_multiple_candidates(self):
        root = self.base / "multi"
        for pid, name in (("one", "START.md"), ("PFC 项目", "README.md")):
            entry = root / "projects" / pid / name
            entry.parent.mkdir(parents=True)
            entry.write_text("private project body", encoding="utf-8")
        index = root / "INDEX.md"
        index.write_text("[one](projects/one/START.md)\n[two](<projects/PFC%20%E9%A1%B9%E7%9B%AE/README.md>)\n", encoding="utf-8")
        before = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        view = workspace_context(root)
        self.assertEqual(["one", "PFC 项目"], [row["project_id"] for row in view["projects"]])
        self.assertFalse(view["automatic_selection"])
        after = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)
        self.assertFalse((root / "research").exists())

    def test_navigation_reports_missing_malformed_truncated_and_unsafe(self):
        missing = workspace_context(self.base / "absent")
        self.assertIn("does not exist", missing["diagnostics"][0])
        root = self.base / "bad"
        root.mkdir()
        self.assertIn("INDEX.md is missing", workspace_context(root)["diagnostics"][0])
        (root / "INDEX.md").write_text("plain text with no recognized links", encoding="utf-8")
        self.assertTrue(workspace_context(root)["diagnostics"])
        (root / "INDEX.md").write_text("[outside](projects/../secret/START.md)\n", encoding="utf-8")
        self.assertEqual([], workspace_context(root)["projects"])
        (root / "INDEX.md").write_text("[x](projects/x/START.md)\n" + "a" * 200, encoding="utf-8")
        clipped = workspace_context(root, max_index_bytes=30)
        self.assertTrue(clipped["index"]["truncated"])
        self.assertTrue(any("truncated" in item for item in clipped["diagnostics"]))

    def test_candidate_directory_link_is_not_followed(self):
        root = self.base / "link-index"
        (root / "projects").mkdir(parents=True)
        outside = self.base / "external.md"
        outside.write_text("external", encoding="utf-8")
        linked = root / "projects" / "linked"
        kind, failure = make_directory_link(linked, self.base)
        if kind is None:
            self.skipTest(f"directory symlink/junction unavailable: {failure}")
        self.addCleanup(remove_directory_link, linked, kind)
        (root / "INDEX.md").write_text("[linked](projects/linked/START.md)\n", encoding="utf-8")
        row = workspace_context(root)["projects"][0]
        self.assertEqual("unsafe_path_not_followed", row["status"])
        self.assertIsNone(row["argv"])

    def test_unclosed_fences_and_malformed_links_do_not_hide_valid_links(self):
        root = self.base / "fences"
        (root / "projects" / "ok").mkdir(parents=True)
        (root / "projects" / "ok" / "START.md").write_text("entry", encoding="utf-8")
        (root / "INDEX.md").write_text(
            "[bad](http://[)\n[ok](projects/ok/START.md)\n"
            "```markdown\n[fake](projects/fake/README.md)\n", encoding="utf-8")
        view = workspace_context(root)
        self.assertEqual(["ok"], [row["project_id"] for row in view["projects"]])
        self.assertTrue(any("malformed" in item for item in view["diagnostics"]))
        bounded = "[ok](projects/ok/START.md)\n```\n" + "[fake](projects/fake/START.md)\n" * 10
        (root / "INDEX.md").write_text(bounded, encoding="utf-8")
        clipped = workspace_context(root, max_index_bytes=60)
        self.assertEqual(["ok"], [row["project_id"] for row in clipped["projects"]])

    def test_cli_argv_works_and_old_project_context_remains_compatible(self):
        root = self.base / "legacy"
        init_project(root, "legacy-project")
        view = project_context(root)
        self.assertEqual("empty", view["store_state"])
        # The existing portable project entry remains navigable without task creation.
        self.assertTrue(view["read_only"])
        env = dict(os.environ)
        env["TEMP"] = str(REPO)
        env["TMP"] = str(REPO)
        env["TMPDIR"] = str(REPO)
        cli = REPO / "mining_kernel.py"
        cli_root = self.base / "CLI 工作区 with spaces"
        initialized = subprocess.run([sys.executable, "-B", "-X", "utf8", str(cli),
                                      "init-workspace", str(cli_root), "--project-id", "cli-project",
                                      "--question", "CLI smoke question"], cwd=str(REPO), env=env,
                                     capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, initialized.returncode, initialized.stderr)
        self.assertTrue((cli_root / "projects" / "cli-project" / "START.md").is_file())
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", str(cli),
                                 "workspace-context", "--workspace-root", str(cli_root)],
                                cwd=str(REPO), env=env, capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("WorkspaceContextView", output["type"])
        self.assertEqual("cli-project", output["projects"][0]["project_id"])


if __name__ == "__main__":
    unittest.main()
