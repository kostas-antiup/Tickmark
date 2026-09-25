from hamcrest import assert_that, contains_string, equal_to, is_not
from tests.shared.givenpy import given, then, when

from tickmark.benchmark_run import RunRecord, grader_totals
from tickmark.report_html import write_html_report

ALL_PASS = {
    "value_correctness": True,
    "formula_coverage": True,
    "traceability": True,
    "no_unexpected_hardcoded_values": True,
    "no_fake_formulas": True,
    "input_change_check": True,
    "perturbation_check": True,
}


def _record(agent, case_id, outcome, family="14_re_dcf", checks=None, remarks=(), baselines=None):
    graded = outcome not in ("pending", "no output", "error")
    return RunRecord(
        agent=agent,
        case_id=case_id,
        status="completed" if graded else outcome,
        outcome=outcome,
        duration_seconds=12.0,
        error=None,
        scores={"value_correctness": 1.0, "formula_coverage": 1.0, "traceability": 1.0}
        if graded
        else None,
        failed_checks=[name for name, ok in (checks or {}).items() if ok is False],
        remarks=list(remarks),
        result_dir="unused",
        family=family,
        n_targets=20,
        checks=checks if graded else None,
        baselines=baselines or {},
    )


def test_when_report_is_written_then_headline_sections_and_assets_are_included(tmp_path) -> None:
    with given() as context:
        hardcoded = {**ALL_PASS, "formula_coverage": False, "perturbation_check": False}
        context.records = [
            _record("modeller", "14_07", "pass", checks=ALL_PASS),
            _record("modeller", "06_18", "pass", family="06_equity_forecast", checks=ALL_PASS),
            _record(
                "hardcoder",
                "14_07",
                "values only",
                checks=hardcoded,
                remarks=["Target cell(s) hold hardcoded values instead of formulas: G20."],
            ),
            _record("hardcoder", "06_18", "pending", family="06_equity_forecast"),
        ]

    with when():
        context.html = write_html_report(tmp_path, context.records, "excel").read_text("utf-8")

    with then():
        assert_that(context.html, contains_string("75% had the right numbers."))
        assert_that(context.html, contains_string("50% were real models."))
        for title in (
            "Right numbers vs real models",
            "Agent by agent",
            "Where agents slip",
            "Where agents do well",
            "Every case",
            "Why cases did not pass",
        ):
            assert_that(context.html, contains_string(title))
        assert_that(context.html, contains_string("Real estate DCF"))
        assert_that(context.html, contains_string("@font-face"))
        assert_that(context.html, contains_string('aria-label="AAI Labs"'))
        assert_that(context.html, contains_string("hold hardcoded values instead of formulas"))


def test_when_existing_graders_disagree_then_the_comparison_section_counts_it(tmp_path) -> None:
    with given() as context:
        both = {"spreadsheetbench": True, "sheetcopilot": True}
        context.records = [
            _record("agent", "14_07", "pass", checks=ALL_PASS, baselines=both),
            _record(
                "agent",
                "06_18",
                "values only",
                checks={**ALL_PASS, "formula_coverage": False},
                baselines=both,
            ),
            _record(
                "agent",
                "16_04",
                "pass",
                checks=ALL_PASS,
                baselines={"spreadsheetbench": True, "sheetcopilot": False},
            ),
        ]

    with when():
        context.html = write_html_report(tmp_path, context.records, "excel").read_text("utf-8")
        context.totals = grader_totals(context.records)["agent"]

    with then():
        assert_that(context.html, contains_string("Same workbooks, existing benchmarks"))
        assert_that(
            context.html,
            contains_string("<b>1</b> passed by SpreadsheetBench-style grading but not real"),
        )
        assert_that(
            context.html, contains_string("<b>1</b> real models failed by SheetCopilot-style")
        )
        assert_that(
            context.totals["spreadsheetbench"],
            equal_to({"graded": 3, "passed": 3, "accepted_not_model": 1, "rejected_real_model": 0}),
        )
        assert_that(context.totals["sheetcopilot"]["rejected_real_model"], equal_to(1))


def test_when_no_record_has_verdicts_then_the_comparison_section_is_left_out(tmp_path) -> None:
    with given() as context:
        context.records = [_record("agent", "14_07", "pass", checks=ALL_PASS)]

    with when():
        context.html = write_html_report(tmp_path, context.records, "excel").read_text("utf-8")

    with then():
        assert_that(context.html, is_not(contains_string("Same workbooks, existing benchmarks")))


def test_when_names_contain_markup_then_it_is_escaped(tmp_path) -> None:
    with given() as context:
        context.records = [_record("<script>alert(1)</script>", "14_07", "pass", checks=ALL_PASS)]

    with when():
        context.html = write_html_report(tmp_path, context.records, "excel").read_text("utf-8")

    with then():
        assert_that(context.html, is_not(contains_string("<script>alert(1)</script>")))
        assert_that(context.html, contains_string("&lt;script&gt;alert(1)&lt;/script&gt;"))


def test_when_one_domain_has_few_cases_then_a_larger_strong_domain_is_preferred(tmp_path) -> None:
    with given() as context:
        context.records = [
            _record("agent", "16_01", "pass", family="16_re_direct_cap", checks=ALL_PASS),
            *[_record("agent", f"14_0{i}", "pass", checks=ALL_PASS) for i in range(1, 10)],
            _record("agent", "14_10", "fail", checks={**ALL_PASS, "value_correctness": False}),
        ]

    with when():
        context.html = write_html_report(tmp_path, context.records, "excel").read_text("utf-8")

    with then():
        assert_that("Real estate DCF (9/10)" in context.html, equal_to(True))
