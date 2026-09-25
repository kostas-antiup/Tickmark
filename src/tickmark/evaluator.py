"""Evaluate a submitted workbook against a benchmark case and explain the result."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .baselines import baseline_verdicts
from .cases import CaseSpec
from .recalculation import Recalculator
from .scenarios import (
    ScenarioPlan,
    evaluate_many,
    factor_scenario,
    one_at_a_time_expected,
    scenario_plan,
)
from .workbook_audit import (
    CellObservation,
    TraceBreak,
    grade_workbook,
    reachable_cells,
    trace_breaks,
    values_match,
)
from .workbook_reader import UNRESOLVED_PREFIX, read_workbook

# Literals that are ordinary unit conversions in financial models (months, days, %...).
# Only used for the informational embedded-constants warning, never for pass/fail.
BENIGN_LITERALS = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 10, 12, 24, 30, 52, 100, 360, 365, 1000})

CONSTRUCTION_CHECKS = (
    "formula_coverage",
    "traceability",
    "no_unexpected_hardcoded_values",
    "no_fake_formulas",
    "input_change_check",
    "perturbation_check",
)

_NEEDS_RECALCULATION = "(use the excel or libreoffice engine)"

_BREAK_TEXT = {
    "hardcoded_value": "hardcoded value",
    "empty_cell": "empty cell",
    "text_value": "text instead of a number",
    "no_references": "formula without cell references",
    "circular_reference": "circular reference",
}


@dataclass(frozen=True)
class CheckResult:
    """Outcome of one audit check; ``passed`` is ``None`` when the check was skipped."""

    passed: bool | None
    detail: str
    cells: tuple[str, ...] = ()
    score: float | None = None


@dataclass(frozen=True)
class EvaluationReport:
    """JSON-ready evaluation of one workbook for one case."""

    case_id: str
    workbook: str
    engine: str
    passed: bool
    correct: bool
    auditable: bool
    scores: dict[str, float]
    final_output: dict[str, Any]
    checks: dict[str, CheckResult]
    remarks: tuple[str, ...]
    warnings: tuple[str, ...]
    reader_issues: tuple[str, ...]
    input_differences: tuple[dict[str, Any], ...] = ()
    branch_coverage: dict[str, Any] | None = None
    sensitivity: tuple[dict[str, Any], ...] = ()
    # Verdicts of existing value-only benchmarks on the same workbook (``baselines``).
    baselines: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_workbook(
    case: CaseSpec, workbook: Path | str, engine: Recalculator, *, sensitivity: bool = False
) -> EvaluationReport:
    """Grade values, construction and auditability of ``workbook`` for ``case``.

    With ``sensitivity=True`` and a failed perturbation check, each input is also
    changed alone to name the inputs that make targets diverge (slower).
    """

    workbook = Path(workbook)
    snapshot = read_workbook(workbook)
    graded_cells = list(dict.fromkeys((*case.target_cells, *case.key_outputs)))
    # The comparison cells ride along in the same recalculation (no extra engine run).
    recalculated = _recalculate(
        case, workbook, engine, list(dict.fromkeys((*graded_cells, *case.comparison_cells)))
    )
    observations = dict(snapshot.observations)
    for key in graded_cells:
        if key in observations:
            observations[key] = replace(observations[key], value=recalculated.base[key])

    def value_of(key: str) -> Any:
        observation = observations.get(key)
        return None if observation is None else observation.value

    def matches(actual: Any, expected: Any) -> bool:
        return values_match(
            actual, expected, abs_tolerance=case.abs_tolerance, rel_tolerance=case.rel_tolerance
        )

    targets = case.target_cells
    grade = grade_workbook(
        observations.values(),
        case.reference_values,
        case.input_cells,
        targets,
        tolerance=case.abs_tolerance,
        rel_tolerance=case.rel_tolerance,
    )
    breaks = trace_breaks(observations.values(), case.input_cells, graded_cells)
    affected: dict[TraceBreak, list[str]] = {}
    for target in targets:
        for point in sorted(breaks[target]):
            affected.setdefault(point, []).append(target)

    wrong_values = [k for k in targets if not matches(value_of(k), case.reference_values.get(k))]
    without_formula = [k for k in targets if not _has_formula(observations.get(k))]
    untraced = [k for k in targets if breaks[k]]
    hardcoded = sorted({point.cell for point in affected if point.kind == "hardcoded_value"})
    fake = sorted({point.cell for point in affected if point.kind == "no_references"})
    embedded = _embedded_constants(case, targets, observations, snapshot.literals)
    perturbation, branch_coverage = _perturbation(case, engine, recalculated, matches)

    checks = {
        "value_correctness": CheckResult(
            grade.value_correctness == 1.0,
            f"{len(targets) - len(wrong_values)}/{len(targets)} target values match the reference.",
            tuple(wrong_values),
            grade.value_correctness,
        ),
        "formula_coverage": CheckResult(
            grade.formula_coverage == 1.0,
            f"{len(targets) - len(without_formula)}/{len(targets)} target cells contain formulas.",
            tuple(without_formula),
            grade.formula_coverage,
        ),
        "traceability": CheckResult(
            grade.traceability == 1.0,
            f"{len(targets) - len(untraced)}/{len(targets)} targets trace to declared inputs.",
            tuple(untraced),
            grade.traceability,
        ),
        "no_unexpected_hardcoded_values": CheckResult(
            not hardcoded,
            f"{len(hardcoded)} hardcoded value(s) inside target formula chains.",
            tuple(hardcoded),
        ),
        "no_fake_formulas": CheckResult(
            not fake,
            f"{len(fake)} formula(s) without any cell reference.",
            tuple(fake),
        ),
        "input_change_check": _input_change(case, engine, recalculated, value_of, matches),
        "perturbation_check": perturbation,
    }

    final = case.final_output
    final_report = {
        "cell": final,
        "expected": case.reference_values.get(final),
        "actual": value_of(final),
        "value_correct": matches(value_of(final), case.reference_values.get(final)),
        "has_formula": _has_formula(observations.get(final)),
        "traceable": not breaks[final],
    }
    correct = bool(checks["value_correctness"].passed)
    auditable = all(checks[name].passed is not False for name in CONSTRUCTION_CHECKS)
    remarks = _remarks(case, engine, observations, value_of, wrong_values, affected, checks)
    sensitivity_found: list[dict[str, Any]] = []
    if sensitivity and perturbation.passed is False:
        sensitivity_found = input_sensitivity(case, workbook, engine, matches)
        remarks += _sensitivity_remarks(sensitivity_found, perturbation.cells)
    differences = input_differences(case, observations)
    warnings = [
        _input_difference_text(target, missing, extra) for target, missing, extra in differences
    ] + [
        f"{key} embeds constant(s) {', '.join(_fmt(n) for n in numbers)} that the reference "
        f"model does not use: '{observations[key].formula}'. Review only; not graded."
        for key, numbers in embedded.items()
    ]
    return EvaluationReport(
        case_id=case.case_id,
        workbook=str(workbook),
        engine=engine.name,
        passed=correct and auditable,
        correct=correct,
        auditable=auditable,
        scores={
            "value_correctness": grade.value_correctness,
            "formula_coverage": grade.formula_coverage,
            "traceability": grade.traceability,
        },
        final_output=final_report,
        checks=checks,
        remarks=tuple(remarks),
        warnings=tuple(warnings),
        reader_issues=snapshot.issues,
        input_differences=tuple(
            {
                "cell": target,
                "missing": sorted(missing, key=_cell_order),
                "extra": sorted(extra, key=_cell_order),
            }
            for target, missing, extra in differences
        ),
        branch_coverage=branch_coverage,
        sensitivity=tuple(sensitivity_found),
        baselines=baseline_verdicts(
            case.answer_cells, case.sheet_cells, case.comparison_values, recalculated.base
        ),
    )


def _input_difference_text(target: str, missing: frozenset[str], extra: frozenset[str]) -> str:
    parts = []
    if missing:
        parts.append(f"does not use {_list(sorted(missing, key=_cell_order))}")
    if extra:
        parts.append(f"also uses {_list(sorted(extra, key=_cell_order))}")
    return (
        f"{target} {' and '.join(parts)}, unlike the reference model. "
        "Review only; the value checks decide whether this matters."
    )


def _has_formula(observation: CellObservation | None) -> bool:
    return observation is not None and observation.has_formula


def _embedded_constants(
    case: CaseSpec,
    targets: Iterable[str],
    observations: Mapping[str, CellObservation],
    literals: Mapping[str, tuple[float, ...]],
) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for key in targets:
        if not _has_formula(observations.get(key)):
            continue
        unusual = sorted(
            {
                abs(number)
                for number in literals.get(key, ())
                if abs(number) not in BENIGN_LITERALS and abs(number) not in case.reference_literals
            }
        )
        if unusual:
            found[key] = unusual
    return found


@dataclass(frozen=True)
class _Recalculated:
    """The submission's values as saved, after the input change, and under each scenario."""

    base: dict[str, Any]
    input_change: dict[str, Any] | None
    plan: ScenarioPlan | None
    scenarios: list[dict[str, Any]]


def _recalculate(
    case: CaseSpec, workbook: Path, engine: Recalculator, graded_cells: list[str]
) -> _Recalculated:
    """Every recalculation of the submission in one batch (one LibreOffice run)."""

    if not engine.supports_changes:
        return _Recalculated(engine.evaluate(workbook, graded_cells), None, None, [])
    plan = scenario_plan(case, engine)
    check = case.input_change
    change_sets: list[Mapping[str, Any]] = [{}]
    cells = list(graded_cells)
    if check is not None:
        change_sets.append({check.cell: check.perturbed_value})
        cells = list(dict.fromkeys((*cells, check.output_cell)))
    change_sets += [scenario.changes for scenario in plan.scenarios]
    results = evaluate_many(engine, workbook, cells, change_sets)
    first_scenario = 2 if check is not None else 1
    return _Recalculated(
        base=results[0],
        input_change=results[1] if check is not None else None,
        plan=plan,
        scenarios=results[first_scenario:],
    )


def _input_change(
    case: CaseSpec,
    engine: Recalculator,
    recalculated: _Recalculated,
    value_of: Callable[[str], Any],
    matches: Callable[[Any, Any], bool],
) -> CheckResult:
    check = case.input_change
    if check is None:
        return CheckResult(None, "Skipped: the case defines no input_change_check.")
    if recalculated.input_change is None:
        return CheckResult(
            None,
            f"Skipped: engine '{engine.name}' cannot recalculate after an input change "
            f"{_NEEDS_RECALCULATION}.",
        )
    before = value_of(check.output_cell)
    after = recalculated.input_change[check.output_cell]
    changed = isinstance(after, (int, float)) and not matches(after, before)
    passed = changed and matches(after, check.expected_after)
    detail = (
        f"Set {check.cell} to {_fmt(check.perturbed_value)}: {check.output_cell} went from "
        f"{_fmt(before)} to {_fmt(after)} (reference model: {_fmt(check.expected_before)} to "
        f"{_fmt(check.expected_after)})."
    )
    return CheckResult(passed, detail, (check.cell, check.output_cell))


def perturbation_changes(case: CaseSpec, scenario: str = "up") -> dict[str, Any]:
    """Input changes of one fixed scenario (``up``, ``down`` or ``mixed``); see ``scenarios``."""

    return dict(factor_scenario(case.golden_input_values, scenario).changes)


def _perturbation(
    case: CaseSpec,
    engine: Recalculator,
    recalculated: _Recalculated,
    matches: Callable[[Any, Any], bool],
) -> tuple[CheckResult, dict[str, Any] | None]:
    """Compare the submission with the reference model under every plan scenario.

    Returns the check and the branch coverage of the reference model's decisions.
    """

    plan = recalculated.plan
    if plan is None:
        skipped = CheckResult(
            None,
            f"Skipped: engine '{engine.name}' cannot recalculate changed inputs "
            f"{_NEEDS_RECALCULATION}.",
        )
        return skipped, None
    coverage = None
    if plan.decisions:
        coverage = {
            "decisions": len(plan.decisions),
            "tested_both_ways": sum(plan.covered),
            "untested": [decision.label for decision in plan.untested],
        }
    if not plan.scenarios:
        skipped = CheckResult(None, "Skipped: the reference model has no numeric inputs to change.")
        return skipped, coverage
    targets = list(case.target_cells)
    diverged: dict[str, list[str]] = {}
    for scenario, actual in zip(plan.scenarios, recalculated.scenarios, strict=True):
        expected = plan.expected[scenario.name]
        for key in targets:
            if not matches(actual.get(key), expected.get(key)):
                diverged.setdefault(key, []).append(scenario.name)
    fixed = [s.name for s in plan.scenarios if not s.name.startswith("branch-")]
    searched = len(plan.scenarios) - len(fixed)
    exposed = {name for names in diverged.values() for name in names}
    detail = (
        f"Compared under {len(plan.scenarios)} input scenarios ({', '.join(fixed)}"
        + (f", {searched} branch-seeking" if searched else "")
        + f"): {len(targets) - len(diverged)}/{len(targets)} targets match the reference model "
        "in every scenario."
        + (
            f" Diverged under: {', '.join(s.name for s in plan.scenarios if s.name in exposed)}."
            if exposed
            else ""
        )
        + (
            f" Reference decisions tested both ways: {coverage['tested_both_ways']}/"
            f"{coverage['decisions']}."
            if coverage
            else ""
        )
    )
    return CheckResult(not diverged, detail, tuple(diverged)), coverage


def input_sensitivity(
    case: CaseSpec,
    workbook: Path,
    engine: Recalculator,
    matches: Callable[[Any, Any], bool],
) -> list[dict[str, Any]]:
    """Change each input alone; list the inputs that make targets diverge from the reference."""

    plan = scenario_plan(case, engine)
    scenarios, expected = one_at_a_time_expected(case, engine, plan)
    targets = list(case.target_cells)
    results = evaluate_many(engine, workbook, targets, [s.changes for s in scenarios])
    found = []
    for scenario, actual in zip(scenarios, results, strict=True):
        wanted = expected[scenario.name]
        diverging = [key for key in targets if not matches(actual.get(key), wanted.get(key))]
        if diverging:
            found.append({"input": next(iter(scenario.changes)), "targets": diverging})
    return found


def _sensitivity_remarks(sensitivity: list[dict[str, Any]], diverged: Iterable[str]) -> list[str]:
    """Group targets that diverge for the same inputs into one readable line each."""

    triggers: dict[str, list[str]] = {}
    for entry in sensitivity:
        for target in entry["targets"]:
            triggers.setdefault(target, []).append(entry["input"])
    groups: dict[tuple[str, ...], list[str]] = {}
    for target, inputs in triggers.items():
        groups.setdefault(tuple(sorted(inputs, key=_cell_order)), []).append(target)
    remarks = [
        f"{_list(sorted(cells, key=_cell_order))} diverge from the reference when "
        f"{_or_list(list(inputs))} changes alone."
        for inputs, cells in sorted(groups.items(), key=lambda item: _cell_order(item[1][0]))
    ]
    unexplained = [target for target in diverged if target not in triggers]
    if unexplained:
        remarks.append(
            f"{_list(unexplained)} diverge only when several inputs change together "
            "(for example a different branch of IF/MIN/MAX logic)."
        )
    return remarks


def _or_list(cells: list[str], limit: int = 8) -> str:
    if len(cells) == 1:
        return cells[0]
    if len(cells) <= limit:
        return f"{', '.join(cells[:-1])} or {cells[-1]}"
    return f"{', '.join(cells[:limit])} or {len(cells) - limit} other inputs"


def input_differences(
    case: CaseSpec, observations: Mapping[str, CellObservation]
) -> list[tuple[str, frozenset[str], frozenset[str]]]:
    """Targets whose input footprint differs from the reference model's, at the root only.

    Returns ``(target, missing, extra)``: inputs the reference uses but the target
    does not, and inputs the target uses but the reference does not. A target is left
    out when the targets it depends on already explain its differences, and when it
    is empty, hardcoded or a formula without references (other checks report those).
    """

    if not case.reference_footprints:
        return []
    target_set = set(case.target_cells)
    reach = reachable_cells(observations.values(), case.target_cells)
    found = []
    for target in case.target_cells:
        ours = reach[target] & case.input_cells
        reference = case.reference_footprints.get(target, frozenset())
        missing, extra = reference - ours, ours - reference
        if missing or extra:
            found.append((target, missing, extra, reach[target] & target_set))
    reported: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for target, missing, extra, upstream in sorted(found, key=lambda item: len(item[3])):
        explained_missing = frozenset().union(*(reported[t][0] for t in upstream if t in reported))
        explained_extra = frozenset().union(*(reported[t][1] for t in upstream if t in reported))
        if missing <= explained_missing and extra <= explained_extra:
            continue
        reported[target] = (missing, extra)

    def real_formula(target: str) -> bool:
        observation = observations.get(target)
        return bool(
            observation is not None
            and observation.has_formula
            and (observation.precedents or observation.range_precedents)
        )

    return [
        (target, *reported[target])
        for target in case.target_cells
        if target in reported and real_formula(target)
    ]


def _cell_order(key: str) -> tuple[str, int, str]:
    sheet, _, address = key.rpartition("!")
    column = address.rstrip("0123456789")
    row = address[len(column) :]
    return sheet, int(row or 0), f"{len(column):02d}{column}"


def _remarks(
    case: CaseSpec,
    engine: Recalculator,
    observations: Mapping[str, CellObservation],
    value_of: Callable[[str], Any],
    wrong_values: list[str],
    affected: Mapping[TraceBreak, list[str]],
    checks: Mapping[str, CheckResult],
) -> list[str]:
    remarks: list[str] = []
    target_set = set(case.target_cells)

    by_kind: dict[str, list[str]] = {}
    for point in affected:
        if point.cell in target_set and point.kind in (
            "empty_cell",
            "hardcoded_value",
            "text_value",
        ):
            by_kind.setdefault(point.kind, []).append(point.cell)
    if by_kind.get("empty_cell"):
        remarks.append(f"Empty target cell(s): {_list(by_kind['empty_cell'])}.")
    if by_kind.get("hardcoded_value"):
        remarks.append(
            f"Target cell(s) hold hardcoded values instead of formulas: "
            f"{_list(by_kind['hardcoded_value'])}."
        )
    if by_kind.get("text_value"):
        remarks.append(
            f"Target cell(s) hold text instead of numbers: {_list(by_kind['text_value'])}."
        )

    for point, targets in sorted(affected.items()):
        others = [target for target in targets if target != point.cell]
        if not others:
            continue
        if point.kind == "no_references":
            formula = observations[point.cell].formula
            what = f"{point.cell} is a formula without cell references ('{formula}')"
        elif point.cell.startswith(UNRESOLVED_PREFIX):
            what = f"unresolved reference {point.cell[len(UNRESOLVED_PREFIX) :]}"
        else:
            what = f"{point.cell} ({_BREAK_TEXT[point.kind]})"
        remarks.append(f"Formula chain broken at {what}; affects {_list(others)}.")

    for key in (point.cell for point in affected if point.kind == "no_references"):
        if key in target_set and len(affected.get(TraceBreak(key, "no_references"), [])) <= 1:
            remarks.append(
                f"{key} is a formula without cell references ('{observations[key].formula}')."
            )

    if wrong_values:
        shown = [
            f"{key} = {_fmt(value_of(key))} (expected {_fmt(case.reference_values.get(key))})"
            for key in wrong_values[:5]
        ]
        more = f" and {len(wrong_values) - 5} more" if len(wrong_values) > 5 else ""
        remarks.append(f"Wrong value(s): {'; '.join(shown)}{more}.")
        uncalculated = [
            key
            for key in wrong_values
            if _has_formula(observations.get(key)) and value_of(key) is None
        ]
        if uncalculated and not engine.supports_changes:
            remarks.append(
                f"{len(uncalculated)} formula target(s) have no saved value; the file was probably "
                f"never recalculated {_NEEDS_RECALCULATION}."
            )

    change = checks["input_change_check"]
    if change.passed is False:
        remarks.append(f"Input-change check failed. {change.detail}")
    perturbation = checks["perturbation_check"]
    stale = [key for key in perturbation.cells if key not in set(wrong_values)]
    if stale:
        remarks.append(
            f"Correct only for the given inputs: {_list(stale)} stop matching the reference model "
            "when inputs change (hidden hardcoded or input-independent logic)."
        )
    return remarks


def _list(cells: list[str], limit: int = 8) -> str:
    shown = ", ".join(cells[:limit])
    return shown + (f" and {len(cells) - limit} more" if len(cells) > limit else "")


def _fmt(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return repr(value)
    return f"{value:,.8g}"  # 8 significant digits: readable, yet close values stay distinct
