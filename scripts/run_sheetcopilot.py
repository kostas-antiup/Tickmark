#!/usr/bin/env python3
"""Evaluate completed workbooks against local SheetCopilot example cases.

Examples:
    # self-test the downloaded references for a few cases
    python scripts/run_sheetcopilot.py --cases 1_BoomerangSales 2_BoomerangSales --golden

    # grade one completed workbook
    python scripts/run_sheetcopilot.py --cases 1_BoomerangSales --workbook path/to/output.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.sheetcopilot_cases import load_sheetcopilot_cases  # noqa: E402
from tickmark.sheetcopilot_evaluator import (  # noqa: E402
    evaluate_sheetcopilot_workbook,
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=ROOT / "data" / "sheetcopilot",
        help="local SheetCopilot dataset folder (default: data/sheetcopilot)",
    )
    parser.add_argument(
        "--dataset-workbook",
        default="dataset_20Samples.xlsx",
        help="task metadata workbook inside --dataset-root",
    )
    parser.add_argument(
        "--answers",
        default="task_sheet_answers_v2",
        help="reference-answer folder inside --dataset-root",
    )
    parser.add_argument(
        "--cases",
        nargs="+",
        help="SheetCopilot case ids such as 1_BoomerangSales; default is every row "
        "in --dataset-workbook",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--workbook", type=Path, help="completed workbook to grade (one case)")
    source.add_argument(
        "--golden",
        action="store_true",
        help="grade each downloaded reference workbook against its own checklist",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "sheetcopilot",
        help="folder for JSON reports (default: results/sheetcopilot)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = load_sheetcopilot_cases(
        args.dataset_root,
        dataset_workbook=args.dataset_workbook,
        answer_dir=args.answers,
        case_ids=args.cases,
    )
    if not cases:
        print("No SheetCopilot cases found.", file=sys.stderr)
        return 2
    if args.workbook and len(cases) != 1:
        print("--workbook needs exactly one --cases id.", file=sys.stderr)
        return 2

    all_passed = True
    for case in cases:
        workbooks = (
            [reference.workbook for reference in case.references]
            if args.golden
            else [args.workbook]
        )
        if not workbooks:
            print(f"{case.case_id:24} FAIL  no references found in {case.reference_dir}")
            all_passed = False
            continue
        for workbook in workbooks:
            report = evaluate_sheetcopilot_workbook(case, workbook)
            out_file = args.out / case.case_id / f"{Path(workbook).stem}.json"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
                encoding="utf-8",
            )
            passed_checks = sum(
                check["passed"]
                for reference in report.to_dict()["references"]
                for check in reference["checks"]
            )
            total_checks = sum(
                len(reference["checks"]) for reference in report.to_dict()["references"]
            )
            print(
                f"{case.case_id:24} {'PASS' if report.passed else 'FAIL'}  "
                f"matched={report.matched_reference or '-'}  "
                f"checks={passed_checks}/{total_checks}  -> {out_file}"
            )
            for remark in report.remarks:
                print(f"          - {remark}")
            all_passed &= report.passed
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
