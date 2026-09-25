"""Existing benchmarks' graders on real recalculated workbooks (Excel or LibreOffice)."""

import importlib.util
import sys
from pathlib import Path

import openpyxl
import pytest
from hamcrest import assert_that, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.cases import load_case
from tickmark.evaluator import evaluate_workbook
from tickmark.recalculation import (
    ExcelRecalculator,
    LibreOfficeRecalculator,
    find_soffice,
)

HAS_EXCEL = sys.platform == "win32" and importlib.util.find_spec("win32com") is not None
ENGINES = [
    pytest.param(
        ExcelRecalculator,
        id="excel",
        marks=[pytest.mark.excel, pytest.mark.skipif(not HAS_EXCEL, reason="needs Excel")],
    ),
    pytest.param(
        LibreOfficeRecalculator,
        id="libreoffice",
        marks=[
            pytest.mark.libreoffice,
            pytest.mark.skipif(find_soffice() is None, reason="needs LibreOffice"),
        ],
    ),
]
CASE_14_07 = Path(__file__).resolve().parents[2] / "data" / "cases" / "14_07"


def _completed(path: Path, *, data_only: bool) -> Path:
    """input.xlsx with the golden's target block: live formulas, or their values pasted."""

    golden = openpyxl.load_workbook(CASE_14_07 / "golden.xlsx", data_only=data_only)["RentRoll"]
    book = openpyxl.load_workbook(CASE_14_07 / "input.xlsx")
    for row in golden["C17:G20"]:
        for cell in row:
            book["RentRoll"][cell.coordinate] = cell.value
    book.save(path)
    return path


@pytest.mark.parametrize("engine_type", ENGINES)
def test_when_values_are_pasted_then_existing_graders_pass_what_the_audit_fails(
    tmp_path, engine_type
) -> None:
    with given() as context:
        context.case = load_case(CASE_14_07)
        context.workbook = _completed(tmp_path / "pasted.xlsx", data_only=True)

    with when(), engine_type() as engine:
        context.report = evaluate_workbook(context.case, context.workbook, engine)

    with then():
        assert_that(context.report.baselines["spreadsheetbench"]["passed"], equal_to(True))
        assert_that(context.report.baselines["sheetcopilot"]["passed"], equal_to(True))
        assert_that(context.report.correct, equal_to(True))
        assert_that(context.report.passed, equal_to(False))


@pytest.mark.parametrize("engine_type", ENGINES)
def test_when_formulas_are_live_then_every_grader_agrees(tmp_path, engine_type) -> None:
    with given() as context:
        context.case = load_case(CASE_14_07)
        context.workbook = _completed(tmp_path / "live.xlsx", data_only=False)

    with when(), engine_type() as engine:
        context.report = evaluate_workbook(context.case, context.workbook, engine)

    with then():
        assert_that(
            {name: verdict["passed"] for name, verdict in context.report.baselines.items()},
            equal_to({"spreadsheetbench": True, "sheetcopilot": True}),
        )
        assert_that(context.report.passed, equal_to(True))
