#!/usr/bin/env python3
"""Compare this benchmark's verdicts with existing benchmarks' graders on the same workbooks.

Reads evaluator reports (``run_benchmark.py`` JSON or ``run_agents.py`` report.json) and
counts, per group, how many workbooks each grader passes and where they disagree.

Examples:
    # malformed workbooks: which variants do value-only graders wrongly accept?
    python scripts/compare_graders.py --reports-root results/malformed_reports

    # an agent run, grouped by agent
    python scripts/compare_graders.py --reports-root results/runs/pilot
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.baselines import GRADER_LABELS, GRADERS  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reports-root", type=Path, required=True, help="folder of reports")
    parser.add_argument("--engine", help="only reports graded with this engine")
    parser.add_argument("--out", type=Path, help="optional JSON summary path")
    return parser.parse_args(argv)


def _group(path: Path, report: dict[str, Any]) -> str:
    """Agent name for run_agents reports, else the workbook variant (file stem sans engine)."""

    if path.name == "report.json":
        return path.parent.parent.name
    return path.stem.removesuffix(f".{report.get('engine', '')}")


def load_reports(root: Path, engine: str | None = None) -> list[tuple[str, dict[str, Any]]]:
    found = []
    for path in sorted(root.rglob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except UnicodeDecodeError, json.JSONDecodeError:
            continue
        if not isinstance(report, dict) or "baselines" not in report or "case_id" not in report:
            continue
        if engine and report.get("engine") != engine:
            continue
        found.append((_group(path, report), report))
    return found


def summarize(reports: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for group, report in reports:
        entry = groups.setdefault(
            group,
            {
                "workbooks": 0,
                "ours": 0,
                **{
                    grader: {"passed": 0, "accepted_not_model": 0, "rejected_real_model": 0}
                    for grader in GRADERS
                },
            },
        )
        ours = bool(report["passed"])
        entry["workbooks"] += 1
        entry["ours"] += ours
        for grader in GRADERS:
            verdict = report["baselines"].get(grader)
            if verdict is None:
                continue
            passed = bool(verdict["passed"])
            entry[grader]["passed"] += passed
            entry[grader]["accepted_not_model"] += passed and not ours
            entry[grader]["rejected_real_model"] += ours and not passed
    return groups


def _print_table(groups: dict[str, dict[str, Any]]) -> None:
    labels = [GRADER_LABELS[grader] for grader in GRADERS]
    print("| Group | Workbooks | " + " | ".join(labels) + " | This benchmark |")
    print("|---|---|" + "---|" * len(labels) + "---|")
    total = {"workbooks": 0, "ours": 0, **{grader: 0 for grader in GRADERS}}
    for group, entry in groups.items():
        n = entry["workbooks"]
        cells = [f"{entry[grader]['passed']}/{n}" for grader in GRADERS]
        print(f"| {group} | {n} | " + " | ".join(cells) + f" | {entry['ours']}/{n} |")
        total["workbooks"] += n
        total["ours"] += entry["ours"]
        for grader in GRADERS:
            total[grader] += entry[grader]["passed"]
    n = total["workbooks"]
    cells = [f"**{total[grader]}/{n}**" for grader in GRADERS]
    print(f"| **All** | {n} | " + " | ".join(cells) + f" | **{total['ours']}/{n}** |")
    print()
    for grader in GRADERS:
        accepted = sum(entry[grader]["accepted_not_model"] for entry in groups.values())
        rejected = sum(entry[grader]["rejected_real_model"] for entry in groups.values())
        print(
            f"{GRADER_LABELS[grader]}: passes {accepted} workbook(s) this benchmark fails, "
            f"fails {rejected} workbook(s) this benchmark passes."
        )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if not args.reports_root.exists():
        print(f"Reports root does not exist: {args.reports_root}", file=sys.stderr)
        return 2
    reports = load_reports(args.reports_root, args.engine)
    if not reports:
        print(
            f"No reports with existing-grader verdicts under {args.reports_root}", file=sys.stderr
        )
        return 2
    groups = summarize(reports)
    _print_table(groups)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(groups, indent=2) + "\n", encoding="utf-8")
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
