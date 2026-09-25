from pathlib import Path

import openpyxl
from hamcrest import (
    assert_that,
    close_to,
    contains_exactly,
    contains_string,
    equal_to,
    has_item,
    has_length,
    none,
    starts_with,
)
from tests.shared.givenpy import given, then, when

from tickmark.cases import CaseSpec, InputChangeCheck
from tickmark.evaluator import evaluate_workbook, perturbation_changes

BASE_INPUTS = {"Model!B2": 100, "Model!B3": 0.2}


def reference_model(inputs):
    b10 = inputs["Model!B2"] * (1 + inputs["Model!B3"])
    return {"Model!B10": b10, "Model!B11": b10 * 2}


class SimulatedEngine:
    """Recalculates with Python functions standing in for each workbook's formulas."""

    name = "simulated"

    def __init__(self, submission_model, supports_changes=True):
        self.submission_model = submission_model
        self.supports_changes = supports_changes

    def evaluate(self, workbook, cells, changes=None):
        model = reference_model if Path(workbook).name == "golden.xlsx" else self.submission_model
        values = model({**BASE_INPUTS, **(changes or {})})
        return {cell: values.get(cell) for cell in cells}


def _case(tmp_path, golden_input_values=None) -> CaseSpec:
    return CaseSpec(
        case_id="toy",
        directory=tmp_path,
        instruction="Fill Model!B10:B11 with live formulas.",
        input_workbook=tmp_path / "input.xlsx",
        golden_workbook=tmp_path / "golden.xlsx",
        target_cells=("Model!B10", "Model!B11"),
        input_cells=frozenset(BASE_INPUTS),
        final_output="Model!B11",
        key_outputs=("Model!B11",),
        reference_values={"Model!B10": 120, "Model!B11": 240},
        reference_literals=frozenset({1.0, 2.0}),
        golden_input_values=BASE_INPUTS if golden_input_values is None else golden_input_values,
        abs_tolerance=1e-6,
        rel_tolerance=1e-6,
        input_change=InputChangeCheck("Model!B2", 110, "Model!B11", 240, 264),
        reference_footprints={
            "Model!B10": frozenset(BASE_INPUTS),
            "Model!B11": frozenset(BASE_INPUTS),
        },
    )


def _submission(tmp_path, b10, b11):
    book = openpyxl.Workbook()
    sheet = book.worksheets[0]
    sheet.title = "Model"
    sheet["A2"], sheet["B2"] = "Revenue", 100
    sheet["A3"], sheet["B3"] = "Growth", 0.2
    sheet["B10"], sheet["B11"] = b10, b11
    path = tmp_path / "submission.xlsx"
    book.save(path)
    return path


def test_when_submission_is_a_live_formula_model_then_it_passes_every_check(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", "=B10*2")
        context.engine = SimulatedEngine(reference_model)

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.passed, equal_to(True))
        assert_that(
            [check.passed for check in context.report.checks.values()], equal_to([True] * 7)
        )
        assert_that(context.report.remarks, equal_to(()))
        assert_that(context.report.warnings, equal_to(()))


def test_when_final_answer_is_hardcoded_then_values_pass_but_auditability_fails(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", 240)
        context.engine = SimulatedEngine(lambda i: {**reference_model(i), "Model!B11": 240})

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.correct, equal_to(True))
        assert_that(context.report.auditable, equal_to(False))
        assert_that(context.report.scores["formula_coverage"], equal_to(0.5))
        assert_that(
            context.report.checks["no_unexpected_hardcoded_values"].cells,
            contains_exactly("Model!B11"),
        )
        assert_that(context.report.checks["input_change_check"].passed, equal_to(False))
        assert_that(
            context.report.checks["perturbation_check"].cells, contains_exactly("Model!B11")
        )


def test_when_intermediate_is_hardcoded_then_downstream_target_is_not_traceable(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, 120, "=B10*2")
        context.engine = SimulatedEngine(lambda i: {"Model!B10": 120, "Model!B11": 240})

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.scores["traceability"], equal_to(0.0))
        assert_that(context.report.final_output["traceable"], equal_to(False))
        assert_that(
            context.report.remarks,
            has_item("Formula chain broken at Model!B10 (hardcoded value); affects Model!B11."),
        )


def test_when_formula_has_no_cell_references_then_it_is_reported_as_fake(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", "=240")
        context.engine = SimulatedEngine(lambda i: {**reference_model(i), "Model!B11": 240})

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.scores["formula_coverage"], equal_to(1.0))
        assert_that(context.report.checks["no_fake_formulas"].cells, contains_exactly("Model!B11"))
        assert_that(context.report.passed, equal_to(False))


def test_when_formula_embeds_a_result_constant_then_perturbation_exposes_it(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2+20", "=B10*2")
        context.engine = SimulatedEngine(
            lambda i: {"Model!B10": i["Model!B2"] + 20, "Model!B11": (i["Model!B2"] + 20) * 2}
        )

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.scores["traceability"], equal_to(1.0))
        assert_that(context.report.correct, equal_to(True))
        assert_that(
            context.report.checks["perturbation_check"].cells,
            contains_exactly("Model!B10", "Model!B11"),
        )
        assert_that(context.report.passed, equal_to(False))
        assert_that(context.report.remarks, has_item(starts_with("Correct only for the given")))
        assert_that(context.report.warnings, has_item(starts_with("Model!B10 embeds constant")))


def test_when_formula_uses_an_unusual_but_harmless_constant_then_it_only_warns(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)*1.5/1.5", "=B10*2")
        context.engine = SimulatedEngine(reference_model)

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.passed, equal_to(True))
        assert_that(context.report.warnings, has_length(1))


def test_when_engine_cannot_recalculate_then_dynamic_checks_are_skipped(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", "=B10*2")
        context.engine = SimulatedEngine(reference_model, supports_changes=False)

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        for name in ("input_change_check", "perturbation_check"):
            check = context.report.checks[name]
            assert_that(check.passed, none())
            assert_that(check.detail, starts_with("Skipped"))
        assert_that(context.report.passed, equal_to(True))


def test_when_inputs_are_perturbed_then_switches_and_years_are_left_alone(tmp_path) -> None:
    with given() as context:
        context.case = _case(
            tmp_path,
            golden_input_values={
                "Model!B2": 100,
                "Model!B3": 0.2,
                "Model!B4": 1,
                "Model!B5": 0,
                "Model!B6": 2025,
                "Model!B7": True,
            },
        )

    with when():
        context.scenarios = {
            scenario: perturbation_changes(context.case, scenario)
            for scenario in ("up", "down", "mixed")
        }
        context.again = perturbation_changes(context.case, "mixed")

    with then():
        for changes in context.scenarios.values():
            assert_that(sorted(changes), contains_exactly("Model!B2", "Model!B3"))
        assert_that(context.scenarios["mixed"], equal_to(context.again))
        for scenario, centre in (("up", 1.15), ("down", 0.85)):
            for key, value in context.scenarios[scenario].items():
                factor = value / context.case.golden_input_values[key]
                assert_that(factor, close_to(centre, 0.1))
        for key, value in context.scenarios["mixed"].items():
            distance = abs(value / context.case.golden_input_values[key] - 1)
            assert_that(distance, close_to(0.15, 0.1))


def test_when_logic_only_fits_rising_inputs_then_the_down_scenario_catches_it(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", "=MAX(B10*2,240)")

        def floor_at_base(inputs):
            values = reference_model(inputs)
            return {**values, "Model!B11": max(values["Model!B10"] * 2, 240)}

        context.engine = SimulatedEngine(floor_at_base)

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(context.report.correct, equal_to(True))
        assert_that(context.report.checks["input_change_check"].passed, equal_to(True))
        check = context.report.checks["perturbation_check"]
        assert_that(check.cells, contains_exactly("Model!B11"))
        assert_that(check.detail, contains_string("Diverged under: down"))
        assert_that(context.report.passed, equal_to(False))


def test_when_a_formula_skips_an_input_then_the_root_cell_is_named(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*1.2", "=B10*2")  # ignores growth input B3
        context.engine = SimulatedEngine(
            lambda i: {"Model!B10": i["Model!B2"] * 1.2, "Model!B11": i["Model!B2"] * 2.4}
        )

    with when():
        context.report = evaluate_workbook(_case(tmp_path), context.workbook, context.engine)

    with then():
        assert_that(
            context.report.input_differences,
            equal_to(({"cell": "Model!B10", "missing": ["Model!B3"], "extra": []},)),
        )
        assert_that(
            context.report.warnings,
            has_item(starts_with("Model!B10 does not use Model!B3, unlike the reference model")),
        )
        assert_that(context.report.checks["perturbation_check"].passed, equal_to(False))


class SwitchEngine:
    """Reference: B11 = B10*2 only when switch B4 is 1; the submission ignores B4."""

    name = "switch-sim"
    supports_changes = True

    def evaluate(self, workbook, cells, changes=None):
        inputs = {**BASE_INPUTS, "Model!B4": 1, **(changes or {})}
        b10 = inputs["Model!B2"] * (1 + inputs["Model!B3"])
        uses_switch = Path(workbook).name == "golden.xlsx"
        b11 = b10 * 2 * (inputs["Model!B4"] if uses_switch else 1)
        values = {"Model!B10": b10, "Model!B11": b11}
        return {cell: values.get(cell) for cell in cells}


def test_when_a_formula_ignores_a_switch_then_the_switch_scenario_catches_it(tmp_path) -> None:
    with given() as context:
        context.case = _case(tmp_path, golden_input_values={**BASE_INPUTS, "Model!B4": 1})
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", "=B10*2")

    with when():
        context.report = evaluate_workbook(context.case, context.workbook, SwitchEngine())

    with then():
        check = context.report.checks["perturbation_check"]
        assert_that(check.cells, contains_exactly("Model!B11"))
        assert_that(check.detail, contains_string("Diverged under: switches"))


def test_when_sensitivity_is_on_then_the_inputs_behind_a_difference_are_named(tmp_path) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*1.2", "=B10*2")  # ignores growth input B3
        context.engine = SimulatedEngine(
            lambda i: {"Model!B10": i["Model!B2"] * 1.2, "Model!B11": i["Model!B2"] * 2.4}
        )

    with when():
        context.report = evaluate_workbook(
            _case(tmp_path), context.workbook, context.engine, sensitivity=True
        )

    with then():
        assert_that(
            context.report.sensitivity,
            equal_to(({"input": "Model!B3", "targets": ["Model!B10", "Model!B11"]},)),
        )
        assert_that(
            context.report.remarks,
            has_item(
                "Model!B10, Model!B11 diverge from the reference when Model!B3 changes alone."
            ),
        )


def test_when_one_target_ignores_an_input_then_the_remark_names_it_in_the_singular(
    tmp_path,
) -> None:
    with given() as context:
        context.workbook = _submission(tmp_path, "=B2*(1+B3)", "=B2*2.4")  # B11 ignores B3
        context.engine = SimulatedEngine(
            lambda i: {
                "Model!B10": i["Model!B2"] * (1 + i["Model!B3"]),
                "Model!B11": i["Model!B2"] * 2.4,
            }
        )

    with when():
        context.report = evaluate_workbook(
            _case(tmp_path), context.workbook, context.engine, sensitivity=True
        )

    with then():
        assert_that(
            context.report.remarks,
            has_item("Model!B11 diverges from the reference when Model!B3 changes alone."),
        )
        assert_that(
            context.report.remarks,
            has_item(
                "Correct only for the given inputs: Model!B11 stops matching the reference model "
                "when inputs change (hidden hardcoded or input-independent logic)."
            ),
        )
