"""Generate controlled malformed submissions from a benchmark golden workbook."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import openpyxl

from .cases import CaseSpec
from .cell_refs import split_reference
from .workbook_audit import trace_breaks
from .workbook_reader import formula_text, read_workbook


@dataclass(frozen=True)
class CellMutation:
    """One deliberate cell change made to a malformed submission."""

    cell: str
    before: Any
    after: Any


@dataclass(frozen=True)
class GeneratedOutput:
    """Description and expected structural scores for one generated workbook."""

    variant: str
    workbook: str
    purpose: str
    mutations: tuple[CellMutation, ...]
    expected_value_correctness_after_recalculation: float
    expected_formula_coverage: float
    expected_traceability: float


def generate_malformed_outputs(
    case: CaseSpec, output_dir: Path | str
) -> tuple[GeneratedOutput, ...]:
    """Create seven malformed workbook variants from ``case.golden_workbook``.

    The original golden workbook is never modified. Generated formula workbooks are marked for a
    full recalculation when opened because openpyxl does not calculate or preserve formula caches.
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    final_formula = _formula_at(case.golden_workbook, case.final_output)
    if final_formula is None:
        raise ValueError(
            f"final output {case.final_output} is not a formula in the golden workbook"
        )

    target_count = len(case.target_cells)
    half_count = max(1, target_count // 2)
    intermediate = find_intermediate_target(case)
    expected_final = case.reference_values[case.final_output]

    variants: tuple[tuple[str, str, dict[str, Any], float], ...] = (
        (
            "hardcoded_final",
            "Correct final value pasted as a constant; formula and final-output lineage must fail.",
            {case.final_output: expected_final},
            1.0,
        ),
        (
            "hardcoded_half",
            "Half of the target cells are replaced by their correct cached values.",
            {key: case.reference_values[key] for key in case.target_cells[:half_count]},
            1.0,
        ),
        (
            "hardcoded_all",
            "Every target formula is replaced by its correct cached value.",
            {key: case.reference_values[key] for key in case.target_cells},
            1.0,
        ),
        (
            "fake_formula_final",
            "The final output is a formula-shaped constant with no cell dependencies.",
            {case.final_output: f"={_excel_number(expected_final)}"},
            1.0,
        ),
        (
            "wrong_formula_final",
            "The final output retains its original references but is 1% (plus one) too high.",
            # Relative, so the error stays outside the value tolerance for outputs in the
            # millions; the +1 keeps it wrong when the correct result is zero.
            {case.final_output: f"=({final_formula[1:]})*1.01+1"},
            (target_count - 1) / target_count,
        ),
        (
            "broken_reference_final",
            "The final output references a worksheet that does not exist.",
            {case.final_output: "='__MISSING_SHEET__'!A1"},
            (target_count - 1) / target_count,
        ),
        (
            "hardcoded_intermediate",
            "A formula feeding the final output is replaced by its correct cached value.",
            {intermediate: case.reference_values[intermediate]},
            1.0,
        ),
    )

    generated: list[GeneratedOutput] = []
    for name, purpose, changes, expected_value_score in variants:
        destination = output_dir / f"{name}.xlsx"
        mutations = _write_variant(case.golden_workbook, destination, changes)
        formula_coverage, traceability = _construction_scores(case, destination)
        generated.append(
            GeneratedOutput(
                variant=name,
                workbook=destination.name,
                purpose=purpose,
                mutations=mutations,
                expected_value_correctness_after_recalculation=expected_value_score,
                expected_formula_coverage=formula_coverage,
                expected_traceability=traceability,
            )
        )

    manifest = {
        "case_id": case.case_id,
        "source_golden": str(case.golden_workbook),
        "note": (
            "Formula-based outputs require Excel or LibreOffice recalculation before value checks."
        ),
        "outputs": [asdict(item) for item in generated],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return tuple(generated)


def find_intermediate_target(case: CaseSpec) -> str:
    """Return a formula target reached from the final output, excluding the output itself."""

    snapshot = read_workbook(case.golden_workbook)
    targets = set(case.target_cells)
    visited: set[str] = set()
    pending = [case.final_output]
    while pending:
        current = pending.pop(0)
        if current in visited:
            continue
        visited.add(current)
        observation = snapshot.observations.get(current)
        if observation is None or not observation.has_formula:
            continue
        dependencies = sorted(observation.precedents | observation.range_precedents)
        for dependency in dependencies:
            candidate = snapshot.observations.get(dependency)
            if (
                dependency != case.final_output
                and dependency in targets
                and candidate is not None
                and candidate.has_formula
                and dependency in case.reference_values
            ):
                return dependency
        pending.extend(dependencies)
    raise ValueError(f"case {case.case_id} has no formula target feeding {case.final_output}")


def _formula_at(workbook: Path, key: str) -> str | None:
    sheet, address = split_reference(key)
    book = openpyxl.load_workbook(workbook, data_only=False, keep_links=True)
    return formula_text(book[sheet][address].value)


def _write_variant(
    source: Path, destination: Path, changes: dict[str, Any]
) -> tuple[CellMutation, ...]:
    book = openpyxl.load_workbook(source, data_only=False, keep_links=True)
    mutations: list[CellMutation] = []
    for key, value in changes.items():
        sheet, address = split_reference(key)
        cell = book[sheet][address]
        before = formula_text(cell.value) or cell.value
        cell.value = value
        mutations.append(CellMutation(key, before, value))

    book.calculation.calcMode = "auto"
    book.calculation.fullCalcOnLoad = True
    book.calculation.forceFullCalc = True
    destination.parent.mkdir(parents=True, exist_ok=True)
    book.save(destination)
    return tuple(mutations)


def _construction_scores(case: CaseSpec, workbook: Path) -> tuple[float, float]:
    snapshot = read_workbook(workbook)
    target_count = len(case.target_cells)
    formula_count = sum(
        int(snapshot.observations.get(key) is not None and snapshot.observations[key].has_formula)
        for key in case.target_cells
    )
    breaks = trace_breaks(snapshot.observations.values(), case.input_cells, case.target_cells)
    traceable_count = sum(int(not breaks[key]) for key in case.target_cells)
    return formula_count / target_count, traceable_count / target_count


def _excel_number(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"expected a numeric final output, got {value!r}")
    return repr(value)
