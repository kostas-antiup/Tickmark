from hamcrest import assert_that, contains_exactly, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.cell_refs import expand_reference, parse_formula


def test_when_formula_mixes_cells_and_ranges_then_they_are_split() -> None:
    with given() as context:
        context.formula = "=B2*(1+$B$3)+SUM(C1:C2)"

    with when():
        context.refs = parse_formula(context.formula, "Model")

    with then():
        assert_that(context.refs.direct, equal_to(frozenset({"Model!B2", "Model!B3"})))
        assert_that(context.refs.ranged, equal_to(frozenset({"Model!C1", "Model!C2"})))
        assert_that(context.refs.literals, contains_exactly(1.0))


def test_when_formula_references_other_sheets_then_keys_use_the_unquoted_sheet_name() -> None:
    with given() as context:
        context.formula = "='My Sheet'!A1+SUM(Other!B2:B3)"

    with when():
        context.refs = parse_formula(context.formula, "Model")

    with then():
        assert_that(context.refs.direct, equal_to(frozenset({"My Sheet!A1"})))
        assert_that(context.refs.ranged, equal_to(frozenset({"Other!B2", "Other!B3"})))


def test_when_formula_uses_whole_column_then_it_expands_within_sheet_bounds() -> None:
    with given() as context:
        context.bounds = {"Model": (3, 2)}

    with when():
        context.refs = parse_formula("=SUM(A:A)", "Model", sheet_bounds=context.bounds)

    with then():
        assert_that(context.refs.ranged, equal_to(frozenset({"Model!A1", "Model!A2", "Model!A3"})))


def test_when_formula_uses_defined_name_then_it_resolves_to_its_cell() -> None:
    with given() as context:
        context.names = {"RATE": [("Inputs", "$B$3")]}

    with when():
        context.refs = parse_formula("=B2*Rate", "Model", defined_names=context.names)

    with then():
        assert_that(context.refs.direct, equal_to(frozenset({"Model!B2", "Inputs!B3"})))


def test_when_formula_links_another_workbook_then_reference_is_unresolved() -> None:
    with given() as context:
        context.formula = "=[1]Sheet1!A1*2"

    with when():
        context.refs = parse_formula(context.formula, "Model")

    with then():
        assert_that(context.refs.unresolved, contains_exactly("[1]Sheet1!A1"))
        assert_that(context.refs.direct, equal_to(frozenset()))


def test_when_case_reference_has_quoted_sheet_then_it_expands_to_cell_keys() -> None:
    with given() as context:
        context.reference = "'M&A'!A1:B2"

    with when():
        context.keys = expand_reference(context.reference)

    with then():
        assert_that(context.keys, contains_exactly("M&A!A1", "M&A!B1", "M&A!A2", "M&A!B2"))
