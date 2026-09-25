#!/usr/bin/env python3
"""Evaluate completed workbooks against benchmark cases and write JSON reports.

Examples:
    # grade one agent-completed workbook
    python scripts/run_benchmark.py --case data/cases/14_07 --workbook out/14_07.xlsx

    # grade every generated malformed workbook
    python scripts/run_benchmark.py --case data/cases --malformed-root results/malformed_outputs

    # self-test: every case's golden workbook must pass
    python scripts/run_benchmark.py --case data/cases --golden --engine excel

Exit code: 0 every workbook passed, 1 at least one failed its checks, 2 bad arguments,
3 at least one workbook could not be graded (its report holds the error; the run goes on).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from contextlib import ExitStack
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.baselines import GRADER_LABELS  # noqa: E402
from tickmark.cases import find_case_dirs, load_case  # noqa: E402
from tickmark.evaluator import EvaluationReport, evaluate_workbook  # noqa: E402
from tickmark.recalculation import open_engine  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--case",
        nargs="+",
        type=Path,
        default=[ROOT / "data" / "cases"],
        help="case folder(s), or a folder containing case folders",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--workbook", type=Path, help="completed workbook to grade (one case)")
    source.add_argument(
        "--malformed-root",
        type=Path,
        help="grade every .xlsx under this malformed-output root, matched by parent case id",
    )
    source.add_argument(
        "--golden",
        action="store_true",
        help="grade each case's golden workbook (evaluator self-test)",
    )
    parser.add_argument(
        "--engine",
        choices=("auto", "excel", "libreoffice", "cached"),
        default="auto",
        help="auto (default): excel if available, else libreoffice, else cached; "
        "excel: Microsoft Excel via COM; libreoffice: headless LibreOffice; "
        "cached: read saved values only, skips the input-change and perturbation checks",
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="when a workbook fails the perturbation check, change each input alone to "
        "name the inputs behind the difference (slower)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results",
        help="folder for JSON reports (default: results/)",
    )
    return parser.parse_args(argv)


def _malformed_workbooks(root: Path, case_ids: set[str]) -> list[Path]:
    return sorted(
        workbook
        for workbook in root.rglob("*.xlsx")
        if workbook.parent.name in case_ids and not workbook.name.startswith("~$")
    )


def _write_report(
    case_id: str, workbook: Path, out: Path, engine_name: str, report: EvaluationReport
) -> Path:
    out_file = out / case_id / f"{workbook.stem}.{engine_name}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )
    return out_file


def _write_error(
    case_id: str, workbook: Path, out: Path, engine_name: str, error: Exception
) -> Path:
    """Report file for a workbook that could not be graded (``passed`` is null)."""

    out_file = out / case_id / f"{workbook.stem}.{engine_name}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "case_id": case_id,
        "workbook": str(workbook),
        "engine": engine_name,
        "passed": None,
        "error": f"{type(error).__name__}: {error}",
        "traceback": traceback.format_exc(),
    }
    out_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return out_file


def _print_report(case_id: str, report: EvaluationReport, out_file: Path) -> None:
    scores = report.scores
    change = report.checks["input_change_check"].passed
    perturbation = report.checks["perturbation_check"].passed
    print(
        f"{case_id:7} {'PASS' if report.passed else 'FAIL'}  "
        f"value={scores['value_correctness']:.2f} "
        f"formulas={scores['formula_coverage']:.2f} "
        f"trace={scores['traceability']:.2f} "
        f"input_change={'skipped' if change is None else change} "
        f"perturbation={'skipped' if perturbation is None else perturbation}"
        f"  -> {out_file}"
    )
    if report.baselines:
        verdicts = " · ".join(
            f"{GRADER_LABELS[name]} {'PASS' if verdict['passed'] else 'FAIL'}"
            + ("" if verdict["passed"] else f" ({verdict['mismatch_count']} cells differ)")
            for name, verdict in report.baselines.items()
        )
        print(f"          = existing benchmarks: {verdicts}")
    for remark in report.remarks:
        print(f"          - {remark}")
    for warning in report.warnings:
        print(f"          ! {warning}")


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    case_dirs = find_case_dirs(args.case)
    if not case_dirs:
        print("No case folders found.", file=sys.stderr)
        return 2
    if args.workbook and len(case_dirs) != 1:
        print("--workbook needs exactly one --case folder.", file=sys.stderr)
        return 2
    if args.malformed_root and not args.malformed_root.exists():
        print(f"--malformed-root does not exist: {args.malformed_root}", file=sys.stderr)
        return 2

    all_passed, errors = True, 0
    with ExitStack() as stack:
        engine = open_engine(args.engine, stack)
        print(f"engine: {engine.name}")
        cases = {case.case_id: case for case in (load_case(case_dir) for case_dir in case_dirs)}
        if args.malformed_root:
            workbooks = _malformed_workbooks(args.malformed_root, set(cases))
            if not workbooks:
                print(
                    f"No .xlsx files found under {args.malformed_root} for the supplied cases.",
                    file=sys.stderr,
                )
                return 2
            print(f"workbooks: {len(workbooks)}")
            jobs = [(cases[workbook.parent.name], workbook) for workbook in workbooks]
        else:
            jobs = [
                (case, case.golden_workbook if args.golden else args.workbook)
                for case in cases.values()
            ]

        for case, workbook in jobs:
            # One workbook that breaks the evaluator or the engine must not end a long run:
            # record the error in its report file and carry on with the next one.
            try:
                report = evaluate_workbook(case, workbook, engine, sensitivity=args.sensitivity)
            except Exception as error:
                errors += 1
                out_file = _write_error(case.case_id, Path(workbook), args.out, engine.name, error)
                print(f"{case.case_id:7} ERROR {type(error).__name__}: {error}  -> {out_file}")
                traceback.print_exc()
                continue
            out_file = _write_report(case.case_id, Path(workbook), args.out, engine.name, report)
            _print_report(case.case_id, report, out_file)
            all_passed &= report.passed
    if errors:
        print(f"{errors} workbook(s) could not be graded; see their ERROR lines.", file=sys.stderr)
        return 3
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
