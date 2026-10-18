"""Read-only parser for bounded MRK point-value CSV results."""

from __future__ import annotations

import csv
import hashlib
import io
import re
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any


MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
MAX_CELL_CHARS = 512
MAX_POINT_ID_CHARS = 200
MAX_NUMERIC_TOKEN_CHARS = 128
MAX_NUMERIC_DIGITS = 100
MIN_ADJUSTED_EXPONENT = -100
MAX_ADJUSTED_EXPONENT = 100
MIN_DECIMAL_EXPONENT = MIN_ADJUSTED_EXPONENT - (MAX_NUMERIC_DIGITS - 1)

_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def _parse_value(value_text: str) -> tuple[str, str, Decimal | None]:
    token = value_text.strip()
    if not token:
        return "MISSING", "", None
    if len(token) > MAX_NUMERIC_TOKEN_CHARS or not _NUMBER_RE.fullmatch(token):
        return "INVALID", "value is not a bounded decimal number", None
    try:
        value = Decimal(token)
    except InvalidOperation:
        return "INVALID", "value is not a decimal number", None
    if not value.is_finite():
        return "INVALID", "non-finite values are not allowed", None
    digits = value.as_tuple().digits
    significant_digits = len("".join(str(digit) for digit in digits).lstrip("0"))
    if significant_digits > MAX_NUMERIC_DIGITS:
        return "INVALID", "value exceeds 100 significant digits", None
    exponent = value.as_tuple().exponent
    if value.is_zero():
        if not MIN_DECIMAL_EXPONENT <= exponent <= MAX_ADJUSTED_EXPONENT:
            return "INVALID", "zero exponent is outside [-199, 100]", None
    elif not MIN_ADJUSTED_EXPONENT <= value.adjusted() <= MAX_ADJUSTED_EXPONENT:
        return "INVALID", "adjusted exponent is outside [-100, 100]", None
    return "VALID", str(value), value


def read_result_csv(path: str | Path, *, encoding: str = "utf-8-sig") -> dict[str, Any]:
    """Read one bounded point_id,value CSV without modifying or executing it."""
    try:
        with Path(path).open("rb") as source:
            raw = source.read(MAX_FILE_BYTES + 1)
    except (IsADirectoryError, PermissionError) as exc:
        raise ValueError("CSV source must be a readable regular file") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError(f"CSV exceeds maximum size of {MAX_FILE_BYTES} bytes")
    try:
        text = raw.decode(encoding, errors="strict")
    except (LookupError, UnicodeDecodeError) as exc:
        raise ValueError(f"CSV cannot be decoded with encoding {encoding!r}") from exc

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=",", strict=True)
    try:
        headers = next(reader)
    except StopIteration as exc:
        raise ValueError("CSV is empty; expected a header and at least one data row") from exc
    except csv.Error as exc:
        raise ValueError(f"invalid CSV header: {exc}") from exc

    if len(headers) != 2 or len(set(headers)) != len(headers):
        raise ValueError("CSV header must contain exactly two distinct columns")
    if any(len(cell) > MAX_CELL_CHARS for cell in headers):
        raise ValueError("CSV header cell exceeds maximum length")
    if set(headers) != {"point_id", "value"}:
        raise ValueError("CSV columns must be exactly point_id and value")
    point_index = headers.index("point_id")
    value_index = headers.index("value")

    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    row_occurrences: dict[str, list[int]] = {}
    previous_end_line = reader.line_num
    try:
        for record_index, cells in enumerate(reader, start=1):
            start_line = previous_end_line + 1
            end_line = reader.line_num
            previous_end_line = end_line
            if len(cells) != 2:
                raise ValueError(f"CSV record {record_index} has {len(cells)} columns; expected 2")
            if record_index > MAX_ROWS:
                raise ValueError(f"CSV exceeds maximum of {MAX_ROWS} data rows")
            if any(len(cell) > MAX_CELL_CHARS for cell in cells):
                raise ValueError(f"CSV record {record_index} contains a cell over {MAX_CELL_CHARS} characters")

            point_id = cells[point_index]
            value_text = cells[value_index]
            row: dict[str, Any] = {
                "point_id": point_id,
                "value_text": value_text,
                "value": None,
                "status": "VALID",
                "start_line": start_line,
                "end_line": end_line,
                "record_index": record_index,
            }
            row_index = len(rows)

            point_issue = None
            if not point_id or len(point_id) > MAX_POINT_ID_CHARS:
                point_issue = "point_id must contain 1 to 200 characters"
            elif point_id != point_id.strip():
                point_issue = "point_id must not have leading or trailing whitespace"
            elif any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in point_id):
                point_issue = "point_id must not contain control characters"
            if point_issue:
                row["status"] = "INVALID"
                diagnostics.append({"code": "invalid_point_id", "point_id": point_id,
                                    "row_indexes": [row_index], "detail": point_issue})
            else:
                row_occurrences.setdefault(point_id, []).append(row_index)

            if start_line != end_line:
                if row["status"] == "VALID":
                    row["status"] = "INVALID"
                diagnostics.append({"code": "multiline_record", "point_id": point_id,
                                    "row_indexes": [row_index],
                                    "detail": "data records spanning physical lines are not allowed"})
            else:
                value_status, detail, parsed = _parse_value(value_text)
                if row["status"] == "VALID":
                    row["status"] = value_status
                    row["value"] = str(parsed) if parsed is not None else None
                if value_status != "VALID":
                    diagnostics.append({"code": value_status.lower(), "point_id": point_id,
                                        "row_indexes": [row_index], "detail": detail})
            rows.append(row)
    except csv.Error as exc:
        raise ValueError(f"invalid CSV structure: {exc}") from exc

    if not rows:
        raise ValueError("CSV must contain at least one data row")

    for point_id, indexes in row_occurrences.items():
        if len(indexes) > 1:
            for index in indexes:
                rows[index]["status"] = "DUPLICATE"
                rows[index]["value"] = None
            diagnostics.append({"code": "duplicate_point_id", "point_id": point_id,
                                "row_indexes": indexes,
                                "detail": "point_id occurs in multiple data rows"})

    return {
        "format": "mrk_point_values_v1",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "encoding": encoding,
        "columns": headers,
        "row_count": len(rows),
        "rows": rows,
        "diagnostics": diagnostics,
        "limits": {"max_file_bytes": MAX_FILE_BYTES, "max_rows": MAX_ROWS},
    }


def difference(candidate_value: str, baseline_value: str) -> str:
    """Return the exact finite Decimal difference candidate minus baseline."""
    candidate_status, candidate_detail, candidate = _parse_value(candidate_value)
    baseline_status, baseline_detail, baseline = _parse_value(baseline_value)
    if candidate_status != "VALID" or candidate is None:
        raise ValueError(f"invalid candidate value: {candidate_detail or candidate_status}")
    if baseline_status != "VALID" or baseline is None:
        raise ValueError(f"invalid baseline value: {baseline_detail or baseline_status}")
    candidate_tuple = candidate.as_tuple()
    baseline_tuple = baseline.as_tuple()
    common_exponent = min(candidate_tuple.exponent, baseline_tuple.exponent)
    candidate_width = len(candidate_tuple.digits) + candidate_tuple.exponent - common_exponent
    baseline_width = len(baseline_tuple.digits) + baseline_tuple.exponent - common_exponent
    required_precision = max(candidate_width, baseline_width) + 1
    with localcontext() as context:
        context.prec = required_precision
        result = candidate - baseline
    if not result.is_finite():
        raise ValueError("difference is not finite")
    return str(result)
