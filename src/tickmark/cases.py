"""Load a benchmark case (``data/cases/<id>/case.json`` + golden workbook)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .baselines import answer_cells, stable_cells, used_range_cells
from .cell_refs import cell_key, expand_reference, split_reference
from .scenarios import Decision, extract_decisions
from .workbook_audit import reachable_cells
from .workbook_reader import read_workbook


@dataclass(frozen=True)
class InputChangeCheck:
    """Set ``cell`` to ``perturbed_value``; ``output_cell`` must move to ``expected_after``."""

    cell: str
    perturbed_value: float
    output_cell: str
    expected_before: Any
    expected_after: Any


@dataclass(frozen=True)
class CaseSpec:
    """Everything the evaluator needs about one case, with cells expanded to keys."""

    case_id: str
    directory: Path
    instruction: str
    input_workbook: Path
    golden_workbook: Path
    target_cells: tuple[str, ...]
    input_cells: frozenset[str]
    final_output: str
    key_outputs: tuple[str, ...]
    reference_values: Mapping[str, Any]
    reference_literals: frozenset[float]
    golden_input_values: Mapping[str, Any]
    abs_tolerance: float
    rel_tolerance: float
    input_change: InputChangeCheck | None
    family: str = ""
    # Input cells each target depends on in the reference model (its input footprint).
    reference_footprints: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # Branch points (IF, MIN/MAX, IFERROR, ABS) in the reference target formulas.
    reference_decisions: tuple[Decision, ...] = ()
    # Cells existing benchmarks grade (see ``baselines``) and their golden values.
    answer_cells: tuple[str, ...] = ()
    sheet_cells: tuple[str, ...] = ()
    comparison_values: Mapping[str, Any] = field(default_factory=dict)

    @property
    def comparison_cells(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.answer_cells, *self.sheet_cells)))


def find_case_dirs(paths: list[Path]) -> list[Path]:
    """Accept case folders, or parent folders whose sub-folders hold ``case.json``."""

    found: list[Path] = []
    for path in paths:
        if (path / "case.json").exists():
            found.append(path)
        elif path.is_dir():
            found.extend(sorted(p for p in path.iterdir() if (p / "case.json").exists()))
    return found


def _key(reference: str) -> str:
    sheet, address = split_reference(reference)
    return cell_key(sheet, address)


def _expand_all(references: list[str]) -> list[str]:
    return list(dict.fromkeys(key for ref in references for key in expand_reference(ref)))


def load_case(directory: Path | str) -> CaseSpec:
    """Read ``case.json`` and the golden workbook's cached values for all graded cells.

    Tier-B ``allowed_hardcoded_cells`` count as inputs (valid chain endpoints).
    """

    directory = Path(directory)
    meta = json.loads((directory / "case.json").read_text(encoding="utf-8"))
    targets = tuple(_expand_all(meta["target_cells"]))
    allowed = [ref for entry in meta.get("allowed_hardcoded_cells", []) for ref in entry["cells"]]
    inputs = frozenset(_expand_all(meta["input_cells"]) + _expand_all(allowed))
    final_output = _key(meta["final_output"])
    key_outputs = tuple(dict.fromkeys([final_output, *map(_key, meta.get("key_outputs", []))]))

    golden_path = directory / meta["golden_workbook"]
    golden = read_workbook(golden_path)
    reference_values = {
        key: golden.observations[key].value
        for key in (*targets, *key_outputs)
        if key in golden.observations
    }
    reference_literals = frozenset(
        abs(number) for numbers in golden.literals.values() for number in numbers
    )
    golden_input_values = {
        key: golden.observations[key].value
        for key in _expand_all(meta.get("golden_input_cells", []))
        if key in golden.observations
    }

    check = meta.get("input_change_check")
    input_change = None
    if check:
        input_change = InputChangeCheck(
            cell=_key(check["cell"]),
            perturbed_value=check["perturbed_value"],
            output_cell=_key(check["observed_output"]),
            expected_before=check["output_before"],
            expected_after=check["output_after_in_golden"],
        )

    answer = stable_cells(answer_cells(meta.get("source_answer_position", "")), golden.observations)
    sheet_cells = stable_cells(
        used_range_cells(golden.observations, (split_reference(t)[0] for t in targets)),
        golden.observations,
    )
    comparison_values = {
        key: golden.observations[key].value if key in golden.observations else None
        for key in dict.fromkeys((*answer, *sheet_cells))
    }

    tolerance = meta.get("value_tolerance", {})
    return CaseSpec(
        case_id=meta["id"],
        directory=directory,
        instruction=meta["instruction"],
        input_workbook=directory / meta["input_workbook"],
        golden_workbook=golden_path,
        target_cells=targets,
        input_cells=inputs,
        final_output=final_output,
        key_outputs=key_outputs,
        reference_values=reference_values,
        reference_literals=reference_literals,
        golden_input_values=golden_input_values,
        abs_tolerance=float(tolerance.get("abs", 1e-6)),
        rel_tolerance=float(tolerance.get("rel", 1e-6)),
        input_change=input_change,
        family=meta.get("family", ""),
        reference_footprints={
            target: cells & inputs
            for target, cells in reachable_cells(golden.observations.values(), targets).items()
        },
        reference_decisions=tuple(extract_decisions(golden.observations, targets)),
        answer_cells=answer,
        sheet_cells=sheet_cells,
        comparison_values=comparison_values,
    )
