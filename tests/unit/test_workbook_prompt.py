from pathlib import Path

import openpyxl
import pytest
from hamcrest import assert_that, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.workbook_prompt import (
    apply_cell_edits,
    describe_workbook,
    parse_cell_edits,
)

CASE_14_07 = Path(__file__).resolve().parents[2] / "data" / "cases" / "14_07"


def test_when_workbook_is_described_then_values_labels_and_formulas_are_listed() -> None:
    with given() as context:
        context.path = CASE_14_07 / "input.xlsx"  # saved without formula results

    with when():
        context.text = describe_workbook(context.path)

    with then():
        assert_that(context.text, contains_string('Sheet "RentRoll"'))
        assert_that(context.text, contains_string("\nC7: 58\n"))
        assert_that(context.text, contains_string("\nG7: =SUM(C7:F7)\n"))
        assert_that(context.text, contains_string("B17: 'Market Rent'"))


def test_when_workbook_has_saved_results_then_they_follow_the_formula() -> None:
    with given() as context:
        context.path = CASE_14_07 / "golden.xlsx"  # saved by Excel, with results

    with when():
        context.text = describe_workbook(context.path)

    with then():
        assert_that(context.text, contains_string("\nG7: =SUM(C7:F7)  [= 320]\n"))


def test_when_reply_wraps_json_in_prose_and_fences_then_cells_are_parsed() -> None:
    with given() as context:
        context.reply = (
            'Here you go:\n```json\n{"cells": {"RentRoll!C17": "=C7*C10*12", "D17": 5}}\n```'
        )

    with when():
        context.edits = parse_cell_edits(context.reply, "RentRoll")

    with then():
        assert_that(context.edits, equal_to({"RentRoll!C17": "=C7*C10*12", "RentRoll!D17": 5}))


def test_when_reply_is_a_flat_mapping_then_it_is_accepted() -> None:
    with given() as context:
        context.reply = '{"Model!$B$10": "=B2*2"}'

    with when():
        context.edits = parse_cell_edits(context.reply, "Other")

    with then():
        assert_that(context.edits, equal_to({"Model!B10": "=B2*2"}))


@pytest.mark.parametrize(
    ("reply", "reason"),
    [
        ("I cannot do that.", "no JSON object"),
        ('{"cells": {"A1": "=1"', "no JSON object"),
        ('{"cells": {"A1": [1, 2]}}', "must be a formula string or a number"),
        ('{"cells": {"A1:B2": "=1"}}', "not a single-cell address"),
        ('{"cells": {}}', "non-empty"),
    ],
)
def test_when_reply_is_unusable_then_the_reason_is_explained(reply, reason) -> None:
    with given() as context:
        context.reply = reply

    with when():
        with pytest.raises(ValueError) as raised:
            parse_cell_edits(context.reply, "Model")

    with then():
        assert_that(str(raised.value), contains_string(reason))


def test_when_edits_are_applied_then_formulas_are_written_and_unknown_sheets_skipped(
    tmp_path,
) -> None:
    with given() as context:
        book = openpyxl.Workbook()
        book.worksheets[0].title = "Model"
        book.worksheets[0]["B2"] = 100
        context.source = tmp_path / "input.xlsx"
        book.save(context.source)
        context.target = tmp_path / "output.xlsx"

    with when():
        context.skipped = apply_cell_edits(
            context.source, {"Model!B10": "=B2*2", "Ghost!A1": 1}, context.target
        )

    with then():
        written = openpyxl.load_workbook(context.target)["Model"]
        assert_that(written["B10"].value, equal_to("=B2*2"))
        assert_that(written["B2"].value, equal_to(100))
        assert_that(context.skipped, equal_to(["Ghost!A1: sheet 'Ghost' does not exist"]))
