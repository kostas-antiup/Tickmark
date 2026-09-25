#!/usr/bin/env python3
"""Run or grade local BlueFin synthesis tasks.

Examples:
    # list locally available synthesis tasks
    python scripts/run_bluefin.py --bluefin-root data/bluefin --list

    # grade BlueFin's sample output for one synthesis task
    python scripts/run_bluefin.py --bluefin-root data/bluefin \\
        --cases TTWO_Operating_Model_DCF --sample --bluefin-code-root data/bluefin

    # run configured agents, then grade their output workbooks with BlueFin's judge
    python scripts/run_bluefin.py --bluefin-root data/bluefin \\
        --agents claude-code --cases TTWO_Operating_Model_DCF --run-id pilot
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from tickmark.agents import (  # noqa: E402
    OUTPUT_NAME,
    Agent,
    AgentResult,
    AgentTask,
    load_agents,
)
from tickmark.bluefin_cases import (  # noqa: E402
    BLUEFIN_DATASET_URL,
    BLUEFIN_REPOSITORY_URL,
    BlueFinCase,
    bluefin_task_text,
    load_bluefin_synthesis_cases,
)
from tickmark.bluefin_evaluator import (  # noqa: E402
    BlueFinEvaluationReport,
    grade_bluefin_workbook,
)


@dataclass(frozen=True)
class BlueFinRunRecord:
    agent: str
    case_id: str
    status: str
    outcome: str
    score_pct: float | None
    score_int: int | None
    criteria_met: int | None
    criteria_total: int | None
    error: str | None
    result_dir: str
    duration_seconds: float = 0.0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bluefin-root",
        type=Path,
        default=ROOT / "data" / "bluefin",
        help="BlueFin checkout, task type folder, or synthesis task folder (default: data/bluefin)",
    )
    parser.add_argument(
        "--bluefin-code-root",
        type=Path,
        help="BlueFin code checkout containing scoring/grade.py (default: --bluefin-root)",
    )
    parser.add_argument(
        "--bluefin-python",
        type=Path,
        help="Python executable with BlueFin dependencies (default: <code-root>/.venv/bin/python)",
    )
    parser.add_argument("--cases", nargs="+", help="case ids such as TTWO_Operating_Model_DCF")
    parser.add_argument("--agents", nargs="+", help="agent names from configs/agents.toml")
    parser.add_argument(
        "--config", type=Path, default=ROOT / "configs" / "agents.toml", help="agent config"
    )
    parser.add_argument("--run-id", help="results run id (default: current time)")
    parser.add_argument(
        "--results",
        type=Path,
        default=ROOT / "results" / "bluefin" / "runs",
        help="parent folder for agent-run results",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--workbook", type=Path, help="completed workbook to grade (one case)")
    source.add_argument(
        "--sample",
        action="store_true",
        help="grade each case's BlueFin sample_output.xlsx when present",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "results" / "bluefin" / "reports",
        help="folder for direct --workbook/--sample reports",
    )
    parser.add_argument("--judge-model", default="gpt-5.4", help="BlueFin judge model")
    parser.add_argument("--max-turns", type=int, default=200, help="max BlueFin judge turns")
    parser.add_argument(
        "--pass-threshold",
        type=float,
        default=0.8,
        help="score_pct threshold for this repo's pass/fail rollup",
    )
    parser.add_argument(
        "--no-grade",
        action="store_true",
        help="run/prepare agent workspaces but do not call BlueFin's LLM judge",
    )
    parser.add_argument("--rerun", action="store_true", help="redo agent cases already graded")
    parser.add_argument("--list", action="store_true", help="list local synthesis tasks and exit")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    cases = load_bluefin_synthesis_cases(args.bluefin_root, case_ids=args.cases)
    if args.list:
        return _list_cases(cases, args.bluefin_root)
    if not cases:
        print(f"No BlueFin synthesis tasks found under {args.bluefin_root}.", file=sys.stderr)
        print(f"Repository: {BLUEFIN_REPOSITORY_URL}", file=sys.stderr)
        print(f"Hugging Face data: {BLUEFIN_DATASET_URL}", file=sys.stderr)
        return 2
    if args.workbook and len(cases) != 1:
        print("--workbook requires exactly one --cases id.", file=sys.stderr)
        return 2
    if args.sample or args.workbook:
        return _grade_direct(args, cases)
    if not args.agents:
        print("Give --agents, --sample, --workbook, or --list.", file=sys.stderr)
        return 2

    agents = load_agents(args.config, args.agents)
    run_dir = args.results / (args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    print(f"run: {run_dir}  agents: {len(agents)}  cases: {len(cases)}")
    records = [_run_agent_case(agent, case, run_dir, args) for agent in agents for case in cases]
    _write_summary(run_dir, records, args)
    print()
    print((run_dir / "summary.md").read_text(encoding="utf-8"))
    return 0 if all(record.outcome == "pass" for record in records) else 1


def _list_cases(cases: list[BlueFinCase], root: Path) -> int:
    if not cases:
        print(f"No BlueFin synthesis tasks found under {root}.")
        return 2
    for case in cases:
        sample = "sample" if case.sample_output else "no-sample"
        print(f"{case.case_id:36} criteria={case.n_criteria:3d} {sample}")
    return 0


def _grade_direct(args: argparse.Namespace, cases: list[BlueFinCase]) -> int:
    code_root = args.bluefin_code_root or args.bluefin_root
    all_passed = True
    for case in cases:
        workbook = args.workbook if args.workbook else case.sample_output
        if workbook is None:
            print(f"{case.case_id:36} ERROR no sample_output.xlsx")
            all_passed = False
            continue
        report = grade_bluefin_workbook(
            case,
            workbook,
            code_root=code_root,
            out_dir=args.out / case.case_id / Path(workbook).stem,
            judge_model=args.judge_model,
            pass_threshold=args.pass_threshold,
            max_turns=args.max_turns,
            python_executable=args.bluefin_python,
        )
        out_file = args.out / case.case_id / Path(workbook).stem / "report.json"
        _write_json(out_file, report.to_dict())
        _print_report(case.case_id, report, out_file)
        all_passed &= report.passed is True
    return 0 if all_passed else 1


def _run_agent_case(
    agent: Agent,
    case: BlueFinCase,
    run_dir: Path,
    args: argparse.Namespace,
) -> BlueFinRunRecord:
    result_dir = run_dir / agent.name / case.case_id
    log_file = result_dir / "agent_log.json"
    report_file = result_dir / "report.json"
    if not args.rerun and report_file.exists():
        return _record_from_files(agent.name, case.case_id, result_dir)
    result_dir.mkdir(parents=True, exist_ok=True)

    output = result_dir / OUTPUT_NAME
    manual = agent.kind == "manual"
    if not manual:
        output.unlink(missing_ok=True)
        report_file.unlink(missing_ok=True)
    if not args.rerun and output.exists() and not report_file.exists() and not args.no_grade:
        return _grade_existing_output(agent.name, case, result_dir, args)

    workspace = result_dir if manual else Path(tempfile.mkdtemp(prefix="bluefin_agent_"))
    task = AgentTask(
        case.case_id,
        case.instruction,
        case.input_workbook,
        workspace,
        task_markdown=bluefin_task_text(case),
    )
    try:
        try:
            result = agent.solve(task)
        except Exception as error:
            result = AgentResult("failed", None, error=f"{type(error).__name__}: {error}")
        produced = result.output_workbook
        if produced is not None and produced.resolve() != output.resolve():
            shutil.copy2(produced, output)
    finally:
        if not manual:
            shutil.rmtree(workspace, ignore_errors=True)

    log = {
        "agent": agent.name,
        "kind": agent.kind,
        "case_id": case.case_id,
        "benchmark": "bluefin",
        "task_type": "synthesis",
        "status": result.status,
        "error": result.error,
        "duration_seconds": round(result.duration_seconds, 1),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **result.log,
    }
    _write_json(log_file, log)
    if result.output_workbook is not None and not args.no_grade:
        return _grade_existing_output(agent.name, case, result_dir, args)
    record = BlueFinRunRecord(
        agent.name,
        case.case_id,
        result.status,
        "pending" if result.status == "pending" else result.status,
        None,
        None,
        None,
        case.n_criteria,
        result.error,
        str(result_dir),
        round(result.duration_seconds, 1),
    )
    print(f"{agent.name:24} {case.case_id:36} {record.outcome:10} {record.error or ''}")
    return record


def _grade_existing_output(
    agent_name: str,
    case: BlueFinCase,
    result_dir: Path,
    args: argparse.Namespace,
) -> BlueFinRunRecord:
    code_root = args.bluefin_code_root or args.bluefin_root
    try:
        report = grade_bluefin_workbook(
            case,
            result_dir / OUTPUT_NAME,
            code_root=code_root,
            out_dir=result_dir,
            judge_model=args.judge_model,
            pass_threshold=args.pass_threshold,
            max_turns=args.max_turns,
            python_executable=args.bluefin_python,
        )
    except Exception as error:
        report = BlueFinEvaluationReport(
            case_id=case.case_id,
            workbook=str(result_dir / OUTPUT_NAME),
            passed=None,
            pass_threshold=args.pass_threshold,
            reward=None,
            score_int=None,
            score_pct=None,
            criteria_total=case.n_criteria,
            criteria_met=None,
            error=f"{type(error).__name__}: {error}",
            stderr_tail=traceback.format_exc(),
        )
    _write_json(result_dir / "report.json", report.to_dict())
    record = _record_from_report(agent_name, case.case_id, result_dir, report)
    print(
        f"{agent_name:24} {case.case_id:36} {record.outcome:10} "
        f"score={record.score_pct if record.score_pct is not None else '-'} "
        f"{record.error or ''}"
    )
    return record


def _record_from_files(agent_name: str, case_id: str, result_dir: Path) -> BlueFinRunRecord:
    report = json.loads((result_dir / "report.json").read_text(encoding="utf-8"))
    return _record_from_report_dict(agent_name, case_id, result_dir, report)


def _record_from_report(
    agent_name: str,
    case_id: str,
    result_dir: Path,
    report: BlueFinEvaluationReport,
) -> BlueFinRunRecord:
    return _record_from_report_dict(agent_name, case_id, result_dir, report.to_dict())


def _record_from_report_dict(
    agent_name: str,
    case_id: str,
    result_dir: Path,
    report: dict[str, Any],
) -> BlueFinRunRecord:
    passed = report.get("passed")
    if passed is True:
        outcome = "pass"
    elif passed is False:
        outcome = "fail"
    else:
        outcome = "error"
    log_file = result_dir / "agent_log.json"
    log = json.loads(log_file.read_text(encoding="utf-8")) if log_file.exists() else {}
    return BlueFinRunRecord(
        agent=agent_name,
        case_id=case_id,
        status=str(log.get("status") or outcome),
        outcome=outcome,
        score_pct=report.get("score_pct"),
        score_int=report.get("score_int"),
        criteria_met=report.get("criteria_met"),
        criteria_total=report.get("criteria_total"),
        error=report.get("error") or log.get("error"),
        result_dir=str(result_dir),
        duration_seconds=float(log.get("duration_seconds", 0.0)),
    )


def _write_summary(
    run_dir: Path, records: list[BlueFinRunRecord], args: argparse.Namespace
) -> None:
    totals: dict[str, dict[str, Any]] = {}
    for record in records:
        entry = totals.setdefault(
            record.agent,
            {"cases": 0, "pass": 0, "fail": 0, "error": 0, "pending": 0, "other": 0},
        )
        entry["cases"] += 1
        entry[record.outcome if record.outcome in entry else "other"] += 1
    _write_json(
        run_dir / "summary.json",
        {
            "run": run_dir.name,
            "benchmark": "bluefin",
            "task_type": "synthesis",
            "judge_model": args.judge_model,
            "pass_threshold": args.pass_threshold,
            "written_at": datetime.now().isoformat(timespec="seconds"),
            "agents": totals,
            "records": [asdict(record) for record in records],
        },
    )
    lines = [
        f"# BlueFin synthesis run `{run_dir.name}`",
        "",
        f"Judge model: `{args.judge_model}`. Pass threshold: `{args.pass_threshold}`.",
        "",
        "## Agents",
        "",
        "| Agent | Cases | Pass | Fail | Error | Pending |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for agent, entry in totals.items():
        lines.append(
            f"| {agent} | {entry['cases']} | {entry['pass']} | {entry['fail']} "
            f"| {entry['error']} | {entry['pending']} |"
        )
    lines += [
        "",
        "## Cases",
        "",
        "| Agent | Case | Outcome | Score | Criteria | Result | Error |",
        "|---|---|---|---:|---:|---|---|",
    ]
    for record in records:
        score = "-" if record.score_pct is None else f"{record.score_pct:.4f}"
        criteria = (
            "-"
            if record.criteria_met is None or record.criteria_total is None
            else f"{record.criteria_met}/{record.criteria_total}"
        )
        error = (record.error or "").replace("|", "\\|")
        lines.append(
            f"| {record.agent} | {record.case_id} | {record.outcome} | {score} "
            f"| {criteria} | `{record.result_dir}` | {error} |"
        )
    (run_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _print_report(case_id: str, report: BlueFinEvaluationReport, out_file: Path) -> None:
    score = "-" if report.score_pct is None else f"{report.score_pct:.4f}"
    criteria = (
        "-"
        if report.criteria_met is None or report.criteria_total is None
        else f"{report.criteria_met}/{report.criteria_total}"
    )
    verdict = "PASS" if report.passed else "FAIL" if report.passed is False else "ERROR"
    print(f"{case_id:36} {verdict} score={score} criteria={criteria} -> {out_file}")
    if report.error:
        print(f"          - {report.error}")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
