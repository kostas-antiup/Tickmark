from hamcrest import assert_that, contains_exactly, equal_to, has_entries, is_
from tests.shared.givenpy import given, then, when

from tickmark.baselines import (
    answer_cells,
    baseline_verdicts,
    spreadsheetbench_match,
    used_range_cells,
)
from tickmark.workbook_audit import CellObservation


def test_when_values_agree_to_two_decimals_then_spreadsheetbench_accepts_them() -> None:
    with given() as context:
        context.pairs = [
            (1234.561, 1234.559, True),  # both round to 1234.56
            (1234.56, 1234.57, False),
            (47.855, 47.855000000000004, True),  # saved vs live Excel value of one cell
            (None, "", True),
            ("12.30", 12.3, True),  # numeric text is converted, as upstream
            (5, 5.0, True),
            ("Total", None, False),
        ]

    with when():
        context.results = [spreadsheetbench_match(a, b) for a, b, _ in context.pairs]

    with then():
        assert_that(context.results, equal_to([expected for *_, expected in context.pairs]))


def test_when_answer_position_lists_several_ranges_then_every_cell_is_expanded() -> None:
    with given() as context:
        context.position = "'Debt, Plan'!A1:B2,'SharedData'!C3"

    with when():
        context.cells = answer_cells(context.position)

    with then():
        assert_that(
            context.cells,
            contains_exactly(
                "Debt, Plan!A1", "Debt, Plan!B1", "Debt, Plan!A2", "Debt, Plan!B2", "SharedData!C3"
            ),
        )


def test_when_sheet_is_used_up_to_c2_then_its_used_range_starts_at_a1() -> None:
    with given() as context:
        context.observations = {
            "Model!B2": CellObservation("Model!B2", 1),
            "Model!C1": CellObservation("Model!C1", "Label"),
            "Other!Z9": CellObservation("Other!Z9", 3),
        }

    with when():
        context.cells = used_range_cells(context.observations, ["Model"])

    with then():
        assert_that(
            context.cells,
            contains_exactly(
                "Model!A1", "Model!B1", "Model!C1", "Model!A2", "Model!B2", "Model!C2"
            ),
        )


def test_when_values_match_but_a_helper_cell_is_added_then_only_sheetcopilot_objects() -> None:
    with given() as context:
        context.answer = ("M!B2", "M!B3")
        context.sheet = ("M!B2", "M!B3", "M!C3")
        context.expected = {"M!B2": 100.0, "M!B3": 120.0, "M!C3": None}
        context.actual = {"M!B2": 100.0, "M!B3": 120.004, "M!C3": 1.2}  # helper value in C3

    with when():
        context.verdicts = baseline_verdicts(
            context.answer, context.sheet, context.expected, context.actual
        )

    with then():
        assert_that(context.verdicts["spreadsheetbench"]["passed"], is_(True))
        assert_that(
            context.verdicts["sheetcopilot"],
            has_entries(passed=False, checked=3, mismatch_count=2),
        )
        assert_that(
            context.verdicts["sheetcopilot"]["mismatches"], contains_exactly("M!B3", "M!C3")
        )
