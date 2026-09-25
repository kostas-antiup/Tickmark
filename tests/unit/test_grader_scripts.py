import importlib.util
import json
import sys
from pathlib import Path

from hamcrest import assert_that, equal_to, has_item, starts_with
from tests.shared.givenpy import given, then, when

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses in the script look their module up here
    spec.loader.exec_module(module)
    return module


EXPECTED = {
    "expected_value_correctness_after_recalculation": 1.0,
    "expected_formula_coverage": 0.0,
    "expected_traceability": 0.0,
}
SCORES = {"value_correctness": 1.0, "formula_coverage": 0.0, "traceability": 0.0}


def test_when_a_malformed_workbook_passes_then_the_comparison_flags_it() -> None:
    with given() as context:
        context.compare = _script("evaluate_malformed_results")._compare_scores
        context.report = {"case_id": "14_07", "passed": True, "scores": SCORES}

    with when():
        context.mismatches, context.matches = context.compare(
            "14_07", EXPECTED, context.report, 1e-12
        )

    with then():
        assert_that(context.mismatches, has_item(starts_with("passed: got True")))
        assert_that(context.matches["value_correctness"], equal_to(True))


def test_when_a_malformed_workbook_fails_as_expected_then_nothing_is_flagged() -> None:
    with given() as context:
        context.compare = _script("evaluate_malformed_results")._compare_scores
        context.report = {"case_id": "14_07", "passed": False, "scores": SCORES}

    with when():
        context.mismatches, _ = context.compare("14_07", EXPECTED, context.report, 1e-12)

    with then():
        assert_that(context.mismatches, equal_to(()))


def test_when_reports_are_compared_then_disagreements_are_counted_per_variant(tmp_path) -> None:
    with given() as context:
        for case_id, variant, ours, sheetcopilot in (
            ("14_07", "hardcoded_all", False, True),
            ("16_04", "hardcoded_all", False, False),
            ("14_07", "golden", True, True),
        ):
            path = tmp_path / case_id / f"{variant}.excel.json"
            path.parent.mkdir(exist_ok=True)
            report = {
                "case_id": case_id,
                "engine": "excel",
                "passed": ours,
                "baselines": {
                    "spreadsheetbench": {"passed": True},
                    "sheetcopilot": {"passed": sheetcopilot},
                },
            }
            path.write_text(json.dumps(report), encoding="utf-8")
        context.script = _script("compare_graders")

    with when():
        context.groups = context.script.summarize(context.script.load_reports(tmp_path))

    with then():
        hardcoded = context.groups["hardcoded_all"]
        assert_that(hardcoded["workbooks"], equal_to(2))
        assert_that(hardcoded["ours"], equal_to(0))
        assert_that(hardcoded["spreadsheetbench"]["accepted_not_model"], equal_to(2))
        assert_that(hardcoded["sheetcopilot"]["passed"], equal_to(1))
        assert_that(context.groups["golden"]["ours"], equal_to(1))
