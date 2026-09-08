import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
CLI = REPO / "mining_kernel.py"
PAGE = "flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html"
HTML = """<!doctype html>
<html><head>
<title>zone list command — Itasca Software 9.6 documentation</title>
<script>var DOCUMENTATION_OPTIONS = { VERSION: '9.6.44' };</script>
</head><body><section id="zone-list-command">
<h1>zone list command</h1>
<p class="h2 rubric">Syntax</p>
<dl><dt class="sig sig-object fish" id="command:zone.list">
<span class="sig-name descname cmdname">zone </span>
<span class="sig-name descname cmdname">list </span>
</dt></dl></section></body></html>
"""


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class DocumentationCliTests(unittest.TestCase):
    def _fixture(self, root, trust_class="synthetic"):
        docs = root / "docs"
        page = docs / PAGE
        page.parent.mkdir(parents=True)
        page.write_text(HTML, encoding="utf-8")
        registration = root / "registration.json"
        registration.write_text(json.dumps({
            "schema_version": 1,
            "source_id": "host.local.flac3d.documentation",
            "root": "docs",
            "product": "flac3d",
            "document_family": "9.6",
            "document_build": "9.6.44",
            "trust_class": trust_class,
            "product_subdir": "flac3d",
            "pages": {PAGE: digest(page)},
        }), encoding="utf-8")
        return registration, page

    def _run(self, registration, *, context=None, version="9.6.44", page=PAGE,
             command="zone list"):
        args = [sys.executable, "-B", str(CLI), "documentation-check",
                "--registration", str(registration), "--page", page,
                "--product", "flac3d", "--product-version", version]
        if command is not None:
            args.extend(["--command", command])
        if context is not None:
            args.extend(["--task-context", context])
        completed = subprocess.run(args, cwd=REPO, text=True,
                                   capture_output=True, check=False)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            self.fail(f"CLI did not print JSON: {completed.stdout!r}; {completed.stderr!r}; {exc}")
        return completed, payload

    def test_synthetic_html_is_verified_only_in_synthetic_context(self):
        with tempfile.TemporaryDirectory() as td:
            registration, _ = self._fixture(Path(td))
            completed, payload = self._run(registration, context="synthetic")
            self.assertEqual(0, completed.returncode)
            self.assertEqual("SYNTHETIC_VERIFIED", payload["status"])
            self.assertTrue(payload.get("citation"))
            self.assertEqual("command_name_only", payload["coverage_scope"])
            self.assertIn("uncovered", payload)

            completed, payload = self._run(registration)
            self.assertEqual(2, completed.returncode)
            self.assertEqual("CANNOT_VERIFY", payload["status"])

    def test_wrong_version_cannot_verify(self):
        with tempfile.TemporaryDirectory() as td:
            registration, _ = self._fixture(Path(td))
            completed, payload = self._run(registration, context="synthetic",
                                           version="9.6.43")
            self.assertEqual(2, completed.returncode)
            self.assertEqual("CANNOT_VERIFY", payload["status"])

    def test_topic_only_and_metadata_only_registration_cannot_verify(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            registration, page = self._fixture(root)
            completed, payload = self._run(registration, context="synthetic",
                                           command=None)
            self.assertEqual(2, completed.returncode)
            self.assertEqual("CANNOT_VERIFY", payload["status"])

            metadata = {"product": "flac3d", "product_version": "9.6.44",
                        "page": PAGE, "commands": ["zone list"]}
            page.write_text(json.dumps(metadata), encoding="utf-8")
            registration_data = json.loads(registration.read_text(encoding="utf-8"))
            registration_data["pages"][PAGE] = digest(page)
            registration.write_text(json.dumps(registration_data), encoding="utf-8")
            completed, payload = self._run(registration, context="synthetic")
            self.assertEqual(2, completed.returncode)
            self.assertEqual("CANNOT_VERIFY", payload["status"])

            page.unlink()
            completed, payload = self._run(registration, context="synthetic")
            self.assertEqual(2, completed.returncode)
            self.assertEqual("CANNOT_VERIFY", payload["status"])

    def test_malformed_registration_is_json_error(self):
        with tempfile.TemporaryDirectory() as td:
            registration = Path(td) / "bad.json"
            registration.write_text("{", encoding="utf-8")
            completed, payload = self._run(registration, context="synthetic")
            self.assertEqual(2, completed.returncode)
            self.assertIn("error", payload)

    def test_check_does_not_write_or_change_host_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            registration, page = self._fixture(Path(td))
            before_registration = registration.read_bytes()
            before_page = page.read_bytes()
            before_files = sorted(p.relative_to(Path(td)).as_posix()
                                  for p in Path(td).rglob("*"))
            completed, _ = self._run(registration, context="synthetic")
            self.assertEqual(0, completed.returncode)
            self.assertEqual(before_registration, registration.read_bytes())
            self.assertEqual(before_page, page.read_bytes())
            self.assertEqual(before_files, sorted(
                p.relative_to(Path(td)).as_posix() for p in Path(td).rglob("*")))


if __name__ == "__main__":
    unittest.main()
