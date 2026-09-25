import shutil
from pathlib import Path

import openpyxl
from hamcrest import assert_that, contains_exactly, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.sheetcopilot_cases import (
    SheetCopilotCase,
    load_sheetcopilot_references,
)
from tickmark.sheetcopilot_evaluator import evaluate_sheetcopilot_workbook


def _write_workbook(path: Path, revenue: float = 120.0) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Sales"
    sheet["A1"] = "Product"
    sheet["B1"] = "Revenue"
    sheet["A2"] = "Standard"
    sheet["B2"] = revenue
    book.save(path)
    return path


def _write_reference_dir(root: Path, checklist: str) -> Path:
    reference_dir = root / "task_sheet_answers_v2" / "BoomerangSales" / "1_BoomerangSales"
    reference_dir.mkdir(parents=True)
    _write_workbook(reference_dir / "1_BoomerangSales_gt1.xlsx")
    (reference_dir / "1_BoomerangSales_gt1_check.yaml").write_text(
        checklist.lstrip(), encoding="utf-8"
    )
    return reference_dir


def _case(root: Path, reference_dir: Path) -> SheetCopilotCase:
    return SheetCopilotCase(
        case_id="1_BoomerangSales",
        sheet_name="BoomerangSales",
        task_no=1,
        context="",
        instruction="Calculate the revenue column.",
        input_workbook=root / "task_sheets" / "BoomerangSales.xlsx",
        reference_dir=reference_dir,
        references=load_sheetcopilot_references(reference_dir),
    )


def test_when_sheetcopilot_output_matches_a_reference_then_it_passes(tmp_path) -> None:
    with given() as context:
        context.reference_dir = _write_reference_dir(
            tmp_path,
            """
check_board:
  '1':
    cells:
      values: true
      formatting: false
      hyperlink: false
required_APIs:
  - Write
""",
        )
        context.case = _case(tmp_path, context.reference_dir)
        context.output = tmp_path / "output.xlsx"
        shutil.copy2(context.reference_dir / "1_BoomerangSales_gt1.xlsx", context.output)

    with when():
        context.report = evaluate_sheetcopilot_workbook(context.case, context.output)

    with then():
        assert_that(context.report.passed, equal_to(True))
        assert_that(context.report.matched_reference, equal_to("1_BoomerangSales_gt1"))
        assert_that(context.report.required_apis, contains_exactly("Write"))
        assert_that(context.report.remarks, equal_to(()))


def test_when_sheetcopilot_output_differs_from_reference_then_mismatch_is_reported(
    tmp_path,
) -> None:
    with given() as context:
        context.reference_dir = _write_reference_dir(
            tmp_path,
            """
check_board:
  '1':
    cells:
      values: true
      formatting: false
      hyperlink: false
""",
        )
        context.case = _case(tmp_path, context.reference_dir)
        context.output = _write_workbook(tmp_path / "wrong.xlsx", revenue=99.0)

    with when():
        context.report = evaluate_sheetcopilot_workbook(context.case, context.output)
        context.check = context.report.references[0].checks[0]

    with then():
        assert_that(context.report.passed, equal_to(False))
        assert_that(context.check.mismatches, contains_exactly("B2"))
        assert_that(context.report.remarks[0], contains_string("Best reference"))


def test_when_checklist_requires_unsupported_area_then_report_says_so(tmp_path) -> None:
    with given() as context:
        context.reference_dir = _write_reference_dir(
            tmp_path,
            """
check_board:
  '1':
    charts:
      title: true
""",
        )
        context.case = _case(tmp_path, context.reference_dir)
        context.output = tmp_path / "output.xlsx"
        shutil.copy2(context.reference_dir / "1_BoomerangSales_gt1.xlsx", context.output)

    with when():
        context.report = evaluate_sheetcopilot_workbook(context.case, context.output)
        context.check = context.report.references[0].checks[0]

    with then():
        assert_that(context.report.passed, equal_to(False))
        assert_that(context.check.passed, equal_to(False))
        assert_that(context.check.detail, contains_string("Unsupported SheetCopilot check"))
