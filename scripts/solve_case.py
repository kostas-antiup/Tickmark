#!/usr/bin/env python3
"""Run one configured agent on one case and write a completed XLSX workbook.

This is the lightweight path for "input.xlsx + instruction from case.json" usage.
Use scripts/run_agents.py when you also want benchmark grading and summaries.

Examples:
    uv run python scripts/solve_case.py --agent gemini-flash --case data/cases/02_01
    uv run python scripts/solve_case.py --agent claude-code --case data/cases/14_07 \
        --output out.xlsx
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.agents import AgentTask, load_agents  # noqa: E402
from tickmark.cases import load_case  # noqa: E402


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", required=True, help="agent name from configs/agents.toml")
    parser.add_argument(
        "--case",
        required=True,
        type=Path,
        help="case folder containing case.json and input.xlsx",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "agents.toml",
        help="agent config file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="where to write the completed workbook (default: <case>/output.<agent>.xlsx)",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        help="keep and use this workspace instead of a temporary directory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    case = load_case(args.case)
    agent = load_agents(args.config, [args.agent])[0]
    output = args.output or (case.directory / f"output.{agent.name}.xlsx")

    if args.workspace:
        workspace = args.workspace
        remove_workspace = False
    elif agent.kind == "manual":
        workspace = output.parent / f"{output.stem}.workspace"
        remove_workspace = False
    else:
        workspace = Path(tempfile.mkdtemp(prefix="fb_solve_"))
        remove_workspace = True
    try:
        task = AgentTask(case.case_id, case.instruction, case.input_workbook, workspace)
        result = agent.solve(task)
        log = {
            "agent": agent.name,
            "kind": agent.kind,
            "case_id": case.case_id,
            "status": result.status,
            "error": result.error,
            "duration_seconds": round(result.duration_seconds, 1),
            "workspace": str(workspace),
            **result.log,
        }
        print(json.dumps(log, indent=2, ensure_ascii=False, default=str))

        if result.output_workbook is None:
            return 1 if result.status != "pending" else 0
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(result.output_workbook, output)
        print(f"\nWrote {output}")
        return 0
    finally:
        if remove_workspace:
            shutil.rmtree(workspace, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
