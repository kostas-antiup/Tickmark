"""Run and normalize BlueFin's upstream grader for local task outputs."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .bluefin_cases import BlueFinCase

_LOG_TAIL = 20_000


@dataclass(frozen=True)
class BlueFinEvaluationReport:
    """JSON-ready report for one BlueFin grading run."""

    case_id: str
    workbook: str
    passed: bool | None
    pass_threshold: float
    reward: float | None
    score_int: int | None
    score_pct: float | None
    criteria_total: int | None
    criteria_met: int | None
    section_scores: dict[str, float] = field(default_factory=dict)
    reward_path: str | None = None
    details_path: str | None = None
    command: list[str] = field(default_factory=list)
    returncode: int | None = None
    stdout_tail: str = ""
    stderr_tail: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def grade_bluefin_workbook(
    case: BlueFinCase,
    workbook: Path | str,
    *,
    code_root: Path | str,
    out_dir: Path | str,
    judge_model: str,
    pass_threshold: float = 0.8,
    max_turns: int = 200,
    python_executable: Path | str | None = None,
) -> BlueFinEvaluationReport:
    """Grade ``workbook`` with BlueFin's ``scoring.grade`` module."""

    workbook = Path(workbook)
    code_root = Path(code_root)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    reward_path = out_dir / "reward.json"
    details_path = out_dir / "grade_details.json"

    if not workbook.exists():
        return _error_report(case, workbook, pass_threshold, f"workbook not found: {workbook}")
    if not (code_root / "scoring" / "grade.py").exists():
        return _error_report(
            case,
            workbook,
            pass_threshold,
            f"BlueFin code root does not contain scoring/grade.py: {code_root}",
        )

    python = str(python_executable or _default_python(code_root))
    command = [
        python,
        "-m",
        "scoring.grade",
        "--output",
        str(workbook.resolve()),
        "--rubric",
        str(case.rubric.resolve()),
        "--reward-path",
        str(reward_path.resolve()),
        "--judge-model",
        judge_model,
        "--task-prompt",
        str((case.task_dir / "instruction.md").resolve()),
        "--max-turns",
        str(max_turns),
    ]
    env = {
        **os.environ,
        "PYTHONPATH": str(code_root.resolve()),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(
        command,
        cwd=code_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        check=False,
    )
    parsed = _parse_bluefin_grade(
        case,
        workbook,
        reward_path=reward_path,
        details_path=details_path,
        pass_threshold=pass_threshold,
    )
    return replace(
        parsed,
        command=command,
        returncode=completed.returncode,
        stdout_tail=_tail(completed.stdout),
        stderr_tail=_tail(completed.stderr),
        error=parsed.error
        or (f"BlueFin grader exited {completed.returncode}" if completed.returncode != 0 else None),
    )


def report_from_existing_bluefin_grade(
    case: BlueFinCase,
    workbook: Path | str,
    *,
    reward_path: Path | str,
    details_path: Path | str | None = None,
    pass_threshold: float = 0.8,
) -> BlueFinEvaluationReport:
    """Normalize existing BlueFin ``reward.json`` / ``grade_details.json`` files."""

    reward = Path(reward_path)
    details = Path(details_path) if details_path else reward.with_name("grade_details.json")
    return _parse_bluefin_grade(
        case,
        Path(workbook),
        reward_path=reward,
        details_path=details,
        pass_threshold=pass_threshold,
    )


def _parse_bluefin_grade(
    case: BlueFinCase,
    workbook: Path,
    *,
    reward_path: Path,
    details_path: Path,
    pass_threshold: float,
) -> BlueFinEvaluationReport:
    reward_data = _read_json(reward_path)
    details_data = _read_json(details_path)
    if reward_data is None and details_data is None:
        return _error_report(
            case,
            workbook,
            pass_threshold,
            f"no BlueFin reward files found at {reward_path} or {details_path}",
            reward_path=reward_path,
            details_path=details_path,
        )

    reward = _float_or_none((reward_data or {}).get("reward"))
    score_pct = _float_or_none((details_data or {}).get("score_pct"))
    if score_pct is None:
        score_pct = reward
    score_int = _int_or_none((details_data or {}).get("score_int"))
    if score_int is None and score_pct is not None:
        score_int = round(score_pct * 100)
    criteria_total = _int_or_none((details_data or {}).get("criteria_total")) or case.n_criteria
    criteria_met = _int_or_none((details_data or {}).get("criteria_met"))
    section_scores = {
        str(name): float(value)
        for name, value in ((details_data or {}).get("section_scores") or {}).items()
    }
    passed = None if score_pct is None else score_pct >= pass_threshold
    return BlueFinEvaluationReport(
        case_id=case.case_id,
        workbook=str(workbook),
        passed=passed,
        pass_threshold=pass_threshold,
        reward=reward,
        score_int=score_int,
        score_pct=score_pct,
        criteria_total=criteria_total,
        criteria_met=criteria_met,
        section_scores=section_scores,
        reward_path=str(reward_path),
        details_path=str(details_path),
    )


def _error_report(
    case: BlueFinCase,
    workbook: Path,
    pass_threshold: float,
    error: str,
    *,
    reward_path: Path | None = None,
    details_path: Path | None = None,
) -> BlueFinEvaluationReport:
    return BlueFinEvaluationReport(
        case_id=case.case_id,
        workbook=str(workbook),
        passed=None,
        pass_threshold=pass_threshold,
        reward=None,
        score_int=None,
        score_pct=None,
        criteria_total=case.n_criteria,
        criteria_met=None,
        reward_path=str(reward_path) if reward_path else None,
        details_path=str(details_path) if details_path else None,
        error=error,
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except TypeError, ValueError:
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def _tail(text: str | None) -> str:
    return (text or "")[-_LOG_TAIL:]


def _default_python(code_root: Path) -> Path:
    candidates = (
        code_root / ".venv" / "bin" / "python",
        code_root / ".venv" / "Scripts" / "python.exe",
    )
    return next((path for path in candidates if path.exists()), Path(sys.executable))
