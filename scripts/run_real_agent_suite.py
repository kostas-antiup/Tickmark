#!/usr/bin/env python3
"""Run a small real-agent benchmark suite and compare the graded results.

Runs the given agents (default: Codex CLI) on three representative cases and grades
them with the first available engine. Pass more agents or cases for a fuller comparison.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_agents import main as run_agents_main  # noqa: E402

DEFAULT_CASES = ["data/cases/02_01", "data/cases/06_18", "data/cases/14_07"]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", nargs="+", default=["codex"], help="agents to compare")
    parser.add_argument("--cases", nargs="+", default=DEFAULT_CASES, help="case folders to run")
    parser.add_argument("--run-id", default="real-agent-suite", help="results folder name")
    parser.add_argument(
        "--engine",
        choices=("auto", "excel", "libreoffice", "cached"),
        default="auto",
        help="recalculation engine for grading (default: auto = excel, else libreoffice)",
    )
    parser.add_argument("--rerun", action="store_true", help="redo already-graded cases")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    forwarded = [
        "--agents",
        *args.agents,
        "--cases",
        *args.cases,
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
