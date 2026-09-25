#!/usr/bin/env python3
"""Run a small real-agent benchmark suite and compare the graded results.

Runs the given agents (default: Codex CLI) on a named case set and grades them with the
first available engine: ``--set pilot`` (3 small cases, the default), ``--set hard`` (the 12
leaderboard cases) or ``--set all`` (all 35). ``--cases`` picks case folders instead.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_agents import main as run_agents_main  # noqa: E402

from tickmark.cases import CASE_SETS  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", nargs="+", default=["codex"], help="agents to compare")
    parser.add_argument(
        "--set", choices=(*CASE_SETS, "all"), default="pilot", help="named case set to run"
    )
    parser.add_argument("--cases", nargs="+", help="case folders to run instead of a set")
    parser.add_argument("--run-id", default="real-agent-suite", help="results folder name")
    parser.add_argument(
        "--engine",
        choices=("auto", "excel", "libreoffice", "cached"),
        default="auto",
        help="recalculation engine for grading (default: auto = excel, else libreoffice)",
    )
    parser.add_argument("--rerun", action="store_true", help="redo already-graded cases")
    return parser.parse_args(argv)


def _set_folders(name: str) -> list[str]:
    if name == "all":
        return ["data/cases"]
    return [f"data/cases/{case_id}" for case_id in CASE_SETS[name]]


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    forwarded = [
        "--agents",
        *args.agents,
        "--cases",
        *(args.cases or _set_folders(args.set)),
        "--run-id",
        args.run_id,
        "--engine",
        args.engine,
    ]
    if args.rerun:
        forwarded.append("--rerun")
    return run_agents_main(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())
