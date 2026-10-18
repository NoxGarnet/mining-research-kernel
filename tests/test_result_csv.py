from __future__ import annotations

import hashlib
import tempfile
import unittest
from decimal import Decimal, localcontext
from pathlib import Path

from mining_research_kernel.result_csv import (
    MAX_FILE_BYTES,
    MAX_ROWS,
    difference,
    read_result_csv,
)


class ResultCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_bom_crlf_chinese_reordered_columns_hash_and_read_only(self) -> None:
        content = "\ufeffvalue,point_id\r\n0.30,测点一\r\n".encode("utf-8")
        path = self.write("result.csv", content)

        result = read_result_csv(path)

        self.assertEqual(result["columns"], ["value", "point_id"])
        self.assertEqual(result["rows"][0]["point_id"], "测点一")
        self.assertEqual(result["rows"][0]["value_text"], "0.30")
        self.assertEqual(result["rows"][0]["value"], "0.30")
        self.assertEqual(result["sha256"], hashlib.sha256(content).hexdigest())
        self.assertEqual(path.read_bytes(), content)
        self.assertEqual(result["encoding"], "utf-8-sig")

    def test_physical_line_numbers_for_multiline_csv_record(self) -> None:
        path = self.write(
            "lines.csv",
            b'point_id,value\r\np1,"1\r\n2"\r\np2,3\r\n',
        )

        result = read_result_csv(path)

        self.assertEqual(
            [(row["start_line"], row["end_line"]) for row in result["rows"]],
            [(2, 3), (4, 4)],
        )
        self.assertEqual(result["rows"][0]["status"], "INVALID")
        self.assertEqual(result["rows"][1]["status"], "VALID")

    def test_missing_invalid_nonfinite_and_duplicate_rows_are_retained(self) -> None:
        path = self.write(
            "quality.csv",
            b"point_id,value\na,\nb,NaN\nc,Infinity\nd,not-a-number\nx,1\nx,2\n",
        )

        result = read_result_csv(path)

        self.assertEqual(
            [row["status"] for row in result["rows"]],
            ["MISSING", "INVALID", "INVALID", "INVALID", "DUPLICATE", "DUPLICATE"],
        )
        self.assertEqual(result["rows"][4]["value_text"], "1")
        self.assertEqual(result["rows"][5]["value_text"], "2")
        duplicate = next(item for item in result["diagnostics"] if item["code"] == "duplicate_point_id")
        self.assertEqual(duplicate["row_indexes"], [4, 5])

    def test_invalid_point_id_is_a_data_quality_diagnostic(self) -> None:
        path = self.write("ids.csv", "point_id,value\n bad ,2\n".encode())

        row = read_result_csv(path)["rows"][0]

        self.assertEqual(row["point_id"], " bad ")
        self.assertEqual(row["status"], "INVALID")

    def test_structural_csv_errors_raise_value_error(self) -> None:
        malformed_inputs = (
            b"point_id,value,extra\np,1,x\n",
            b"point_id,point_id\np,1\n",
            b"point_id,value\np,1,extra\n",
            b'point_id,value\np,"unterminated\n',
            b"point_id,value\n",
            b"point_id,value\np,1\n\n",
        )
        for content in malformed_inputs:
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    read_result_csv(self.write("bad.csv", content))

    def test_cell_and_file_byte_limits(self) -> None:
        long_cell = "x" * 513
        path = self.write("cell.csv", f"point_id,value\np,{long_cell}\n".encode())
        with self.assertRaises(ValueError):
            read_result_csv(path)

        path = self.write("large.csv", b"point_id,value\np,1\n" + b" " * MAX_FILE_BYTES)
        with self.assertRaises(ValueError):
            read_result_csv(path)

    def test_row_limit_and_maximum_row_count(self) -> None:
        accepted = "point_id,value\n" + "".join(f"p{i},1\n" for i in range(MAX_ROWS))
        result = read_result_csv(self.write("max-rows.csv", accepted.encode()))
        self.assertEqual(result["row_count"], MAX_ROWS)

        rejected = accepted + f"p{MAX_ROWS},1\n"
        with self.assertRaises(ValueError):
            read_result_csv(self.write("too-many-rows.csv", rejected.encode()))

    def test_numeric_token_precision_and_exponent_bounds(self) -> None:
        accepted_100_digits = "9" * 100
        content = (
            "point_id,value\n"
            f"a,{accepted_100_digits}\n"
            "b,1e100\n"
            "c,1e-100\n"
            f"d,{'9' * 101}\n"
            "e,1e101\n"
            "f,1e-101\n"
            f"g,{'1' * 129}\n"
            "h,0e999999999\n"
        )

        rows = read_result_csv(self.write("numeric-bounds.csv", content.encode()))["rows"]

        self.assertEqual([row["status"] for row in rows[:3]], ["VALID"] * 3)
        self.assertEqual([row["status"] for row in rows[3:]], ["INVALID"] * 5)

    def test_explicit_encoding_and_decode_failures(self) -> None:
        path = self.write("latin.csv", "point_id,value\ncafé,1\n".encode("cp1252"))
        self.assertEqual(read_result_csv(path, encoding="cp1252")["rows"][0]["point_id"], "café")
        with self.assertRaises(ValueError):
            read_result_csv(path)
        with self.assertRaises(ValueError):
            read_result_csv(path, encoding="unknown-encoding")

        directory = self.root / "directory"
        directory.mkdir()
        with self.assertRaises(ValueError):
            read_result_csv(directory)

    def test_difference_is_exact_for_decimal_and_long_coefficients(self) -> None:
        self.assertEqual(difference("0.3", "0.1"), "0.2")
        self.assertEqual(
            difference("123456789012345678901234567890.1", "0.1"),
            "123456789012345678901234567890.0",
        )

    def test_difference_uses_precision_for_full_allowed_exponent_span(self) -> None:
        low_coefficient = "1234567890" * 10
        low_value = f"{low_coefficient[0]}.{low_coefficient[1:]}e-100"

        actual = difference("1e100", low_value)

        with localcontext() as context:
            context.prec = 512
            expected = Decimal("1e100") - Decimal(low_value)
        self.assertEqual(Decimal(actual), expected)
        self.assertNotEqual(Decimal(actual), Decimal("1e100"))

    def test_difference_can_exceed_input_adjusted_exponent_range(self) -> None:
        self.assertEqual(difference("9e100", "-9e100"), "1.8E+101")

    def test_difference_rejects_extreme_zero_quantum_and_invalid_numbers(self) -> None:
        with self.assertRaises(ValueError):
            difference("0e999999999", "1")
        with self.assertRaises(ValueError):
            difference("1", "Infinity")
        with self.assertRaises(ValueError):
            difference("1e101", "1")


if __name__ == "__main__":
    unittest.main()
