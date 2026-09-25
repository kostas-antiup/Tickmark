"""Branch-seeking scenarios with a real recalculation engine (Excel or LibreOffice).

The reference model has IF(B2>B3*3, B2-B3*3, 0). With B2=100 and B3=50 the fixed
+/-25% scenarios never push B2/B3 above 2.42, so only the wider branch search can
flip the IF - and expose a submission that is always 0.
"""

import importlib.util
import sys

import openpyxl
import pytest
from hamcrest import assert_that, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.cases import CaseSpec
from tickmark.evaluator import evaluate_workbook
from tickmark.recalculation import (
    ExcelRecalculator,
    LibreOfficeRecalculator,
    find_soffice,
)
from tickmark.scenarios import extract_decisions
from tickmark.workbook_audit import reachable_cells
from tickmark.workbook_reader import read_workbook

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
INPUTS = {"Model!B2": 100, "Model!B3": 50}


def _workbook(path, formula):
    book = openpyxl.Workbook()
    sheet = book.worksheets[0]
    sheet.title = "Model"
    sheet["A2"], sheet["B2"] = "Revenue", 100
    sheet["A3"], sheet["B3"] = "Threshold", 50
    sheet["B10"] = formula
    book.save(path)
    return path


def _case(tmp_path) -> CaseSpec:
    golden = _workbook(tmp_path / "golden.xlsx", "=IF(B2>B3*3,B2-B3*3,0)")
    observations = read_workbook(golden).observations
    return CaseSpec(
        case_id="branch",
        directory=tmp_path,
        instruction="",
        input_workbook=golden,
        golden_workbook=golden,
        target_cells=("Model!B10",),
        input_cells=frozenset(INPUTS),
        final_output="Model!B10",
        key_outputs=("Model!B10",),
        reference_values={"Model!B10": 0},
        reference_literals=frozenset({3.0, 0.0}),
        golden_input_values=INPUTS,
        abs_tolerance=1e-6,
        rel_tolerance=1e-6,
        input_change=None,
        reference_footprints={
            key: cells & frozenset(INPUTS)
            for key, cells in reachable_cells(observations.values(), ["Model!B10"]).items()
        },
        reference_decisions=tuple(extract_decisions(observations, ["Model!B10"])),
    )


@pytest.mark.parametrize("engine_type", ENGINES)
def test_when_a_branch_is_never_taken_at_base_then_the_search_still_exposes_it(
    tmp_path, engine_type
) -> None:
    with given() as context:
        context.case = _case(tmp_path)
        context.workbook = _workbook(tmp_path / "always_zero.xlsx", "=B2*0")

    with when(), engine_type() as engine:
        context.report = evaluate_workbook(context.case, context.workbook, engine)

    with then():
        assert_that(context.report.correct, equal_to(True))
        check = context.report.checks["perturbation_check"]
        assert_that(check.passed, equal_to(False))
        assert_that(check.detail, contains_string("branch-seeking"))
        assert_that(check.detail, contains_string("Diverged under: branch-search"))
        coverage = context.report.branch_coverage
        assert coverage is not None
        assert_that(coverage["tested_both_ways"], equal_to(1))


@pytest.mark.parametrize("engine_type", ENGINES)
def test_when_a_rewrite_is_equivalent_on_both_branches_then_it_passes(
    tmp_path, engine_type
) -> None:
    with given() as context:
        context.case = _case(tmp_path)
        context.workbook = _workbook(tmp_path / "rewrite.xlsx", "=MAX(0,B2-3*B3)")

    with when(), engine_type() as engine:
        context.report = evaluate_workbook(context.case, context.workbook, engine)

    with then():
        assert_that(context.report.checks["perturbation_check"].passed, equal_to(True))
        assert_that(context.report.passed, equal_to(True))
