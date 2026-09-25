import datetime

import openpyxl
from hamcrest import assert_that, equal_to, is_
from tests.shared.givenpy import given, then, when

from tickmark.recalculation import CachedValues
from tickmark.xlsx_fast import XlsxTemplate, read_saved_values


def _workbook(path):
    book = openpyxl.Workbook()
    sheet = book.worksheets[0]
    sheet.title = "Debt Plan"
    sheet["A1"] = "Revenue"
    sheet["B1"] = 100
    sheet["B1"].number_format = "#,##0.00"
    sheet["B2"] = 0.25
    sheet["B3"] = True
    sheet["B4"] = datetime.datetime(2026, 9, 11)
    sheet["B5"] = "=B1*(1+B2)"
    sheet["B6"] = "#DIV/0!"
    book.save(path)
    return path


def test_when_inputs_are_patched_then_only_those_values_change(tmp_path) -> None:
    with given() as context:
        context.source = _workbook(tmp_path / "source.xlsx")
        context.target = tmp_path / "patched.xlsx"

    with when():
        context.written = XlsxTemplate(context.source).write(
            context.target, {"Debt Plan!B1": 110.5, "Debt Plan!B2": 0, "Missing!A1": 1}
        )

    with then():
        assert_that(context.written, is_(True))
        sheet = openpyxl.load_workbook(context.target)["Debt Plan"]
        assert_that([sheet["B1"].value, sheet["B2"].value], equal_to([110.5, 0]))
        assert_that(sheet["B1"].number_format, equal_to("#,##0.00"))  # style kept
        assert_that(sheet["B5"].value, equal_to("=B1*(1+B2)"))
        assert_that(sheet["A1"].value, equal_to("Revenue"))


def test_when_a_change_needs_openpyxl_then_nothing_is_written(tmp_path) -> None:
    with given() as context:
        context.template = XlsxTemplate(_workbook(tmp_path / "source.xlsx"))

    with when():
        context.results = {
            name: context.template.write(tmp_path / f"{name}.xlsx", changes)
            for name, changes in {
                "formula": {"Debt Plan!B5": 1},
                "missing_cell": {"Debt Plan!Z99": 1},
                "text": {"Debt Plan!B1": "one hundred"},
            }.items()
        }

    with then():
        assert_that(set(context.results.values()), equal_to({False}))
        assert_that(
            any((tmp_path / f"{name}.xlsx").exists() for name in context.results), is_(False)
        )


def test_when_saved_values_are_read_then_they_match_openpyxl(tmp_path) -> None:
    with given() as context:
        context.path = _workbook(tmp_path / "source.xlsx")
        context.cells = [f"Debt Plan!{cell}" for cell in ("A1", "B1", "B2", "B3", "B4", "B6", "C9")]

    with when():
        context.fast = read_saved_values(context.path, context.cells)

    with then():
        assert_that(context.fast, equal_to(CachedValues().evaluate(context.path, context.cells)))
        assert_that(context.fast["Debt Plan!B4"], equal_to(datetime.datetime(2026, 9, 11)))
