import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from providers.documentation import (
    CANNOT_VERIFY,
    SYNTHETIC_VERIFIED,
    VERIFIED,
    load_registration,
    resolve_documentation,
)


PAGE = "flac3d/zone/doc/manual/zone_manual/zone_commands/cmd_zone.list.html"
ANCHOR = "command:zone.list"


def html_page(*, family="9.6", build="9.6.44", syntax=True, heading="zone list command",
              section_id="zone-list-command", signature=True, anchor=ANCHOR):
    syntax_markup = ""
    if syntax:
        signature_markup = ""
        if signature:
            signature_markup = (
                f'<dt class="sig sig-object fish" id="{anchor}">'
                '<span class="sig-name descname cmdname">'
                '<span class="sig-name descname cmdname">z</span>'
                '<span class="sig-name descname cmdname">o</span>'
                '<span class="sig-name descname cmdname">n</span>'
                '<span class="sig-name descname cmdname">e</span>'
                '<span class="sig-name descname cmdname">list</span>'
                '</span> [optional keyword/range]</dt>'
            )
        syntax_markup = (
            f'<section id="{section_id}"><h1>{heading}</h1>'
            '<p class="h2 rubric">Syntax</p><dl>'
            f'{signature_markup}</dl></section>'
        )
    return (
        '<!doctype html><html><head>'
        f'<title>zone list command &#8212; Itasca Software {family} documentation</title>'
        f"<script>var DOCUMENTATION_OPTIONS = {{VERSION: '{build}'}};</script>"
        '</head><body>' + syntax_markup + '</body></html>'
    ).encode("utf-8")


class R1DocumentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.docs = self.base / "docs"
        self.page_path = self.docs / Path(*PAGE.split("/"))
        self.page_path.parent.mkdir(parents=True)
        self.page_path.write_bytes(html_page())
        self.registration_path = self.base / "registration.json"

    def tearDown(self):
        self.temp.cleanup()

    def register(self, *, body=None, trust_class="official_local", family="9.6",
                 build="9.6.44", page=PAGE, root="docs", digest=None, extra=None):
        if body is not None:
            self.page_path.write_bytes(body)
        body = self.page_path.read_bytes()
        data = {
            "schema_version": 1,
            "source_id": "example.docs.local",
            "root": root,
            "product": "flac3d",
            "document_family": family,
            "document_build": build,
            "trust_class": trust_class,
            "product_subdir": "flac3d",
            "pages": {page: digest or hashlib.sha256(body).hexdigest()},
        }
        if extra:
            data.update(extra)
        self.registration_path.write_text(json.dumps(data), encoding="utf-8")
        return load_registration(self.registration_path)

    def provider(self, **kwargs):
        return resolve_documentation({"provider": "local"}, registration=self.register(**kwargs))

    def verify(self, provider=None, **kwargs):
        provider = provider or self.provider()
        defaults = {"product": "flac3d", "product_version": "9.6"}
        defaults.update(kwargs)
        return provider.verify_syntax(PAGE, "zone list", **defaults)

    def test_registration_is_strict_and_relative_root_is_host_selected(self):
        source = self.register()
        self.assertEqual("docs", source.root)
        self.assertEqual(self.docs, source.root_path)
        self.assertEqual(PAGE, next(iter(source.pages)))
        original_cwd = Path.cwd()
        try:
            os.chdir(self.base.parent)
            self.assertEqual(self.docs, source.root_path)
        finally:
            os.chdir(original_cwd)
        for extra in ({"unexpected": True},):
            with self.assertRaisesRegex(ValueError, "invalid_registration"):
                self.register(extra=extra)
        self.registration_path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsupported_schema_version|fields"):
            load_registration(self.registration_path)

        self.register()
        data = json.loads(self.registration_path.read_text(encoding="utf-8"))
        data["source_id"] = "official"
        self.registration_path.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source_id_must_be_dot_namespaced"):
            load_registration(self.registration_path)

    def test_registered_html_is_verified_with_separate_citation_times(self):
        result = self.verify()
        self.assertEqual(VERIFIED, result["status"])
        self.assertEqual("exact_command_name_match", result["stop_reason"])
        self.assertEqual("command_name_only", result["coverage_scope"])
        self.assertIn("parameters", result["uncovered"])
        citation = result["citation"]
        self.assertEqual("example.docs.local", citation["source_id"])
        self.assertEqual("official_local", citation["trust_class"])
        self.assertEqual(PAGE, citation["page"])
        self.assertEqual(ANCHOR, citation["anchor"])
        self.assertEqual(hashlib.sha256(self.page_path.read_bytes()).hexdigest(), citation["sha256"])
        self.assertIsNotNone(citation["fetched_at"])
        self.assertIsNotNone(citation["checked_at"])
        self.assertIn("query_sha256", citation)

    def test_capability_stays_compatible_with_existing_schema(self):
        capability = self.provider().capability()
        allowed = {"schema_version", "type", "provider_id", "provider_kind", "source_kind",
                   "available", "host_local", "capabilities", "product_version",
                   "authorization_required", "last_checked", "diagnostics", "status"}
        self.assertTrue(set(capability).issubset(allowed))
        self.assertEqual("documentation", capability["provider_kind"])


    def test_missing_page_anchor_and_syntax_fail_closed(self):
        provider = self.provider()
        self.page_path.unlink()
        self.assertEqual("page_missing_or_unreadable", self.verify(provider)["stop_reason"])

        provider = self.provider(body=html_page())
        self.assertEqual("anchor_mismatch", self.verify(provider, anchor="command:wrong")["stop_reason"])

        provider = self.provider(body=html_page(syntax=False))
        self.assertEqual("syntax_section_missing", self.verify(provider)["stop_reason"])

    def test_wrong_family_build_product_and_unknown_target_fail_closed(self):
        self.assertEqual("document_family_mismatch",
                         self.verify(self.provider(body=html_page(family="9.5"), family="9.6"))["stop_reason"])
        self.assertEqual("document_build_mismatch",
                         self.verify(self.provider(body=html_page(build="9.6.43"), build="9.6.44"))["stop_reason"])
        self.assertEqual("target_product_mismatch",
                         self.verify(product="pfc" )["stop_reason"])
        self.assertEqual("target_product_version_mismatch",
                         self.verify(product_version="9.0")["stop_reason"])
        self.assertEqual("target_product_version_mismatch",
                         self.verify(product_version="unknown")["stop_reason"])

    def test_hash_drift_is_checked_on_every_read(self):
        provider = self.provider()
        self.page_path.write_bytes(html_page(heading="changed command"))
        result = self.verify(provider)
        self.assertEqual(CANNOT_VERIFY, result["status"])
        self.assertEqual("page_hash_drift", result["stop_reason"])

    def test_traversal_and_out_of_product_pages_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "traversal|outside_product"):
            self.register(page="flac3d/../outside.html")
        with self.assertRaisesRegex(ValueError, "outside_product"):
            self.register(page="other/page.html")

        provider = self.provider()
        result = provider.verify_syntax("flac3d/../outside.html", "zone list",
                                        product="flac3d", product_version="9.6")
        self.assertEqual("topic_path_invalid", result["stop_reason"])

    def test_filesystem_link_escape(self):
        outside_dir = self.base / "outside-docs"
        outside_page = outside_dir / "page.html"
        link_dir = self.docs / "flac3d" / "escape"
        base_resolved = self.base.resolve()
        for candidate in (outside_dir, outside_page, link_dir):
            self.assertTrue(candidate.resolve(strict=False).is_relative_to(base_resolved), candidate)
        outside_dir.mkdir()
        outside_page.write_bytes(html_page())

        link_kind = None
        link_failure = None
        try:
            try:
                os.symlink(outside_dir, link_dir, target_is_directory=True)
                link_kind = "directory_symlink"
            except (OSError, NotImplementedError) as exc:
                link_failure = f"symlink:{exc}"
            if link_kind is None and os.name == "nt":
                link_command = (
                    f"New-Item -ItemType Junction -Path '{str(link_dir).replace(chr(39), chr(39) * 2)}' "
                    f"-Target '{str(outside_dir).replace(chr(39), chr(39) * 2)}' | Out-Null"
                )
                try:
                    completed = subprocess.run(
                        ["powershell.exe", "-NoProfile", "-WindowStyle", "Hidden",
                         "-Command", link_command],
                        capture_output=True, text=True, check=False, timeout=10,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if completed.returncode == 0 and link_dir.is_dir():
                        link_kind = "directory_junction"
                    else:
                        link_failure = f"junction:exit={completed.returncode}"
                except (FileNotFoundError, OSError) as exc:
                    link_failure = f"junction:{exc}"
                except subprocess.TimeoutExpired:
                    link_failure = "junction:timeout"
            if link_kind is None:
                self.skipTest(f"filesystem_link_escape unavailable ({link_failure or 'non-Windows host'})")

            resolved_target = link_dir.resolve()
            self.assertTrue(resolved_target.is_relative_to(base_resolved))
            self.assertEqual(outside_dir.resolve(), resolved_target)
            registration = self.register(
                page="flac3d/escape/page.html",
                digest=hashlib.sha256(outside_page.read_bytes()).hexdigest(),
            )
            provider = resolve_documentation({"provider": "local"}, registration=registration)
            with patch.object(Path, "read_bytes", side_effect=AssertionError(
                    f"{link_kind} escape was read before containment check")):
                result = provider.verify_syntax("flac3d/escape/page.html", "zone list",
                                                product="flac3d", product_version="9.6")
            self.assertEqual("page_path_outside_registered_product_root", result["stop_reason"])
        finally:
            if link_dir.exists() or link_dir.is_symlink():
                resolved_target = link_dir.resolve(strict=False)
                self.assertTrue(resolved_target.is_relative_to(base_resolved))
                self.assertEqual(outside_dir.resolve(), resolved_target)
                if link_kind == "directory_symlink":
                    link_dir.unlink()
                elif link_kind == "directory_junction":
                    link_dir.rmdir()

    def test_synthetic_source_requires_synthetic_context(self):
        provider = self.provider(trust_class="synthetic")
        self.assertEqual("synthetic_source_not_for_production", self.verify(provider)["stop_reason"])
        result = self.verify(provider, task_context="synthetic")
        self.assertEqual(SYNTHETIC_VERIFIED, result["status"])
        self.assertEqual("synthetic", result["citation"]["trust_class"])

    def test_only_command_head_is_supported_and_topic_only_is_not_verification(self):
        provider = self.provider()
        result = provider.verify_syntax(PAGE, "zone list range", product="flac3d", product_version="9.6")
        self.assertEqual(CANNOT_VERIFY, result["status"])
        self.assertIn(result["stop_reason"], {"syntax_heading_mismatch", "command_signature_missing"})
        result = provider.verify_syntax(PAGE, product="flac3d", product_version="9.6")
        self.assertEqual(CANNOT_VERIFY, result["status"])
        self.assertEqual("topic_only", result["stop_reason"])

    def test_target_product_and_version_are_required_and_callbacks_cannot_register(self):
        provider = self.provider()
        self.assertEqual("target_product_required",
                         provider.verify_syntax(PAGE, "zone list", product_version="9.6")["stop_reason"])
        self.assertEqual("target_product_version_required",
                         provider.verify_syntax(PAGE, "zone list", product="flac3d")["stop_reason"])

        calls = []
        def forged(_):
            calls.append(True)
            return {"product": "flac3d", "product_version": "9.6", "topic": PAGE,
                    "commands": ["zone list"], "location": "forged"}
        unavailable = resolve_documentation({"provider": "auto", "root": "docs"},
                                            official_lookup=forged, installed_lookup=forged)
        result = unavailable.verify_syntax(PAGE, "zone list", product="flac3d", product_version="9.6")
        self.assertEqual(CANNOT_VERIFY, result["status"])
        self.assertFalse(calls)

    def test_unhashable_and_control_character_requests_fail_closed(self):
        provider = self.provider()
        for kwargs in ({"source": []}, {"anchor": {}}, {"source": "local\x00"},
                       {"anchor": "command:zone.list\x00"}):
            result = provider.verify_syntax(PAGE, "zone list", product="flac3d",
                                            product_version="9.6", **kwargs)
            self.assertEqual(CANNOT_VERIFY, result["status"])
        for topic in ("flac3d/zone\x00/page.html", "flac3d/zone:page.html"):
            result = provider.verify_syntax(topic, "zone list", product="flac3d",
                                            product_version="9.6")
            self.assertEqual(CANNOT_VERIFY, result["status"])
        result = provider.verify_syntax(PAGE, "zone\nlist", product="flac3d",
                                        product_version="9.6")
        self.assertEqual("command_invalid", result["stop_reason"])

    def test_missing_html_metadata_and_fake_navigation_do_not_verify(self):
        body = html_page().replace(b"DOCUMENTATION_OPTIONS", b"OTHER_OPTIONS")
        provider = self.provider(body=body)
        self.assertEqual("document_build_unreadable", self.verify(provider)["stop_reason"])

        body = html_page(heading="zone list 10.0 command")
        provider = self.provider(body=body)
        self.assertEqual("document_family_unreadable", self.verify(provider)["stop_reason"])

        body = html_page().replace(
            b"</head>", b"<script>var DOCUMENTATION_OPTIONS = {VERSION: '9.6.43'};</script></head>"
        )
        provider = self.provider(body=body)
        self.assertEqual("document_build_unreadable", self.verify(provider)["stop_reason"])

        body = html_page().replace(
            b"VERSION: '9.6.44'", b"VERSION: '9.6.44', OTHER: 1, VERSION: '9.6.43'"
        )
        provider = self.provider(body=body)
        self.assertEqual("document_build_unreadable", self.verify(provider)["stop_reason"])

        provider = self.provider(body=html_page(signature=False))
        self.assertEqual("command_signature_missing", self.verify(provider)["stop_reason"])

        provider = self.provider(body=html_page(heading="other prose"))
        self.assertEqual("syntax_heading_mismatch", self.verify(provider)["stop_reason"])

    def test_direct_registration_objects_still_fail_closed_on_trust_and_schema(self):
        source = self.register()
        from dataclasses import replace
        untrusted = replace(source, trust_class="untrusted")
        result = resolve_documentation({"provider": "local"}, registration=untrusted).verify_syntax(
            PAGE, "zone list", product="flac3d", product_version="9.6")
        self.assertEqual("registration_trust_class_invalid", result["stop_reason"])
        wrong_schema = replace(source, schema_version=2)
        result = resolve_documentation({"provider": "local"}, registration=wrong_schema).verify_syntax(
            PAGE, "zone list", product="flac3d", product_version="9.6")
        self.assertEqual("registration_schema_version_invalid", result["stop_reason"])


if __name__ == "__main__":
    unittest.main()
