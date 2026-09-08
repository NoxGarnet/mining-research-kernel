import unittest

from mining_research_kernel import validate_record


def legacy_record(record_type):
    fields = {
        "Project": {
            "project_id": "p1", "domain": "mining", "project_type": "computation",
            "authority_root": "projects/p1", "entry": "START.md", "status": "draft",
            "status_scope": "fixture", "known_limits": [], "verification_gates": [],
        },
        "Asset": {
            "asset_id": "a1", "project_id": "p1", "path": "a.txt",
            "asset_type": "text", "authority": "derived", "verification_status": "CANNOT_VERIFY",
        },
        "Tool": {"tool_id": "t1", "name": "reader", "read_only": True},
        "Run": {
            "run_id": "r1", "status": "active", "current_stage": "exploration",
            "stages": {
                stage: {
                    "role": {
                        "exploration": "planning_agent", "plan": "planning_agent",
                        "execution": "execution_agent", "test": "execution_agent",
                        "acceptance": "acceptance_agent",
                    }[stage],
                    "status": "active" if stage == "exploration" else "pending",
                    "attempt_count": 0,
                }
                for stage in ("exploration", "plan", "execution", "test", "acceptance")
            },
            "history": [{"event": "run_created", "current_stage": "exploration"}],
        },
        "Verification": {"gate_id": "g1", "status": "CANNOT_VERIFY", "scope": "fixture"},
    }
    return {"schema_version": 1, **fields[record_type]}


class R0RecordValidationTests(unittest.TestCase):
    def test_automatic_selection_accepts_each_known_declared_type(self):
        cases = [(record_type, legacy_record(record_type)) for record_type in (
            "Project", "Asset", "Tool", "Run", "Verification")]
        for record_type, record in cases:
            with self.subTest(record_type=record_type):
                record["type"] = record_type
                self.assertEqual([], validate_record(record))

    def test_explicit_selection_accepts_legacy_records_without_type(self):
        for record_type in ("Project", "Asset", "Tool", "Run", "Verification"):
            with self.subTest(record_type=record_type):
                self.assertEqual([], validate_record(legacy_record(record_type), record_type))

    def test_malformed_types_and_kinds_return_diagnostics(self):
        malformed_records = [
            ({"schema_version": 1}, "missing record type"),
            ({"schema_version": 1, "type": None}, "record type must be a string"),
            ({"schema_version": 1, "type": []}, "record type must be a string"),
            ({"schema_version": 1, "type": {}}, "record type must be a string"),
            ({"schema_version": 1, "type": ""}, "record type must be a non-empty string"),
            ({"schema_version": 1, "type": "  "}, "record type must be a non-empty string"),
            ({"schema_version": 1, "type": "FutureRecord"}, "unsupported record type"),
            ({"schema_version": 1, "type": "CognitionProposal"}, "unsupported record type"),
        ]
        for record, expected_diagnostic in malformed_records:
            with self.subTest(record=record):
                errors = validate_record(record)
                self.assertTrue(any(expected_diagnostic in error for error in errors))

        malformed_kinds = (
            ([], "kind must be a string"),
            ({}, "kind must be a string"),
            ("", "kind must be a non-empty string"),
            (" ", "kind must be a non-empty string"),
            ("FutureRecord", "unsupported kind"),
            ("CognitionProposal", "unsupported kind"),
        )
        for explicit_kind, expected_diagnostic in malformed_kinds:
            with self.subTest(kind=explicit_kind):
                errors = validate_record({"schema_version": 1}, explicit_kind)
                self.assertTrue(any(expected_diagnostic in error for error in errors))

    def test_explicit_and_declared_type_mismatch_is_rejected(self):
        record = legacy_record("Project")
        record["type"] = "Asset"
        errors = validate_record(record, "Project")
        self.assertTrue(any("expected type Project" in error for error in errors))

    def test_known_explicit_kind_does_not_mask_malformed_declared_type(self):
        malformed_declared_types = (
            (None, "record type must be a string"),
            ([], "record type must be a string"),
            ({}, "record type must be a string"),
            ("", "record type must be a non-empty string"),
            ("FutureRecord", "unsupported record type"),
            ("CognitionProposal", "unsupported record type"),
        )
        for declared_type, expected_diagnostic in malformed_declared_types:
            with self.subTest(declared_type=declared_type):
                record = legacy_record("Project")
                record["type"] = declared_type
                errors = validate_record(record, "Project")
                self.assertTrue(any(expected_diagnostic in error for error in errors))

    def test_malformed_explicit_kind_is_not_ignored_by_valid_declared_type(self):
        malformed_kinds = (
            ([], "kind must be a string"), ({}, "kind must be a string"),
            (True, "kind must be a string"), (1, "kind must be a string"),
            ("", "kind must be a non-empty string"),
            (" ", "kind must be a non-empty string"),
            ("FutureRecord", "unsupported kind"),
            ("CognitionProposal", "unsupported kind"),
        )
        for explicit_kind, expected_diagnostic in malformed_kinds:
            with self.subTest(kind=explicit_kind):
                record = legacy_record("Project")
                record["type"] = "Project"
                errors = validate_record(record, explicit_kind)
                self.assertTrue(any(expected_diagnostic in error for error in errors))

    def test_known_type_selection_still_enforces_required_fields(self):
        required_fields = {
            "Project": "project_id", "Asset": "asset_id", "Tool": "tool_id",
            "Run": "run_id", "Verification": "gate_id",
        }
        for record_type, required_field in required_fields.items():
            with self.subTest(path="automatic", record_type=record_type):
                record = legacy_record(record_type)
                record["type"] = record_type
                del record[required_field]
                self.assertTrue(any(f"missing {required_field}" in error for error in validate_record(record)))
            with self.subTest(path="explicit", record_type=record_type):
                record = legacy_record(record_type)
                del record[required_field]
                errors = validate_record(record, record_type)
                self.assertTrue(any(f"missing {required_field}" in error for error in errors))

    def test_known_declared_type_with_explicit_matching_kind_remains_valid(self):
        record = legacy_record("Verification")
        record["type"] = "Verification"
        self.assertEqual([], validate_record(record, "Verification"))


if __name__ == "__main__":
    unittest.main()
