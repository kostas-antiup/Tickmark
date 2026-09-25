from hamcrest import assert_that, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.workbook_audit import (
    CellObservation,
    TraceBreak,
    grade_workbook,
    trace_breaks,
)


def test_when_formula_model_reaches_inputs_then_all_axes_score_one() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B2", 100),
            CellObservation("B3", 0.2),
            CellObservation("B10", 120, "=B2*(1+B3)", frozenset({"B2", "B3"})),
        ]
        context.reference_values = {"B10": 120}
        context.input_cells = ["B2", "B3"]
        context.target_cells = ["B10"]

    with when():
        context.grade = grade_workbook(
            context.observations,
            context.reference_values,
            context.input_cells,
            context.target_cells,
        )

    with then():
        assert_that(context.grade.value_correctness, equal_to(1.0))
        assert_that(context.grade.formula_coverage, equal_to(1.0))
        assert_that(context.grade.traceability, equal_to(1.0))


def test_when_correct_number_is_hardcoded_then_construction_axes_score_zero() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B2", 100),
            CellObservation("B3", 0.2),
            CellObservation("B10", 120),
        ]
        context.reference_values = {"B10": 120}
        context.input_cells = ["B2", "B3"]
        context.target_cells = ["B10"]

    with when():
        context.grade = grade_workbook(
            context.observations,
            context.reference_values,
            context.input_cells,
            context.target_cells,
        )

    with then():
        assert_that(context.grade.value_correctness, equal_to(1.0))
        assert_that(context.grade.formula_coverage, equal_to(0.0))
        assert_that(context.grade.traceability, equal_to(0.0))


def _traceability(observations, input_cells, target_cells) -> float:
    return grade_workbook(observations, {}, input_cells, target_cells).traceability


def test_when_one_range_member_is_a_hardcoded_intermediate_then_target_is_not_traceable() -> None:
    with given() as context:
        context.observations = [
            CellObservation("C7", 58),
            CellObservation("C10", 1850),
            CellObservation("C20", 1287600, "=C7*C10*12", frozenset({"C7", "C10"})),
            CellObservation("D20", 2561688),
            CellObservation(
                "G20", 3849288, "=SUM(C20:D20)", range_precedents=frozenset({"C20", "D20"})
            ),
        ]
        context.input_cells = ["C7", "C10"]

    with when():
        context.traceability = _traceability(context.observations, context.input_cells, ["G20"])

    with then():
        assert_that(context.traceability, equal_to(0.0))


def test_when_one_direct_precedent_is_hardcoded_then_target_is_not_traceable() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B2", 100),
            CellObservation("B7", 500),
            CellObservation("B10", 600, "=B2+B7", frozenset({"B2", "B7"})),
        ]
        context.input_cells = ["B2"]

    with when():
        context.traceability = _traceability(context.observations, context.input_cells, ["B10"])

    with then():
        assert_that(context.traceability, equal_to(0.0))


def test_when_range_contains_blank_and_label_cells_then_they_are_skipped() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B1", "Revenue"),
            CellObservation("B2", 100),
            CellObservation(
                "B10", 100, "=SUM(B1:B3)", range_precedents=frozenset({"B1", "B2", "B3"})
            ),
        ]
        context.input_cells = ["B2"]

    with when():
        context.traceability = _traceability(context.observations, context.input_cells, ["B10"])

    with then():
        assert_that(context.traceability, equal_to(1.0))


def test_when_formula_directly_references_an_empty_cell_then_target_is_not_traceable() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B2", 100),
            CellObservation("B10", 0, "=B2*B99", frozenset({"B2", "B99"})),
        ]
        context.input_cells = ["B2"]

    with when():
        context.traceability = _traceability(context.observations, context.input_cells, ["B10"])

    with then():
        assert_that(context.traceability, equal_to(0.0))


def test_when_formula_references_no_input_bearing_cells_then_target_is_not_traceable() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B10", 9080487, "=9080487"),
            CellObservation("B11", 0, "=SUM(B20:B21)", range_precedents=frozenset({"B20", "B21"})),
        ]
        context.input_cells = ["B2"]

    with when():
        context.traceability = _traceability(
            context.observations, context.input_cells, ["B10", "B11"]
        )

    with then():
        assert_that(context.traceability, equal_to(0.0))


def test_when_shared_intermediate_is_reached_by_two_paths_then_target_is_traceable() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B2", 100),
            CellObservation("B3", 0.2),
            CellObservation("B4", 120, "=B2*(1+B3)", frozenset({"B2", "B3"})),
            CellObservation("B5", 240, "=B4*2", frozenset({"B4"})),
            CellObservation("B6", 360, "=B4*3", frozenset({"B4"})),
            CellObservation("B10", 600, "=B5+B6", frozenset({"B5", "B6"})),
        ]
        context.input_cells = ["B2", "B3"]

    with when():
        context.traceability = _traceability(
            context.observations, context.input_cells, ["B5", "B6", "B10"]
        )

    with then():
        assert_that(context.traceability, equal_to(1.0))


def test_when_formulas_form_a_cycle_then_target_is_not_traceable() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B2", 100),
            CellObservation("B5", 0, "=B2+B6", frozenset({"B2", "B6"})),
            CellObservation("B6", 0, "=B5*2", frozenset({"B5"})),
        ]
        context.input_cells = ["B2"]

    with when():
        context.traceability = _traceability(context.observations, context.input_cells, ["B6"])

    with then():
        assert_that(context.traceability, equal_to(0.0))


def test_when_chains_break_then_each_break_reports_its_cell_and_reason() -> None:
    with given() as context:
        context.observations = [
            CellObservation("B1", "Revenue"),
            CellObservation("B2", 100),
            CellObservation("T1", 5),
            CellObservation("T2", 0, "=B2*B99", frozenset({"B2", "B99"})),
            CellObservation("T3", 9, "=9"),
            CellObservation("T4", 0, "=B1*2", frozenset({"B1"})),
            CellObservation("T5", 100, "=B2", frozenset({"B2"})),
        ]
        context.input_cells = ["B2"]

    with when():
        context.breaks = trace_breaks(
            context.observations, context.input_cells, ["T1", "T2", "T3", "T4", "T5", "T6"]
        )

    with then():
        assert_that(
            context.breaks["T1"], equal_to(frozenset({TraceBreak("T1", "hardcoded_value")}))
        )
        assert_that(context.breaks["T2"], equal_to(frozenset({TraceBreak("B99", "empty_cell")})))
        assert_that(context.breaks["T3"], equal_to(frozenset({TraceBreak("T3", "no_references")})))
        assert_that(context.breaks["T4"], equal_to(frozenset({TraceBreak("B1", "text_value")})))
        assert_that(context.breaks["T5"], equal_to(frozenset()))
        assert_that(context.breaks["T6"], equal_to(frozenset({TraceBreak("T6", "empty_cell")})))


def test_when_large_values_differ_by_rounding_noise_then_relative_tolerance_accepts_them() -> None:
    with given() as context:
        context.observations = [CellObservation("B10", 176060983.33333334)]
        context.reference_values = {"B10": 176060983.33333337}

    with when():
        context.strict = grade_workbook(
            context.observations, context.reference_values, [], ["B10"], tolerance=1e-9
        )
        context.relative = grade_workbook(
            context.observations,
            context.reference_values,
            [],
            ["B10"],
            tolerance=1e-9,
            rel_tolerance=1e-9,
        )

    with then():
        assert_that(context.strict.value_correctness, equal_to(0.0))
        assert_that(context.relative.value_correctness, equal_to(1.0))
