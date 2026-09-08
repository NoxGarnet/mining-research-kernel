import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1]))

import mining_kernel
import zotero_export
from flac3d_project import init_project
from relation_map import write_artifacts
from stability import diagnose


def make_directory_link(link_dir: Path, target_dir: Path) -> tuple[str | None, str | None]:
    """Use a symlink first, then the R1 Windows junction fallback."""
    try:
        link_dir.symlink_to(target_dir, target_is_directory=True)
        return "directory_symlink", None
    except (OSError, NotImplementedError) as exc:
        failure = f"symlink:{exc}"
    if sys.platform != "win32":
        return None, failure
    link_text = str(link_dir).replace("'", "''")
    target_text = str(target_dir).replace("'", "''")
    command = (
        f"New-Item -ItemType Junction -Path '{link_text}' "
        f"-Target '{target_text}' | Out-Null"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            capture_output=True, text=True, check=False, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (FileNotFoundError, OSError) as exc:
        return None, f"junction:{exc}"
    except subprocess.TimeoutExpired:
        return None, "junction:timeout"
    if completed.returncode == 0 and link_dir.is_dir():
        return "directory_junction", None
    return None, f"junction:exit={completed.returncode}"


def remove_directory_link(link_dir: Path, link_kind: str | None) -> None:
    if link_kind == "directory_symlink" and link_dir.is_symlink():
        link_dir.unlink()
    elif link_kind == "directory_junction" and link_dir.exists():
        link_dir.rmdir()


class R6SecurityTests(unittest.TestCase):
    def test_diagnose_rejects_escape_before_hash_read(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "project"
            root.mkdir()
            outside = base / "outside.txt"
            outside.write_text("outside", encoding="utf-8")
            record = {
                "schema_version": 1,
                "type": "Project",
                "project_id": "p",
                "status": "ready",
                "assets": [{
                    "asset_id": "a",
                    "path": "../outside.txt",
                    "sha256": hashlib.sha256(b"outside").hexdigest(),
                }],
            }
            result = diagnose([record], root)
        self.assertIn("unsafe_workspace_path", {error["code"] for error in result["errors"]})
        self.assertNotIn("registered_hash_drift", {error["code"] for error in result["errors"]})

    def test_diagnose_rejects_workspace_symlink_escape(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            root = base / "project"
            root.mkdir()
            outside = base / "outside"
            outside.mkdir()
            (outside / "secret.txt").write_text("outside", encoding="utf-8")
            link = root / "link"
            link_kind, failure = make_directory_link(link, outside)
            if link_kind is None:
                self.skipTest(f"directory symlink/junction unavailable ({failure})")
            try:
                record = {
                    "schema_version": 1,
                    "type": "Project",
                    "project_id": "p",
                    "status": "ready",
                    "assets": [{"asset_id": "a", "path": "link/secret.txt"}],
                }
                result = diagnose([record], root)
            finally:
                remove_directory_link(link, link_kind)
        self.assertIn("unsafe_workspace_path", {error["code"] for error in result["errors"]})

    def test_initialization_rejects_link_before_resolve(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside"
            outside.mkdir()
            link = base / "project-link"
            link_kind, failure = make_directory_link(link, outside)
            if link_kind is None:
                self.skipTest(f"directory symlink/junction unavailable ({failure})")
            try:
                with self.assertRaisesRegex(ValueError, "symlink or junction"):
                    init_project(link, "r6_project")
                self.assertEqual([], list(outside.iterdir()))
            finally:
                remove_directory_link(link, link_kind)

    def test_cli_passes_unresolved_initialization_path_to_initializer(self):
        target = Path("linked-project")
        with patch("flac3d_project.init_project", return_value=target) as initializer:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, mining_kernel.main([
                    "init-flac3d-project", str(target), "--project-id", "r6_cli",
                ]))
        self.assertEqual(target, initializer.call_args.args[0])

    def test_explicit_external_output_is_allowed_but_linked_output_is_rejected(self):
        result = {
            "summary": {}, "ambiguities": [], "duplicates": [], "orphans": [],
            "missing_from_zotero": [], "markdown_reconciliation": {},
        }
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            external = base / "external-output"
            write_artifacts(result, external)
            self.assertTrue((external / "relation_map.json").is_file())
            linked = base / "linked-output"
            link_kind, failure = make_directory_link(linked, external)
            if link_kind is None:
                self.skipTest(f"directory symlink/junction unavailable ({failure})")
            try:
                with self.assertRaisesRegex(ValueError, "symlink or junction"):
                    write_artifacts(result, linked)
            finally:
                remove_directory_link(linked, link_kind)

    def test_zotero_output_replaces_atomically_and_rejects_linked_file(self):
        snapshot = {
            "schema_version": 1, "snapshot_type": "zotero_filtered_metadata",
            "instance_id": "a" * 64, "exported_at": "2026-01-01T00:00:00+00:00",
            "library": {"version": "1"}, "items": [],
        }
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            output = base / "snapshot.json"
            with patch.object(zotero_export, "export_snapshot", return_value=snapshot):
                self.assertIsNone(zotero_export.main(["--instance-seed", "r6", "--output", str(output)]))
            self.assertEqual(snapshot, json.loads(output.read_text(encoding="utf-8")))
            target = base / "target.json"
            target.write_text("keep", encoding="utf-8")
            linked = base / "linked.json"
            try:
                linked.symlink_to(target)
            except (OSError, NotImplementedError):
                self.skipTest("file symlinks are unavailable")
            with self.assertRaisesRegex(ValueError, "symlink or junction"):
                with patch.object(zotero_export, "export_snapshot", return_value=snapshot):
                    zotero_export.main(["--instance-seed", "r6", "--output", str(linked)])
            self.assertEqual("keep", target.read_text(encoding="utf-8"))

    def test_validate_reports_fixture_relative_paths(self):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(0, mining_kernel.main([
                "--workspace", "examples/synthetic_workspace", "validate",
            ]))
        output = json.loads(stream.getvalue())
        self.assertEqual(3, len(output))
        self.assertTrue(all(not row["errors"] for row in output))

        root = Path(__file__).parents[1]
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            self.assertEqual(2, mining_kernel.main(["--workspace", str(root), "validate"]))
        output = json.loads(stream.getvalue())
        for row in output:
            self.assertFalse(Path(row["file"]).is_absolute())
            self.assertNotIn(str(root), row["file"])
            self.assertNotIn("\\", row["file"])


if __name__ == "__main__":
    unittest.main()
