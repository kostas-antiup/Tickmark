"""Run agents on cases, grade their workbooks and summarise the results.

Layout of one run (``results/runs/<run_id>/``)::

    <agent>/<case>/output.xlsx      completed workbook
    <agent>/<case>/agent_log.json   status, timing, agent output
    <agent>/<case>/report.json      evaluator report (only when a workbook exists)
    summary.json, summary.md        per-agent and per-case results

Cases that already have a ``report.json`` are not re-run unless ``rerun=True``,
so an interrupted or rate-limited run can simply be started again.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import traceback
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents import OUTPUT_NAME, Agent, AgentResult, AgentTask
from .baselines import GRADER_LABELS, GRADERS
from .cases import CaseSpec
from .evaluator import evaluate_workbook
from .recalculation import Recalculator
from .report_html import write_html_report

OUTCOMES = ("pass", "values only", "auditable, wrong values", "fail")


@dataclass(frozen=True)
class RunRecord:
    """Outcome of one agent on one case."""

    agent: str
    case_id: str
    status: str
    outcome: str
    duration_seconds: float
    error: str | None
    scores: dict[str, float] | None
    failed_checks: list[str]
    remarks: list[str]
    result_dir: str
    family: str = ""
    n_targets: int = 0
    checks: dict[str, bool | None] | None = None
    warnings: list[str] = field(default_factory=list)
    # Pass/fail of existing value-only benchmarks on the same workbook (``baselines``).
    baselines: dict[str, bool] = field(default_factory=dict)


def outcome_of(report: dict[str, Any] | None, status: str) -> str:
    """``pass`` / ``values only`` / ``auditable, wrong values`` / ``fail``, else the status."""

    if report is None:
        return {"pending": "pending", "no_output": "no output"}.get(status, "error")
    if report["correct"] and report["auditable"]:
        return "pass"
    if report["correct"]:
        return "values only"
    if report["auditable"]:
        return "auditable, wrong values"
    return "fail"


def _record(agent: str, case_id: str, result_dir: Path, log: dict[str, Any]) -> RunRecord:
    report_file = result_dir / "report.json"
    report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else None
    status = log.get("status", "completed" if report else "error")
    failed = (
        [name for name, check in report["checks"].items() if check["passed"] is False]
        if report
        else []
    )
    return RunRecord(
        agent=agent,
        case_id=case_id,
        status=status,
        outcome=outcome_of(report, status),
        duration_seconds=float(log.get("duration_seconds", 0.0)),
        error=log.get("error"),
        scores=report["scores"] if report else None,
        failed_checks=failed,
        remarks=list(report["remarks"]) if report else [],
        result_dir=str(result_dir),
        family=log.get("family", ""),
        n_targets=int(log.get("n_targets", 0)),
        checks={name: check["passed"] for name, check in report["checks"].items()}
        if report
        else None,
        warnings=list(report.get("warnings", [])) if report else [],
        baselines={
            name: bool(verdict["passed"]) for name, verdict in report.get("baselines", {}).items()
        }
        if report
        else {},
    )


def _write_json(path: Path, data: Any) -> None:
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )


def _copy2_wait(source: Path, target: Path, *, attempts: int = 60, delay: float = 0.5) -> None:
    """Copy a file, tolerating brief Windows locks left by external agent processes."""

    for attempt in range(attempts):
        try:
            shutil.copy2(source, target)
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def run_case(
    agent: Agent,
    case: CaseSpec,
    run_dir: Path,
    engine: Recalculator,
    *,
    rerun: bool = False,
    sensitivity: bool = False,
) -> RunRecord:
    """Let ``agent`` solve ``case`` (unless already graded), grade the result, record it."""

    result_dir = run_dir / agent.name / case.case_id
    log_file = result_dir / "agent_log.json"
    if not rerun and log_file.exists():
        log = json.loads(log_file.read_text("utf-8"))
        if (result_dir / "report.json").exists():
            return _record(agent.name, case.case_id, result_dir, log)
        if log.get("grading_error") and (result_dir / OUTPUT_NAME).exists():
            # The agent's workbook is there; only grading failed last time, so retry that.
            log = _grade(case, result_dir, engine, log, sensitivity)
            return _record(agent.name, case.case_id, result_dir, log)

    result_dir.mkdir(parents=True, exist_ok=True)
    output = result_dir / OUTPUT_NAME
    (result_dir / "report.json").unlink(missing_ok=True)
    manual = agent.kind == "manual"
    if not manual:
        output.unlink(missing_ok=True)  # never grade a stale workbook from an earlier attempt
    # Manual agents work in the result folder so the person can drop output.xlsx there;
    # automated agents get an empty temporary folder away from the repository.
    workspace = result_dir if manual else Path(tempfile.mkdtemp(prefix="fb_agent_"))
    task = AgentTask(case.case_id, case.instruction, case.input_workbook, workspace)
    keep_workspace = False
    try:
        try:
            result = agent.solve(task)
        except Exception as error:  # an adapter bug must not stop the whole run
            result = AgentResult("failed", None, error=f"{type(error).__name__}: {error}")
        produced = result.output_workbook
        if produced is not None and produced.resolve() != output.resolve():
            try:
                _copy2_wait(produced, output)
            except PermissionError as error:
                keep_workspace = True
                result = AgentResult(
                    "failed",
                    None,
                    result.duration_seconds,
                    {
                        **result.log,
                        "uncollected_output": str(produced),
                        "workspace_kept": str(workspace),
                    },
                    f"could not collect output workbook: {error}",
                )
    finally:
        if not manual and not keep_workspace:
            shutil.rmtree(workspace, ignore_errors=True)

    log = {
        "agent": agent.name,
        "kind": agent.kind,
        "case_id": case.case_id,
        "family": case.family,
        "n_targets": len(case.target_cells),
        "status": result.status,
        "error": result.error,
        "duration_seconds": round(result.duration_seconds, 1),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        **result.log,
    }
    _write_json(log_file, log)
    if result.output_workbook is not None:
        log = _grade(case, result_dir, engine, log, sensitivity)
    return _record(agent.name, case.case_id, result_dir, log)


def _grade(
    case: CaseSpec,
    result_dir: Path,
    engine: Recalculator,
    log: dict[str, Any],
    sensitivity: bool,
) -> dict[str, Any]:
    """Grade ``output.xlsx``; a grading error is logged (``grading_error``), never raised."""

    try:
        report = evaluate_workbook(case, result_dir / OUTPUT_NAME, engine, sensitivity=sensitivity)
    except Exception as error:
        log = {
            **log,
            "grading_error": True,
            "error": f"grading failed: {type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }
    else:
        _write_json(result_dir / "report.json", report.to_dict())
        if log.pop("grading_error", None):
            log = {**log, "error": None}
            log.pop("traceback", None)
    _write_json(result_dir / "agent_log.json", log)
    return log


def run_benchmark(
    agents: Sequence[Agent],
    cases: Sequence[CaseSpec],
    run_dir: Path,
    engine: Recalculator,
    *,
    rerun: bool = False,
    sensitivity: bool = False,
    progress: Any = print,
) -> list[RunRecord]:
    records: list[RunRecord] = []
    for agent in agents:
        for case in cases:
            record = run_case(agent, case, run_dir, engine, rerun=rerun, sensitivity=sensitivity)
            progress(
                f"{agent.name:24} {case.case_id:7} {record.outcome:24} "
                f"{record.duration_seconds:6.0f}s  {record.error or ''}"
            )
            records.append(record)
    write_summary(run_dir, records, engine.name)
    return records


def collect_records(run_dir: Path) -> list[RunRecord]:
    """Re-read every ``<agent>/<case>/agent_log.json`` of an existing run."""

    records = []
    for log_file in sorted(run_dir.glob("*/*/agent_log.json")):
        log = json.loads(log_file.read_text(encoding="utf-8"))
        records.append(_record(log["agent"], log["case_id"], log_file.parent, log))
    return records


def _agent_totals(records: Iterable[RunRecord]) -> dict[str, dict[str, Any]]:
    totals: dict[str, dict[str, Any]] = {}
    for record in records:
        entry = totals.setdefault(
            record.agent,
            {"cases": 0, "graded": 0, **{outcome: 0 for outcome in OUTCOMES}, "no result": 0},
        )
        entry["cases"] += 1
        if record.scores is None:
            entry["no result"] += 1
            continue
        entry["graded"] += 1
        entry[record.outcome] += 1
    for entry in totals.values():
        entry["value-only score"] = entry["pass"] + entry["values only"]
        entry["auditable score"] = entry["pass"]
    return totals


def grader_totals(records: Iterable[RunRecord]) -> dict[str, dict[str, dict[str, int]]]:
    """Per agent and existing grader: workbooks it passes, and where it disagrees with ours.

    ``accepted_not_model``: the existing grader passes it, this benchmark does not.
    ``rejected_real_model``: this benchmark passes it, the existing grader does not.
    """

    totals: dict[str, dict[str, dict[str, int]]] = {}
    for record in records:
        for grader in GRADERS:
            entry = totals.setdefault(record.agent, {}).setdefault(
                grader,
                {"graded": 0, "passed": 0, "accepted_not_model": 0, "rejected_real_model": 0},
            )
            verdict = record.baselines.get(grader)
            if verdict is None:
                continue
            ours = record.outcome == "pass"
            entry["graded"] += 1
            entry["passed"] += verdict
            entry["accepted_not_model"] += verdict and not ours
            entry["rejected_real_model"] += ours and not verdict
    return totals


def _grader_comparison_lines(records: Sequence[RunRecord]) -> list[str]:
    totals = grader_totals(records)
    if not any(entry["graded"] for graders in totals.values() for entry in graders.values()):
        return []
    lines = [
        "## Compared with existing benchmarks (same workbooks)",
        "",
        "| Agent | Grader | Passes | This benchmark passes | Accepted, not a real model "
        "| Real model, rejected |",
        "|---|---|---|---|---|---|",
    ]
    for agent, graders in totals.items():
        ours = sum(r.outcome == "pass" for r in records if r.agent == agent and r.baselines)
        for grader, entry in graders.items():
            n = entry["graded"]
            if not n:
                continue
            lines.append(
                f"| {agent} | {GRADER_LABELS[grader]} | {entry['passed']}/{n} | {ours}/{n} "
                f"| {entry['accepted_not_model']} | {entry['rejected_real_model']} |"
            )
    lines += [
        "",
        "Existing graders compare final values only (see `tickmark.baselines`). "
        "'Accepted, not a real model' = right values but hardcoded or not live.",
    ]
    return lines


def write_summary(run_dir: Path, records: Sequence[RunRecord], engine: str) -> None:
    """Write ``summary.json`` and a readable ``summary.md`` for the run."""

    totals = _agent_totals(records)
    _write_json(
        run_dir / "summary.json",
        {
            "run": run_dir.name,
            "engine": engine,
            "written_at": datetime.now().isoformat(timespec="seconds"),
            "agents": totals,
            "existing_graders": grader_totals(records),
            "records": [asdict(record) for record in records],
        },
    )

    lines = [f"# Run `{run_dir.name}`", "", f"Recalculation engine: {engine}", ""]
    lines += [
        "## Headline: value-only grading vs auditability grading",
        "",
        "| Agent | Cases | Value-only grading (correct numbers) | Auditability grading (pass) "
        "| Correct but not auditable | No result |",
        "|---|---|---|---|---|---|",
    ]
    for agent, entry in totals.items():
        n = entry["cases"]
        lines.append(
            f"| {agent} | {n} | {entry['value-only score']}/{n} | {entry['auditable score']}/{n} "
            f"| {entry['values only']} | {entry['no result']} |"
        )

    lines += ["", *_grader_comparison_lines(records)]

    agents = list(totals)
    by_case: dict[str, dict[str, RunRecord]] = {}
    for record in records:
        by_case.setdefault(record.case_id, {})[record.agent] = record
    lines += ["", "## By case", "", "| Case | " + " | ".join(agents) + " |"]
    lines.append("|---|" + "---|" * len(agents))
    for case_id in sorted(by_case):
        cells = []
        for agent in agents:
            record = by_case[case_id].get(agent)
            if record is None:
                cells.append("")
            elif record.scores is None:
                cells.append(record.outcome)
            else:
                s = record.scores
                cells.append(
                    f"{record.outcome} (V {s['value_correctness']:.2f} · F "
                    f"{s['formula_coverage']:.2f} · T {s['traceability']:.2f})"
                )
        lines.append(f"| {case_id} | " + " | ".join(cells) + " |")

    lines += ["", "## Why cases did not pass", ""]
    for record in records:
        if record.outcome == "pass":
            continue
        reason = "; ".join(record.remarks[:3]) or record.error or record.status
        checks = f" (failed: {', '.join(record.failed_checks)})" if record.failed_checks else ""
        lines.append(f"- **{record.agent} / {record.case_id}**: {record.outcome}{checks}. {reason}")
    lines += [
        "",
        "V = value correctness, F = formula coverage, T = traceability. "
        "'values only' = every number correct but the workbook is not an auditable model.",
        "",
    ]
    (run_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    write_html_report(run_dir, records, engine)
