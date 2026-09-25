import json
from pathlib import Path

import openpyxl
import pytest
from hamcrest import assert_that, contains_exactly, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.bluefin_cases import (
    bluefin_task_text,
    find_bluefin_task_dirs,
    load_bluefin_synthesis_case,
    load_bluefin_synthesis_cases,
)


def _write_task(root: Path, case_id: str = "TTWO_Operating_Model_DCF") -> Path:
    task = root / "tasks" / "synthesis" / case_id
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("Build the operating model.", encoding="utf-8")
    (task / "metadata.json").write_text(
        json.dumps({"task_id": "gf2_0bfe9c36", "task_name": "TTWO DCF", "n_criteria": 2}),
        encoding="utf-8",
    )
    (task / "rubric.json").write_text(
        json.dumps(
            {
                "sections": [
                    {
                        "id": "formula",
                        "name": "Formula Correctness",
                        "criteria": [{"id": "c1", "points": 1, "question": "Uses formulas"}],
                    },
                    {
                        "id": "integration",
                        "name": "Model Integration",
                        "criteria": [{"id": "c2", "points": 1, "question": "Links inputs"}],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    book = openpyxl.Workbook()
    book.active["A1"] = "Source"
    book.save(task / "input_workbook.xlsx")
    book.save(task / "sample_output.xlsx")
    return task


def test_when_bluefin_root_is_loaded_then_synthesis_cases_are_discovered(tmp_path) -> None:
    with given() as context:
        context.task = _write_task(tmp_path)

    with when():
        context.dirs = find_bluefin_task_dirs([tmp_path])
        context.cases = load_bluefin_synthesis_cases(tmp_path)

    with then():
        assert_that(context.dirs, contains_exactly(context.task))
        assert_that(
            [case.case_id for case in context.cases],
            contains_exactly("TTWO_Operating_Model_DCF"),
        )
        assert_that(context.cases[0].task_name, equal_to("TTWO DCF"))
        assert_that(context.cases[0].n_criteria, equal_to(2))
        sample = context.cases[0].sample_output
        assert sample is not None
        assert_that(sample.name, equal_to("sample_output.xlsx"))


def test_when_bluefin_case_is_missing_required_files_then_error_names_them(tmp_path) -> None:
    with given() as context:
        context.task = tmp_path / "bad_task"
        context.task.mkdir()

    with when(), pytest.raises(ValueError, match="instruction.md") as context.error:
        load_bluefin_synthesis_case(context.task)

    with then():
        assert_that(str(context.error.value), contains_string("rubric.json"))


def test_bluefin_task_text_uses_synthesis_specific_instructions(tmp_path) -> None:
    with given() as context:
        _write_task(tmp_path)
        context.case = load_bluefin_synthesis_cases(
            tmp_path, case_ids=["TTWO_Operating_Model_DCF"]
        )[0]

    with when():
        context.text = bluefin_task_text(context.case)

    with then():
        assert_that(context.text, contains_string("BlueFin Synthesis Task"))
        assert_that(context.text, contains_string("output.xlsx"))
        assert_that(context.text, contains_string("Build the operating model."))
