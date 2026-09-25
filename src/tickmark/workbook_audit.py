"""Deterministic workbook construction grading primitives."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CellObservation:
    """Observed state for one workbook cell after formula extraction/evaluation.

    ``precedents`` holds cells the formula references directly (``=B2*B3``);
    ``range_precedents`` holds cells it reaches only through a range
    (``=SUM(C17:C19)``). Blank and label cells inside a range are skipped during
    tracing, whereas a direct reference to one is a broken chain.
    """

    address: str
    value: Any
    formula: str | None = None
    precedents: frozenset[str] = field(default_factory=frozenset)
    range_precedents: frozenset[str] = field(default_factory=frozenset)

    @property
    def has_formula(self) -> bool:
        return bool(self.formula and self.formula.lstrip().startswith("="))


@dataclass(frozen=True)
class WorkbookGrade:
    """Separate construction-quality axes for one submitted workbook."""

    value_correctness: float
    formula_coverage: float
    traceability: float


@dataclass(frozen=True, order=True)
class TraceBreak:
    """A point where a formula chain stops before reaching a declared input.

    ``kind`` is one of:

    - ``hardcoded_value``: a number that is neither a formula nor a declared input;
    - ``empty_cell``: an empty target, or a direct reference to an empty cell;
    - ``text_value``: a target holding text, or a direct reference to a label;
    - ``no_references``: a formula with nothing to trace (e.g. ``=9080487``);
    - ``circular_reference``: the chain loops back on itself.
    """

    cell: str
    kind: str


def values_match(
    actual: Any, expected: Any, *, abs_tolerance: float = 1e-9, rel_tolerance: float = 0.0
) -> bool:
    """Compare numbers within tolerance and everything else by equality."""

    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if isinstance(actual, bool) or isinstance(expected, bool):
            return actual == expected
        return (
            math.isfinite(actual)
            and math.isfinite(expected)
            and math.isclose(actual, expected, rel_tol=rel_tolerance, abs_tol=abs_tolerance)
        )
    return actual == expected


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _is_blank_or_label(observation: CellObservation | None) -> bool:
    if observation is None:
        return True
    if observation.has_formula:
        return False
    return observation.value is None or isinstance(observation.value, str)


class _InputTracer:
    """Finds every point where a cell's formula chain fails to reach declared inputs."""

    def __init__(self, observations: Mapping[str, CellObservation], input_cells: set[str]):
        self._observations = observations
        self._input_cells = input_cells
        self._results: dict[str, frozenset[TraceBreak]] = {}
        self._on_path: set[str] = set()

    def breaks(self, address: str) -> frozenset[TraceBreak]:
        if address in self._input_cells:
            return frozenset()
        if address in self._on_path:
            return frozenset({TraceBreak(address, "circular_reference")})
        if address in self._results:
            return self._results[address]
        observation = self._observations.get(address)
        if observation is None or (not observation.has_formula and observation.value in (None, "")):
            result = frozenset({TraceBreak(address, "empty_cell")})
        elif not observation.has_formula:
            kind = "text_value" if isinstance(observation.value, str) else "hardcoded_value"
            result = frozenset({TraceBreak(address, kind)})
        else:
            dependencies = set(observation.precedents) | {
                cell
                for cell in observation.range_precedents
                if not _is_blank_or_label(self._observations.get(cell))
            }
            if not dependencies:
                result = frozenset({TraceBreak(address, "no_references")})
            else:
                self._on_path.add(address)
                result = frozenset().union(*(self.breaks(cell) for cell in sorted(dependencies)))
                self._on_path.discard(address)
        self._results[address] = result
        return result


def reachable_cells(
    observations: Iterable[CellObservation], addresses: Iterable[str]
) -> dict[str, frozenset[str]]:
    """Every cell each address depends on, following formulas transitively.

    Blank and label cells inside ranges are skipped, as in tracing. Intersect the
    result with the input cells to get a cell's *input footprint*.
    """

    by_address = {observation.address: observation for observation in observations}
    memo: dict[str, frozenset[str]] = {}
    on_path: set[str] = set()

    def visit(address: str) -> frozenset[str]:
        if address in memo:
            return memo[address]
        observation = by_address.get(address)
        if address in on_path or observation is None or not observation.has_formula:
            return frozenset()
        dependencies = set(observation.precedents) | {
            cell
            for cell in observation.range_precedents
            if not _is_blank_or_label(by_address.get(cell))
        }
        on_path.add(address)
        found = frozenset(dependencies).union(*(visit(cell) for cell in dependencies))
        on_path.discard(address)
        memo[address] = found
        return found

    return {address: visit(address) for address in dict.fromkeys(addresses)}


def trace_breaks(
    observations: Iterable[CellObservation],
    input_cells: Iterable[str],
    target_cells: Iterable[str],
) -> dict[str, frozenset[TraceBreak]]:
    """Return, for each target, the points where its formula chain breaks.

    An empty set means every path from the target ends at a declared input.
    """

    by_address = {observation.address: observation for observation in observations}
    tracer = _InputTracer(by_address, set(input_cells))
    return {address: tracer.breaks(address) for address in dict.fromkeys(target_cells)}


def grade_workbook(
    observations: Iterable[CellObservation],
    reference_values: Mapping[str, Any],
    input_cells: Iterable[str],
    target_cells: Iterable[str],
    *,
    tolerance: float = 1e-9,
    rel_tolerance: float = 0.0,
) -> WorkbookGrade:
    """Grade values, formula construction, and input traceability separately."""

    by_address = {observation.address: observation for observation in observations}
    targets = list(dict.fromkeys(target_cells))
    value_correct = sum(
        int(
            address in by_address
            and address in reference_values
            and values_match(
                by_address[address].value,
                reference_values[address],
                abs_tolerance=tolerance,
                rel_tolerance=rel_tolerance,
            )
        )
        for address in targets
    )
    formulas = sum(
        int(by_address.get(address, CellObservation(address, None)).has_formula)
        for address in targets
    )
    breaks = trace_breaks(by_address.values(), input_cells, targets)
    traceable = sum(int(not breaks[address]) for address in targets)
    denominator = len(targets)
    return WorkbookGrade(
        value_correctness=_ratio(value_correct, denominator),
        formula_coverage=_ratio(formulas, denominator),
        traceability=_ratio(traceable, denominator),
    )
