#!/usr/bin/env python3
"""Let agents complete benchmark cases, grade their workbooks and summarise the results.

Examples:
    # list configured agents and whether each can start on this machine
    python scripts/run_agents.py --list

    # pilot: Claude Code and Gemini on two cases
    python scripts/run_agents.py --agents claude-code gemini-flash \\
        --cases data/cases/14_07 data/cases/06_18 --run-id pilot

    # all 35 cases; re-running the same --run-id resumes where it stopped
    python scripts/run_agents.py --agents gemini-flash --cases data/cases --run-id full

    # rebuild summary.md / summary.json of an existing run
    python scripts/run_agents.py --summarize results/runs/pilot

Results go to results/runs/<run-id>/<agent>/<case>/ plus summary.md and summary.json.
"""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.agents import check_agent, load_agent_table, load_agents  # noqa: E402
from tickmark.benchmark_run import (  # noqa: E402
    collect_records,
    run_benchmark,
    write_summary,
)
from tickmark.cases import find_case_dirs, load_case  # noqa: E402
from tickmark.recalculation import open_engine  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agents", nargs="+", help="agent names from the config file")
    parser.add_argument(
        "--cases",
        nargs="+",
        type=Path,
        default=[ROOT / "data" / "cases"],
        help="case folder(s) or a folder of case folders (default: all of data/cases)",
    )
    parser.add_argument("--run-id", help="results folder name (default: current time)")
    parser.add_argument(
        "--engine",
        choices=("auto", "excel", "libreoffice", "cached"),
        default="auto",
        help="recalculation engine for grading (default: auto)",
    )
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs" / "agents.toml", help="agent config"
    )
    parser.add_argument(
        "--results", type=Path, default=ROOT / "results" / "runs", help="parent results folder"
    )
    parser.add_argument(
        "--rerun", action="store_true", help="redo cases that already have a report"
    )
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="when a workbook fails the perturbation check, change each input alone to "
        "name the inputs behind the difference (slower)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="list configured agents, whether each is ready, and exit",
    )
    parser.add_argument("--summarize", type=Path, help="rewrite the summary of an existing run")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    if args.list:
        _print_agents(args.config)
        return 0

    if args.summarize:
        records = collect_records(args.summarize)
        engines = {
            json.loads(report.read_text(encoding="utf-8"))["engine"]
            for report in args.summarize.glob("*/*/report.json")
        }
        write_summary(args.summarize, records, ", ".join(sorted(engines)) or "none")
        print((args.summarize / "summary.md").read_text(encoding="utf-8"))
        return 0

    if not args.agents:
        print("Give --agents (see --list).", file=sys.stderr)
        return 2
    try:
        agents = load_agents(args.config, args.agents)
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    if not _agents_ready(args.config, args.agents):
        return 2
    case_dirs = find_case_dirs(args.cases)
    if not case_dirs:
        print("No case folders found.", file=sys.stderr)
        return 2
    run_dir = args.results / (args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)

    with ExitStack() as stack:
        engine = open_engine(args.engine, stack)
        print(
            f"run: {run_dir}  engine: {engine.name}  agents: {len(agents)}  cases: {len(case_dirs)}"
        )
        cases = [load_case(case_dir) for case_dir in case_dirs]
        run_benchmark(
            agents, cases, run_dir, engine, rerun=args.rerun, sensitivity=args.sensitivity
        )

    print()
    print((run_dir / "summary.md").read_text(encoding="utf-8"))
    return 0


def _print_agents(config: Path) -> None:
    print(f"Agents in {config} (ready = can start on this machine):\n")
    for name, settings in load_agent_table(config).items():
        status = check_agent(settings)
        state = "ready" if status.ready else "not ready"
        print(f"  {name:22} {settings.get('type', '?'):7} {state:10} {status.detail}")
        if not status.ready and status.setup:
            print(f"  {'':41} setup: {status.setup}")
    print("\nSet-up steps for every agent: docs/agents.md")


def _agents_ready(config: Path, names: list[str]) -> bool:
    """Stop before a run when an agent cannot start, instead of failing every case."""

    table = load_agent_table(config)
    blocked = [(name, check_agent(table[name])) for name in names]
    blocked = [(name, status) for name, status in blocked if not status.ready]
    for name, status in blocked:
        print(f"{name} is not ready: {status.detail}.", file=sys.stderr)
        if status.setup:
            print(f"  setup: {status.setup}", file=sys.stderr)
    if blocked:
        print("See every agent's status with --list, or docs/agents.md.", file=sys.stderr)
    return not blocked


if __name__ == "__main__":
    raise SystemExit(main())
