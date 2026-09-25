"""Load BlueFin synthesis tasks from a local BlueFin checkout or data release."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BLUEFIN_REPOSITORY_URL = "https://github.com/Longitude-Labs/bluefin"
BLUEFIN_DATASET_URL = "https://huggingface.co/datasets/Longitude-Labs/bluefin-release"
SUPPORTED_BLUEFIN_TASK_TYPES = ("synthesis",)


@dataclass(frozen=True)
class BlueFinCase:
    """One local BlueFin task directory."""

    case_id: str
    task_type: str
    task_dir: Path
    instruction: str
    input_workbook: Path
    rubric: Path
    sample_output: Path | None = None
    metadata: dict[str, Any] | None = None
    n_criteria: int = 0

    @property
    def task_name(self) -> str:
        meta = self.metadata or {}
        return str(meta.get("task_name") or self.case_id)


def find_bluefin_task_dirs(
    paths: Sequence[Path | str], *, task_type: str = "synthesis"
) -> list[Path]:
    """Accept task folders, a BlueFin root, or a folder containing task folders."""

    if task_type not in SUPPORTED_BLUEFIN_TASK_TYPES:
        raise ValueError(f"unsupported BlueFin task type {task_type!r}")
    found: list[Path] = []
    for item in paths:
        path = Path(item)
        if _is_bluefin_task_dir(path):
            found.append(path)
            continue
        for parent in (path / "tasks" / task_type, path / task_type, path):
            if not parent.is_dir():
                continue
            found.extend(sorted(child for child in parent.iterdir() if _is_bluefin_task_dir(child)))
            break
    return list(dict.fromkeys(found))


def load_bluefin_synthesis_cases(
    roots: Path | str | Sequence[Path | str],
    *,
    case_ids: Iterable[str] | None = None,
) -> list[BlueFinCase]:
    """Load public BlueFin synthesis task folders from local files."""

    paths: Sequence[Path | str]
    if isinstance(roots, str | Path):
        paths = [roots]
    else:
        paths = roots
    selected = set(case_ids or ())
    cases: list[BlueFinCase] = []
    for task_dir in find_bluefin_task_dirs(paths, task_type="synthesis"):
        case_id = task_dir.name
        if selected and case_id not in selected:
            continue
        cases.append(load_bluefin_synthesis_case(task_dir))
    return cases


def load_bluefin_synthesis_case(task_dir: Path | str) -> BlueFinCase:
    """Read one BlueFin synthesis task directory."""

    directory = Path(task_dir)
    instruction_path = directory / "instruction.md"
    rubric_path = directory / "rubric.json"
    input_path = directory / "input_workbook.xlsx"
    missing = [
        path.name for path in (instruction_path, rubric_path, input_path) if not path.exists()
    ]
    if missing:
        raise ValueError(f"{directory} is missing BlueFin file(s): {', '.join(missing)}")

    metadata_path = directory / "metadata.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    )
    rubric = json.loads(rubric_path.read_text(encoding="utf-8"))
    sample = directory / "sample_output.xlsx"
    return BlueFinCase(
        case_id=directory.name,
        task_type="synthesis",
        task_dir=directory,
        instruction=instruction_path.read_text(encoding="utf-8"),
        input_workbook=input_path,
        rubric=rubric_path,
        sample_output=sample if sample.exists() else None,
        metadata=metadata,
        n_criteria=int(metadata.get("n_criteria") or _count_criteria(rubric)),
    )


def bluefin_task_text(case: BlueFinCase) -> str:
    """Task text for manual or generic CLI agents."""

    return (
        f"# BlueFin Synthesis Task {case.case_id}\n\n"
        "The Excel workbook `input.xlsx` is in this folder. Build the complete model "
        "described below and save the completed workbook as `output.xlsx` in this folder.\n\n"
        f"{case.instruction}\n"
    )


def _is_bluefin_task_dir(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "instruction.md").exists()
        and (path / "rubric.json").exists()
        and (path / "input_workbook.xlsx").exists()
    )


def _count_criteria(rubric: dict[str, Any]) -> int:
    return sum(len(section.get("criteria", ())) for section in rubric.get("sections", ()))
