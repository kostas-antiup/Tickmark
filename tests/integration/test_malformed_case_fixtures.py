from hamcrest import assert_that, equal_to, is_

from tickmark.cases import load_case
from tickmark.evaluator import evaluate_workbook
from tickmark.malformed_outputs import generate_malformed_outputs
from tickmark.recalculation import CachedValues


def test_when_all_targets_are_hardcoded_then_values_pass_but_construction_fails(tmp_path) -> None:
    case = load_case("data/cases/16_04")
    generate_malformed_outputs(case, tmp_path)
    workbook = tmp_path / "hardcoded_all.xlsx"

    report = evaluate_workbook(case, workbook, CachedValues())

    assert_that(report.correct, is_(True))
    assert_that(report.auditable, is_(False))
    assert_that(report.passed, is_(False))
    assert_that(report.scores["value_correctness"], equal_to(1.0))
    assert_that(report.scores["formula_coverage"], equal_to(0.0))
    assert_that(report.scores["traceability"], equal_to(0.0))
