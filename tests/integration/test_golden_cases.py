from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.cases import load_case
from tickmark.evaluator import evaluate_workbook
from tickmark.recalculation import CachedValues

CASES = Path(__file__).resolve().parents[2] / "data" / "cases"
CASE_DIRS = (
    sorted(p for p in CASES.iterdir() if (p / "case.json").exists()) if CASES.exists() else []
)


def test_when_case_14_07_is_loaded_then_targets_inputs_and_reference_match_case_json() -> None:
    with given() as context:
        context.directory = CASES / "14_07"

    with when():
        context.case = load_case(context.directory)

    with then():
        assert_that(len(context.case.target_cells), equal_to(20))
        assert_that(context.case.final_output, equal_to("RentRoll!G20"))
        assert_that(context.case.reference_values["RentRoll!G20"], equal_to(9080487))
        assert_that("RentRoll!C10" in context.case.input_cells, equal_to(True))
        input_change = context.case.input_change
        assert input_change is not None
        assert_that(input_change.cell, equal_to("RentRoll!C7"))


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
def test_when_golden_workbook_is_graded_then_it_passes_its_own_case(case_dir) -> None:
    with given() as context:
        context.case = load_case(case_dir)

    with when():
        context.report = evaluate_workbook(
            context.case, context.case.golden_workbook, CachedValues()
        )

    with then():
        assert_that(context.report.remarks, equal_to(()))
        assert_that(context.report.passed, equal_to(True))
