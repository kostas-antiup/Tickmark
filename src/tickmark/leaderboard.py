"""Agent leaderboard: pilot-suite results per agent, and the tables shown in the docs.

Entries live in ``leaderboard/entries.json``. Each is one agent (a tool, a model, or both)
graded on the same pilot cases, so the rows compare like with like. ``real_models`` is
Tickmark's verdict (right numbers and every audit check); ``right_numbers`` is what a
value-only benchmark would count, so the gap between them is the point of the table.

Agents are ranked by real models, then by the share of all audit checks they passed (each
check counts once, so there are no invented weights), then by right numbers. Agents equal
on all three share a rank.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable, Mapping, Sequence
from html import escape
from pathlib import Path
from typing import Any

PILOT_CASES = ("02_01", "06_18", "14_07")
README_START = "<!-- leaderboard:start -->"
README_END = "<!-- leaderboard:end -->"
CHECKS = (
    "value_correctness",
    "formula_coverage",
    "traceability",
    "no_unexpected_hardcoded_values",
    "no_fake_formulas",
    "input_change_check",
    "perturbation_check",
)
_SCORES = ("value_correctness", "formula_coverage", "traceability")


def entry_from_records(
    records: Iterable[Mapping[str, Any]], agent: str, cases: Sequence[str] = PILOT_CASES
) -> dict[str, Any]:
    """Pilot statistics for ``agent`` from a run's ``summary.json`` records.

    Every case in ``cases`` must be in the run; a case the agent did not complete counts
    as failed, with zero scores and no checks passed.
    """

    by_case = {r["case_id"]: r for r in records if r["agent"] == agent}
    missing = [case for case in cases if case not in by_case]
    if missing:
        raise ValueError(f"run has no result for {agent!r} on case(s) {missing}")
    chosen = [by_case[case] for case in cases]
    scores = [r.get("scores") or {} for r in chosen]
    passed_checks = sum(
        sum(bool((r.get("checks") or {}).get(check)) for check in CHECKS) for r in chosen
    )
    return {
        "cases": len(chosen),
        "real_models": sum(r["outcome"] == "pass" for r in chosen),
        "right_numbers": sum(r["outcome"] in ("pass", "values only") for r in chosen),
        **{name: round(sum(s.get(name, 0.0) for s in scores) / len(chosen), 4) for name in _SCORES},
        "checks_passed": round(passed_checks / (len(CHECKS) * len(chosen)), 4),
        "median_seconds": round(statistics.median(r.get("duration_seconds") or 0 for r in chosen)),
    }


def _key(entry: Mapping[str, Any]) -> tuple[float, ...]:
    return (-entry["real_models"], -entry.get("checks_passed", 0.0), -entry["right_numbers"])


def ranked(entries: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Best first: real models, then checks passed, then right numbers; then by name."""

    return sorted(entries, key=lambda e: (*_key(e), label(e)))


def ranks(entries: Sequence[Mapping[str, Any]]) -> list[int]:
    """Competition ranks for already ``ranked`` entries: equal results share a rank."""

    return [1 + sum(_key(other) < _key(e) for other in entries) for e in entries]


def label(entry: Mapping[str, Any]) -> str:
    return f"{entry['name']} · {entry['model']}" if entry.get("model") else entry["name"]


def _pct(value: float) -> str:
    return f"{100 * value:.0f}%"


def table(entries: Iterable[Mapping[str, Any]]) -> str:
    """The Markdown leaderboard table."""

    rows = ranked(entries)
    lines = [
        "| # | Agent | Interface | Real models | Right numbers | Checks passed | Values right "
        "| Formulas | Traceable | Time per case |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for rank, e in zip(ranks(rows), rows, strict=True):
        lines.append(
            f"| {rank} | {label(e)} | {e['interface']} | **{e['real_models']} / {e['cases']}** | "
            f"{e['right_numbers']} / {e['cases']} | {_pct(e.get('checks_passed', 0.0))} | "
            f"{_pct(e['value_correctness'])} | {_pct(e['formula_coverage'])} | "
            f"{_pct(e['traceability'])} | {e.get('median_seconds', 0)} s |"
        )
    return "\n".join(lines)


# --- The leaderboard card (SVG), in the AAI Labs palette ---------------------------------

_SANS = "'DM Sans','IBM Plex Sans','Segoe UI',Helvetica,Arial,sans-serif"
_MONO = "'IBM Plex Mono',SFMono-Regular,Consolas,'Courier New',monospace"
_BLUE, _INK, _GREY, _MUTED = "#0000F0", "#0A0A0A", "#6B6C70", "#929397"
_HAIR, _TRACK, _WASH = "#E6E7EA", "#F1F2F4", "#F8F9FA"
_RANK_FILLS = ("#0000F0", "#3D3DF5", "#7B7BF8")  # ranks 1-3; the rest are outlined


def _bar_fill(value: float) -> str:
    if value >= 0.995:
        return _BLUE
    if value >= 0.6:
        return "#3D3DF5"
    if value >= 0.3:
        return "#9B9BF9"
    return _MUTED


def _text(
    x: float,
    y: float,
    content: str,
    size: float,
    fill: str = _INK,
    *,
    weight: int = 400,
    anchor: str = "start",
    family: str = _SANS,
    spacing: float = 0,
) -> str:
    track = f' letter-spacing="{spacing}"' if spacing else ""
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{track}>'
        f"{escape(content)}</text>"
    )


def svg_card(entries: Iterable[Mapping[str, Any]], cases: Sequence[str], updated: str) -> str:
    """The ranked leaderboard as a self-contained SVG card for the README."""

    rows = ranked(entries)
    width, top, row_h, bar_w = 1180, 138, 66, 104
    height = top + row_h * len(rows) + 76
    metrics = (
        ("checks_passed", "CHECKS PASSED", 520),
        ("value_correctness", "VALUES RIGHT", 654),
        ("formula_coverage", "FORMULAS", 788),
        ("traceability", "TRACEABLE", 922),
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="Tickmark agent leaderboard">',
        f'<rect x="0.5" y="0.5" width="{width - 1}" height="{height - 1}" rx="18" fill="#FFFFFF" '
        f'stroke="{_HAIR}"/>',
        _text(32, 46, "TICKMARK LEADERBOARD", 14, _BLUE, weight=600, family=_MONO, spacing=2.2),
        _text(32, 76, f"AI agents on the pilot cases {', '.join(cases)}", 18, _INK, weight=600),
        _text(
            width - 32,
            46,
            f"UPDATED {updated}",
            12,
            _MUTED,
            anchor="end",
            family=_MONO,
            spacing=1.5,
        ),
    ]
    headers = [("#", 58, "middle"), ("AGENT", 92, "start"), ("REAL MODELS", 382, "start")]
    headers += [(title, x + bar_w, "end") for _, title, x in metrics]
    headers.append(("TIME / CASE", width - 36, "end"))
    for title, x, anchor in headers:
        out.append(_text(x, 118, title, 11, _MUTED, anchor=anchor, family=_MONO, spacing=1.4))
    for rank, (index, e) in zip(ranks(rows), enumerate(rows), strict=True):
        y = top + index * row_h
        cy = y + row_h / 2
        if index % 2 == 0:
            out.append(
                f'<rect x="20" y="{y}" width="{width - 40}" height="{row_h}" rx="12" '
                f'fill="{_WASH}"/>'
            )
        if rank <= 3:
            out.append(f'<circle cx="58" cy="{cy}" r="17" fill="{_RANK_FILLS[rank - 1]}"/>')
            out.append(_text(58, cy + 5.5, str(rank), 16, "#FFFFFF", weight=700, anchor="middle"))
        else:
            out.append(f'<circle cx="58" cy="{cy}" r="16.5" fill="#FFFFFF" stroke="#D5D6D9"/>')
            out.append(_text(58, cy + 5.5, str(rank), 16, _GREY, weight=600, anchor="middle"))
        out.append(_text(92, cy - 3, label(e), 18, _INK, weight=600))
        out.append(_text(92, cy + 18, e["interface"], 13, _GREY))
        for k in range(e["cases"]):
            fill = _BLUE if k < e["real_models"] else _HAIR
            out.append(f'<circle cx="{389 + k * 19}" cy="{cy - 7}" r="6.5" fill="{fill}"/>')
        out.append(
            _text(
                389 + e["cases"] * 19 + 2,
                cy - 1.5,
                f"{e['real_models']}/{e['cases']}",
                17,
                _INK,
                weight=700,
            )
        )
        out.append(
            _text(
                382,
                cy + 18,
                f"right numbers {e['right_numbers']}/{e['cases']}",
                12,
                _GREY,
                family=_MONO,
            )
        )
        for key, _, x in metrics:
            value = float(e.get(key, 0.0))
            out.append(_text(x + bar_w, cy - 5, _pct(value), 16, _INK, weight=600, anchor="end"))
            out.append(
                f'<rect x="{x}" y="{cy + 6}" width="{bar_w}" height="8" rx="4" fill="{_TRACK}"/>'
            )
            if value > 0:
                out.append(
                    f'<rect x="{x}" y="{cy + 6}" width="{max(bar_w * value, 8):.1f}" '
                    f'height="8" rx="4" fill="{_bar_fill(value)}"/>'
                )
        out.append(
            _text(width - 36, cy + 5, f"{e.get('median_seconds', 0)} s", 16, _GREY, anchor="end")
        )
    out.append(
        _text(
            32,
            height - 42,
            "Real models: every number right and every audit check "
            "passed. Ranked by real models, then checks passed, then right numbers.",
            13,
            _GREY,
        )
    )
    out.append(
        _text(
            32,
            height - 22,
            "Time: median wall-clock seconds per case; free tiers include provider queueing.",
            13,
            _GREY,
        )
    )
    out.append("</svg>")
    return "\n".join(out) + "\n"


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
