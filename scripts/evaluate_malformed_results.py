#!/usr/bin/env python3
"""Compare malformed-workbook evaluator reports with their manifest expectations."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

EXPECTED_SCORE_KEYS = {
    "value_correctness": "expected_value_correctness_after_recalculation",
    "formula_coverage": "expected_formula_coverage",
    "traceability": "expected_traceability",
}


@dataclass(frozen=True)
class Comparison:
    case_id: str
    variant: str
    report: Path | None
    matched: bool
    mismatches: tuple[str, ...]
    score_matches: dict[str, bool | None]
    engine: str = ""


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--malformed-root",
        type=Path,
        default=ROOT / "results" / "malformed_outputs",
        help="folder containing <case>/manifest.json files",
    )
    parser.add_argument(
        "--reports-root",
        type=Path,
        default=ROOT / "results",
        help="folder containing run_benchmark.py JSON reports in <case>/<variant>.<engine>.json",
    )
    parser.add_argument(
        "--engine",
        help="only compare reports for this engine, e.g. cached, excel, libreoffice",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-12,
        help="absolute tolerance for floating-point score comparisons",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="optional JSON summary path",
    )
    parser.add_argument(
        "--max-failures",
        type=int,
        default=50,
        help="maximum failed comparisons to print (default: 50; use 0 for all)",
    )
    return parser.parse_args(argv)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_paths(malformed_root: Path) -> list[Path]:
    return sorted(malformed_root.glob("*/manifest.json"))


def _report_candidates(
    reports_root: Path, case_id: str, variant: str, engine: str | None
) -> list[Path]:
    case_root = reports_root / case_id
    pattern = f"{variant}.{engine}.json" if engine else f"{variant}.*.json"
    return sorted(case_root.glob(pattern))


def _compare_scores(
    case_id: str, expected: dict[str, Any], report: dict[str, Any], tolerance: float
) -> tuple[tuple[str, ...], dict[str, bool | None]]:
    mismatches: list[str] = []
    matches: dict[str, bool | None] = {}
    if report.get("case_id") != case_id:
        mismatches.append(f"case_id: got {report.get('case_id')}, expected {case_id}")
    if report.get("passed") is not False:
        # Every generated variant is broken on purpose; passing means a check went blind.
        mismatches.append(f"passed: got {report.get('passed')}, expected False")
    scores = report.get("scores") or {}
    for report_key, manifest_key in EXPECTED_SCORE_KEYS.items():
        actual = scores.get(report_key)
        wanted = expected.get(manifest_key)
        if actual is None:
            mismatches.append(f"{report_key}: missing in report")
            matches[report_key] = None
        elif wanted is None:
            mismatches.append(f"{manifest_key}: missing in manifest")
            matches[report_key] = None
        elif abs(float(actual) - float(wanted)) > tolerance:
            mismatches.append(f"{report_key}: got {actual}, expected {wanted}")
            matches[report_key] = False
        else:
            matches[report_key] = True
    return tuple(mismatches), matches


def compare_results(
    malformed_root: Path,
    reports_root: Path,
    *,
    engine: str | None = None,
    tolerance: float = 1e-12,
) -> list[Comparison]:
    comparisons: list[Comparison] = []
    for manifest_path in _manifest_paths(malformed_root):
        manifest = _load_json(manifest_path)
        case_id = manifest["case_id"]
        for expected in manifest["outputs"]:
            variant = expected["variant"]
            candidates = _report_candidates(reports_root, case_id, variant, engine)
            if not candidates:
                comparisons.append(
                    Comparison(
                        case_id=case_id,
                        variant=variant,
                        report=None,
                        matched=False,
                        mismatches=("missing report",),
                        score_matches={key: None for key in EXPECTED_SCORE_KEYS},
                    )
                )
                continue
            for report_path in candidates:
                report = _load_json(report_path)
                mismatches, score_matches = _compare_scores(case_id, expected, report, tolerance)
                comparisons.append(
                    Comparison(
                        case_id=case_id,
                        variant=variant,
                        report=report_path,
                        matched=not mismatches,
                        mismatches=mismatches,
                        score_matches=score_matches,
                        engine=str(report.get("engine") or report_path.stem.rsplit(".", 1)[-1]),
                    )
                )
    return comparisons


def _to_dict(item: Comparison) -> dict[str, Any]:
    return {
        "case_id": item.case_id,
        "variant": item.variant,
        "engine": item.engine,
        "report": None if item.report is None else str(item.report),
        "matched": item.matched,
        "score_matches": item.score_matches,
        "mismatches": list(item.mismatches),
    }


def _metric_summary(comparisons: list[Comparison]) -> dict[str, dict[str, int]]:
    summary = {}
    for key in EXPECTED_SCORE_KEYS:
        values = [item.score_matches[key] for item in comparisons]
        summary[key] = {
            "matched": sum(value is True for value in values),
            "failed": sum(value is False for value in values),
            "missing": sum(value is None for value in values),
            "total": len(values),
        }
    return summary


def _print_summary(comparisons: list[Comparison], max_failures: int) -> None:
    total = len(comparisons)
    passed = sum(item.matched for item in comparisons)
    missing = sum(item.report is None for item in comparisons)
    print(f"Compared {total} report(s): {passed} matched, {total - passed} failed.")
    print("Score accuracy:")
    for metric, counts in _metric_summary(comparisons).items():
        print(
            f"  {metric}: {counts['matched']}/{counts['total']} matched, "
            f"{counts['failed']} failed, {counts['missing']} missing"
        )
    if missing:
        print(f"Missing reports: {missing}")
    failures = [item for item in comparisons if not item.matched]
    shown_failures = failures if max_failures == 0 else failures[:max_failures]
    for item in shown_failures:
        if item.matched:
            continue
        location = "missing" if item.report is None else str(item.report)
        engine = f" [{item.engine}]" if item.engine else ""
        print(f"{item.case_id}/{item.variant}{engine}: {location}")
        for mismatch in item.mismatches:
            print(f"  - {mismatch}")
    hidden = len(failures) - len(shown_failures)
    if hidden:
        print(
            f"... {hidden} more failed comparison(s) not shown; pass --max-failures 0 to print all."
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.malformed_root.exists():
        print(f"Malformed root does not exist: {args.malformed_root}", file=sys.stderr)
        return 2
    if not args.reports_root.exists():
        print(f"Reports root does not exist: {args.reports_root}", file=sys.stderr)
        return 2

    comparisons = compare_results(
        args.malformed_root,
        args.reports_root,
        engine=args.engine,
        tolerance=args.tolerance,
    )
    if not comparisons:
        print(f"No manifest.json files found under {args.malformed_root}", file=sys.stderr)
        return 2

    _print_summary(comparisons, args.max_failures)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "malformed_root": str(args.malformed_root),
            "reports_root": str(args.reports_root),
            "engine": args.engine,
            "total": len(comparisons),
            "matched": sum(item.matched for item in comparisons),
            "failed": sum(not item.matched for item in comparisons),
            "score_accuracy": _metric_summary(comparisons),
            "comparisons": [_to_dict(item) for item in comparisons],
        }
        args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", "utf-8")
        print(f"Wrote {args.out}")
    return 0 if all(item.matched for item in comparisons) else 1


if __name__ == "__main__":
    raise SystemExit(main())
