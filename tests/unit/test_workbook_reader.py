import openpyxl
from hamcrest import assert_that, contains_exactly, equal_to, has_item, is_not, none
from openpyxl.worksheet.formula import ArrayFormula
from tests.shared.givenpy import given, then, when

from tickmark.workbook_reader import read_workbook


def _write_workbook(path):
    book = openpyxl.Workbook()
    model = book.worksheets[0]
    model.title = "Model"
    inputs = book.create_sheet("Inputs")
    inputs["A1"] = "Growth"
    inputs["B1"] = 0.1
    model["B2"] = 100
    model["B3"] = "=B2*(1+Inputs!B1)"
    model["B4"] = "=SUM(B2:B3)"
    model["B5"] = "=[1]Other!A1"
    model["C1"] = ArrayFormula("C1:C2", "=B2:B3*2")
    book.save(path)
    return path


def test_when_workbook_is_read_then_cells_are_keyed_by_sheet_with_their_references(
    tmp_path,
) -> None:
    with given() as context:
        context.path = _write_workbook(tmp_path / "model.xlsx")

    with when():
        context.snapshot = read_workbook(context.path)

    with then():
        cells = context.snapshot.observations
        assert_that(cells["Inputs!B1"].value, equal_to(0.1))
        assert_that(cells["Inputs!A1"].formula, none())
        assert_that(cells["Model!B3"].formula, equal_to("=B2*(1+Inputs!B1)"))
        assert_that(cells["Model!B3"].precedents, equal_to(frozenset({"Model!B2", "Inputs!B1"})))
        assert_that(
            cells["Model!B4"].range_precedents, equal_to(frozenset({"Model!B2", "Model!B3"}))
        )
        assert_that(context.snapshot.literals["Model!B3"], contains_exactly(1.0))


def test_when_formula_links_another_workbook_then_it_is_reported_and_breaks_tracing(
    tmp_path,
) -> None:
    with given() as context:
        context.path = _write_workbook(tmp_path / "model.xlsx")

    with when():
        context.snapshot = read_workbook(context.path)

    with then():
        assert_that(
            context.snapshot.observations["Model!B5"].precedents,
            equal_to(frozenset({"?[1]Other!A1"})),
        )
        assert_that(
            context.snapshot.issues, has_item("Model!B5: unresolved reference(s) [1]Other!A1")
        )


def test_when_array_formula_spans_cells_then_every_covered_cell_has_the_formula(tmp_path) -> None:
    with given() as context:
        context.path = _write_workbook(tmp_path / "model.xlsx")

    with when():
        context.snapshot = read_workbook(context.path)

    with then():
        for key in ("Model!C1", "Model!C2"):
            observation = context.snapshot.observations[key]
            assert_that(observation.formula, equal_to("=B2:B3*2"))
            assert_that(observation.range_precedents, is_not(equal_to(frozenset())))
