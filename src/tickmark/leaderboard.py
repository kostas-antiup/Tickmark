"""Agent leaderboard: pilot-suite results per agent, and the tables shown in the docs.

Entries live in ``leaderboard/entries.json``. Each is one agent (a tool, a model, or both)
graded on the same pilot cases, so the rows compare like with like. ``real_models`` is
Tickmark's verdict (right numbers and every audit check); ``right_numbers`` is what a
value-only benchmark would count, so the gap between them is the point of the table.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

PILOT_CASES = ("02_01", "06_18", "14_07")
README_START = "<!-- leaderboard:start -->"
README_END = "<!-- leaderboard:end -->"
_SCORES = ("value_correctness", "formula_coverage", "traceability")


def entry_from_records(
    records: Iterable[Mapping[str, Any]], agent: str, cases: Sequence[str] = PILOT_CASES
) -> dict[str, Any]:
    """Pilot statistics for ``agent`` from a run's ``summary.json`` records.

    Every case in ``cases`` must be in the run; a case the agent did not complete counts
    as failed with zero scores.
    """

    by_case = {r["case_id"]: r for r in records if r["agent"] == agent}
    missing = [case for case in cases if case not in by_case]
    if missing:
        raise ValueError(f"run has no result for {agent!r} on case(s) {missing}")
    chosen = [by_case[case] for case in cases]
    scores = [r.get("scores") or {} for r in chosen]
    return {
        "cases": len(chosen),
        "real_models": sum(r["outcome"] == "pass" for r in chosen),
        "right_numbers": sum(r["outcome"] in ("pass", "values only") for r in chosen),
        **{name: round(sum(s.get(name, 0.0) for s in scores) / len(chosen), 4) for name in _SCORES},
    }


def ranked(entries: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Best first: real models, then right numbers, then the mean construction score."""

    def key(entry: Mapping[str, Any]) -> tuple[float, ...]:
        construction = sum(entry[name] for name in _SCORES) / len(_SCORES)
        return (-entry["real_models"], -entry["right_numbers"], -construction)

    return sorted(entries, key=key)


def _pct(value: float) -> str:
    return f"{100 * value:.0f}%"


def table(entries: Iterable[Mapping[str, Any]]) -> str:
    """The Markdown leaderboard table."""

    lines = [
        "| # | Agent | Interface | Real models | Right numbers | Formulas | Traceable |",
        "|---:|---|---|---:|---:|---:|---:|",
    ]
    for rank, e in enumerate(ranked(entries), start=1):
        agent = f"{e['name']} · {e['model']}" if e.get("model") else e["name"]
        real = f"{e['real_models']} / {e['cases']}"
        lines.append(
            f"| {rank} | {agent} | {e['interface']} | **{real}** | "
            f"{e['right_numbers']} / {e['cases']} | {_pct(e['formula_coverage'])} | "
            f"{_pct(e['traceability'])} |"
        )
    return "\n".join(lines)


def replace_between(text: str, block: str, start: str = README_START, end: str = README_END) -> str:
    """Put ``block`` between the ``start`` and ``end`` markers in ``text``."""

    head, found, rest = text.partition(start)
    if not found or end not in rest:
        raise ValueError(f"markers {start} ... {end} not found")
    return f"{head}{start}\n{block}\n{end}{rest.split(end, 1)[1]}"


def load_entries(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save_entries(path: Path, data: Mapping[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def upsert(entries: list[dict[str, Any]], entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Replace the entry with the same name and model, or append it."""

    same = [
        e for e in entries if (e["name"], e.get("model")) == (entry["name"], entry.get("model"))
    ]
    kept = [e for e in entries if e not in same]
    return [*kept, entry]
