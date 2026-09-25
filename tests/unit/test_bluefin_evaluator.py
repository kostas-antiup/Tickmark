import json
from pathlib import Path

import openpyxl
from hamcrest import assert_that, contains_string, equal_to, none
from tests.shared.givenpy import given, then, when

from tickmark.bluefin_cases import load_bluefin_synthesis_case
from tickmark.bluefin_evaluator import (
    grade_bluefin_workbook,
    report_from_existing_bluefin_grade,
)


def _write_case(root: Path):
    task = root / "TTWO_Operating_Model_DCF"
    task.mkdir()
    (task / "instruction.md").write_text("Build the model.", encoding="utf-8")
    (task / "metadata.json").write_text(json.dumps({"n_criteria": 3}), encoding="utf-8")
    (task / "rubric.json").write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "id": "formula",
                        "name": "Formula Correctness",
                        "criteria": [
                            {"id": "c1", "points": 1, "question": "A"},
                            {"id": "c2", "points": 1, "question": "B"},
                            {"id": "c3", "points": -1, "question": "C"},
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    book = openpyxl.Workbook()
    book.active["A1"] = 1
    book.save(task / "input_workbook.xlsx")
    book.save(task / "output.xlsx")
    return load_bluefin_synthesis_case(task)


def test_when_existing_bluefin_grade_is_loaded_then_report_is_normalized(tmp_path) -> None:
    with given() as context:
        context.case = _write_case(tmp_path)
        context.reward = tmp_path / "reward.json"
        context.details = tmp_path / "grade_details.json"
        context.reward.write_text(json.dumps({"reward": 0.75}), encoding="utf-8")
        context.details.write_text(
            json.dumps(
                {
                    "score_pct": 0.75,
                    "score_int": 75,
                    "criteria_total": 3,
                    "criteria_met": 2,
                    "section_scores": {"Formula Correctness": 0.667},
                }
            ),
            encoding="utf-8",
        )

    with when():
        context.report = report_from_existing_bluefin_grade(
            context.case,
            context.case.task_dir / "output.xlsx",
            reward_path=context.reward,
            details_path=context.details,
            pass_threshold=0.8,
        )

    with then():
        assert_that(context.report.passed, equal_to(False))
        assert_that(context.report.reward, equal_to(0.75))
        assert_that(context.report.score_int, equal_to(75))
        assert_that(context.report.criteria_met, equal_to(2))
        assert_that(context.report.section_scores["Formula Correctness"], equal_to(0.667))


def test_when_bluefin_reward_only_exists_then_reward_becomes_score(tmp_path) -> None:
    with given() as context:
        context.case = _write_case(tmp_path)
        context.reward = tmp_path / "reward.json"
        context.reward.write_text(json.dumps({"reward": 0.9}), encoding="utf-8")

    with when():
        context.report = report_from_existing_bluefin_grade(
            context.case,
            context.case.task_dir / "output.xlsx",
            reward_path=context.reward,
            pass_threshold=0.8,
        )

    with then():
        assert_that(context.report.passed, equal_to(True))
        assert_that(context.report.score_pct, equal_to(0.9))
        assert_that(context.report.score_int, equal_to(90))
        assert_that(context.report.error, none())


def test_when_bluefin_code_root_is_missing_then_grading_reports_error(tmp_path) -> None:
    with given() as context:
        context.case = _write_case(tmp_path)

    with when():
        context.report = grade_bluefin_workbook(
            context.case,
            context.case.task_dir / "output.xlsx",
            code_root=tmp_path / "missing-bluefin",
            out_dir=tmp_path / "out",
            judge_model="gpt-5.4",
        )

    with then():
        assert_that(context.report.passed, none())
        assert_that(context.report.error or "", contains_string("scoring/grade.py"))
