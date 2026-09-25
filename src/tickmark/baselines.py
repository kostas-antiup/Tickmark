"""Grade a workbook the way existing spreadsheet benchmarks would, for comparison.

Both graders look only at final cell values, so they cannot tell a live model from
pasted numbers. Running them on the same recalculated workbook as this benchmark
shows what they accept that an audit rejects, and the reverse.

- ``spreadsheetbench``: SpreadsheetBench's ``evaluation.py`` rule. Every cell of the
  task's ``answer_position`` must equal the golden after rounding numbers to two
  decimals; blank and empty text are equal; values of different types differ. Its
  script reads saved values, so outputs are recalculated first, as its pipeline does.
- ``sheetcopilot``: SheetCopilot's ``cells.values`` checklist rule (see
  ``sheetcopilot_evaluator``). Every cell of each task sheet's used range must match
  the golden within 1e-8; charts, pivots and formatting are not part of our cases.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from openpyxl.utils.cell import column_index_from_string, coordinate_from_string, get_column_letter
from openpyxl.utils.datetime import to_excel

from .cell_refs import cell_key, expand_reference, split_reference
from .sheetcopilot_evaluator import cell_values_match
from .workbook_audit import CellObservation

GRADERS = ("spreadsheetbench", "sheetcopilot")
GRADER_LABELS = {
    "spreadsheetbench": "SpreadsheetBench-style",
    "sheetcopilot": "SheetCopilot-style",
}
_SHOWN_MISMATCHES = 20
# Functions whose result changes on every recalculation; such cells cannot match a saved golden.
VOLATILE = re.compile(r"\b(TODAY|NOW|RAND|RANDBETWEEN)\s*\(", re.IGNORECASE)


@dataclass(frozen=True)
class BaselineVerdict:
    """One existing grader's verdict on a workbook."""

    passed: bool
    checked: int
    mismatch_count: int
    mismatches: tuple[str, ...]  # first cells that differ
    method: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def answer_cells(answer_position: str) -> tuple[str, ...]:
    """Expand ``'Sheet'!B2:G22,'Other'!A1:B3`` (SpreadsheetBench ``answer_position``)."""

    return tuple(
        dict.fromkeys(
            key for part in _split_ranges(answer_position) for key in expand_reference(part)
        )
    )


def stable_cells(
    cells: Iterable[str], observations: Mapping[str, CellObservation]
) -> tuple[str, ...]:
    """Drop cells whose golden formula is volatile (``TODAY()`` differs on every recalculation)."""

    def volatile(key: str) -> bool:
        formula = (observations[key].formula or "") if key in observations else ""
        return VOLATILE.search(formula) is not None

    return tuple(key for key in cells if not volatile(key))


def used_range_cells(
    observations: Mapping[str, CellObservation], sheets: Iterable[str]
) -> tuple[str, ...]:
    """Every cell from A1 to the last used row and column of each sheet (golden layout)."""

    cells: list[str] = []
    for sheet in dict.fromkeys(sheets):
        rows, columns = [], []
        for key in observations:
            name, address = split_reference(key)
            if name != sheet:
                continue
            column, row = coordinate_from_string(address)
            rows.append(row)
            columns.append(column_index_from_string(column))
        if not rows:
            continue
        cells.extend(
            cell_key(sheet, f"{get_column_letter(column)}{row}")
            for row in range(1, max(rows) + 1)
            for column in range(1, max(columns) + 1)
        )
    return tuple(cells)


def spreadsheetbench_match(expected: Any, actual: Any) -> bool:
    """SpreadsheetBench's ``compare_cell_value``: 2-decimal rounding, strict types."""

    expected, actual = _spreadsheetbench_value(expected), _spreadsheetbench_value(actual)
    if (expected == "" and actual is None) or (expected is None and actual == ""):
        return True
    if (expected == "" and actual == "") or (expected is None and actual is None):
        return True
    return type(expected) is type(actual) and expected == actual


def baseline_verdicts(
    answer: Sequence[str],
    sheet_cells: Sequence[str],
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Verdicts of both existing graders on ``actual`` (recalculated cell values)."""

    verdicts: dict[str, dict[str, Any]] = {}
    if answer:
        verdicts["spreadsheetbench"] = _verdict(
            answer,
            expected,
            actual,
            spreadsheetbench_match,
            "every cell of SpreadsheetBench's answer range equals the golden (2 decimals)",
        ).to_dict()
    if sheet_cells:
        verdicts["sheetcopilot"] = _verdict(
            sheet_cells,
            expected,
            actual,
            cell_values_match,
            "every cell of the task sheets equals the golden (SheetCopilot cells.values)",
        ).to_dict()
    return verdicts


def _verdict(
    cells: Sequence[str],
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    same: Any,
    method: str,
) -> BaselineVerdict:
    differing = [key for key in cells if not same(expected.get(key), actual.get(key))]
    return BaselineVerdict(
        passed=not differing,
        checked=len(cells),
        mismatch_count=len(differing),
        mismatches=tuple(differing[:_SHOWN_MISMATCHES]),
        method=method,
    )


def _spreadsheetbench_value(value: Any) -> Any:
    # Mirrors transform_value() in SpreadsheetBench's evaluation.py (bool counts as int).
    # Numbers are first cut to the 15 significant digits a saved Excel file holds: the
    # upstream script reads saved files, and a live 47.855000000000004 (saved as 47.855)
    # would otherwise round to 47.86 instead of 47.85.
    if isinstance(value, (int, float)):
        return round(float(f"{float(value):.15g}"), 2)
    if isinstance(value, datetime.time):
        return str(value)[:-3]
    if isinstance(value, datetime.datetime):
        return round(to_excel(value.replace(tzinfo=None)), 0)
    if isinstance(value, str):
        try:
            return round(float(value), 2)
        except ValueError:
            return value
    return value


def _split_ranges(text: str) -> list[str]:
    """Split on commas outside quoted sheet names."""

    parts, current, quoted = [], [], False
    for char in text:
        if char == "'":
            quoted = not quoted
        if char == "," and not quoted:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [part for part in parts if part]
