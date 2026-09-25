"""Self-contained HTML report for one benchmark run, in the AAI Labs visual style.

The page embeds its fonts and logo (``report_assets/``), so ``report.html`` can be
opened from disk, attached to an e-mail or published as-is. Charts are plain
HTML/CSS; every value in a chart is also printed as text or available in a table.
"""

from __future__ import annotations

import base64
import statistics
from collections.abc import Callable, Sequence
from datetime import datetime
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING

from .baselines import GRADER_LABELS, GRADERS

if TYPE_CHECKING:
    from .benchmark_run import RunRecord

ASSETS = Path(__file__).with_name("report_assets")
OURS = "ours"  # this benchmark's own verdict in the grader comparison

# Outcome classes: one brand hue plus greys. Solid blue = the goal, pale blue = the gap
# the benchmark exists to expose (right numbers, no real model), greys = the rest.
OUTCOME_CLASSES = (
    ("pass", "Pass", "Right numbers from an auditable, formula-driven model."),
    ("values", "Values only", "Right numbers, but hardcoded or not a live model."),
    ("wrong", "Wrong", "At least one number differs from the reference model."),
    ("none", "No result", "The agent failed, produced no workbook, or is still pending."),
)

CHECK_LABELS = {
    "value_correctness": "Correct values",
    "formula_coverage": "Formulas in all target cells",
    "traceability": "Traces back to inputs",
    "no_unexpected_hardcoded_values": "No hardcoded numbers",
    "no_fake_formulas": "No fake formulas",
    "input_change_check": "Reacts to an input change",
    "perturbation_check": "Holds up with new inputs",
}

FAMILY_LABELS = {
    "02_cash_sweep": "Cash sweep & debt waterfall",
    "04_dcf_valuation": "DCF valuation",
    "06_equity_forecast": "Equity research forecast",
    "08_fin_model_basics": "Financial model basics",
    "09_lbo_model": "LBO debt schedule",
    "10_ma_analysis": "M&A accretion / dilution",
    "11_ma_model": "M&A model",
    "13_nonrecurring": "Earnings normalisation",
    "14_re_dcf": "Real estate DCF",
    "16_re_direct_cap": "Real estate direct cap",
}

SIZE_BUCKETS = ((30, "Up to 30 cells"), (60, "31–60 cells"), (100, "61–100 cells"))
LARGEST_BUCKET = "Over 100 cells"
ENGINE_LABELS = {"excel": "Excel", "libreoffice": "LibreOffice", "cached": "saved values"}


def outcome_class(outcome: str) -> str:
    if outcome == "pass":
        return "pass"
    if outcome == "values only":
        return "values"
    if outcome in ("fail", "auditable, wrong values"):
        return "wrong"
    return "none"


def _outcome_label(outcome: str) -> str:
    """Report label for a run outcome; runs without a result keep their own status."""

    key = outcome_class(outcome)
    if key == "none":
        return outcome.capitalize()
    return next(label for k, label, _ in OUTCOME_CLASSES if k == key)


def _input_hint(record: RunRecord) -> str | None:
    """Most specific input hint: a one-at-a-time diagnosis, else an input-footprint difference."""

    for remark in record.remarks:
        if remark.endswith("changes alone."):
            return remark
    for warning in record.warnings:
        if "unlike the reference model" in warning:
            return warning.split(", unlike the reference model")[0] + "."
    return None


def family_label(family: str) -> str:
    if family in FAMILY_LABELS:
        return FAMILY_LABELS[family]
    name = family.split("_", 1)[-1] if family[:2].isdigit() else family
    return name.replace("_", " ").capitalize() or "Other"


def size_bucket(n_targets: int) -> str:
    for limit, label in SIZE_BUCKETS:
        if n_targets <= limit:
            return label
    return LARGEST_BUCKET


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.0f}%" if whole else "–"


def _attr(text: str) -> str:
    return escape(text, quote=True).replace("\n", "&#10;")


class _AgentStats:
    def __init__(self, name: str, records: list[RunRecord]) -> None:
        self.name = name
        self.records = records
        self.n = len(records)
        self.counts = {key: 0 for key, *_ in OUTCOME_CLASSES}
        for record in records:
            self.counts[outcome_class(record.outcome)] += 1
        self.graded = [record for record in records if record.scores is not None]
        self.correct = self.counts["pass"] + self.counts["values"]
        self.passed = self.counts["pass"]
        durations = [r.duration_seconds for r in records if r.duration_seconds]
        self.median_seconds = statistics.median(durations) if durations else None

    def check_rate(self, check: str) -> tuple[int, int] | None:
        results = [
            r.checks[check] for r in self.graded if r.checks and r.checks.get(check) is not None
        ]
        return (sum(bool(v) for v in results), len(results)) if results else None

    def pass_rate(self, keep: Callable[[RunRecord], bool]) -> tuple[int, int] | None:
        chosen = [r for r in self.records if keep(r)]
        return (sum(r.outcome == "pass" for r in chosen), len(chosen)) if chosen else None

    def grader_rate(self, grader: str) -> tuple[int, int] | None:
        """Workbooks an existing grader passes (``ours`` = this benchmark), of those it graded."""

        if grader == OURS:
            chosen = [r for r in self.graded if r.baselines]
            return (sum(r.outcome == "pass" for r in chosen), len(chosen)) if chosen else None
        verdicts = [r.baselines[grader] for r in self.graded if grader in r.baselines]
        return (sum(verdicts), len(verdicts)) if verdicts else None

    def disagreements(self, grader: str) -> tuple[int, int]:
        """(accepted by ``grader`` but not a real model, real model rejected by ``grader``)."""

        chosen = [r for r in self.graded if grader in r.baselines]
        accepted = sum(r.baselines[grader] and r.outcome != "pass" for r in chosen)
        rejected = sum(r.outcome == "pass" and not r.baselines[grader] for r in chosen)
        return accepted, rejected

    def strongest_domain(self) -> str | None:
        """Domain with the best pass rate, shrunk towards 50% so 2/2 does not beat 9/10."""

        rates = []
        for family in {r.family for r in self.records}:
            rate = self.pass_rate(lambda r, f=family: r.family == f)
            if rate and rate[0]:
                passed, total = rate
                rates.append(((passed + 1) / (total + 2), total, family, rate))
        if not rates:
            return None
        _, _, family, (passed, total) = max(rates)
        return f"{family_label(family)} ({passed}/{total})"

    def weakest_check(self) -> str | None:
        rates = [
            (rate[0] / rate[1], label)
            for check, label in CHECK_LABELS.items()
            if (rate := self.check_rate(check)) is not None
        ]
        if not rates:
            return None
        share, label = min(rates)
        return None if share == 1 else f"{label.lower()} ({share:.0%})"


def write_html_report(run_dir: Path, records: Sequence[RunRecord], engine: str) -> Path:
    """Write ``report.html`` for the run and return its path."""

    by_agent: dict[str, list[RunRecord]] = {}
    for record in records:
        by_agent.setdefault(record.agent, []).append(record)
    stats = [_AgentStats(name, rows) for name, rows in by_agent.items()]
    cases = sorted({record.case_id for record in records})

    sections = [
        (
            "Right numbers vs real models",
            "Hollow dot: every number correct. Solid dot: also an auditable model. "
            "The line between them is the gap answer-matching cannot see.",
            _dumbbell(stats),
        ),
    ]
    if any(record.baselines for record in records):
        sections.append(
            (
                "Same workbooks, existing benchmarks",
                "Share of graded workbooks each grader passes. Existing benchmarks compare "
                "final values only, so they also pass pasted numbers.",
                _grader_comparison(stats),
            )
        )
    sections += [
        ("Agent by agent", "", _agent_rows(stats)),
        (
            "Where agents slip",
            "Share of graded workbooks that pass each audit check.",
            _heatmap(
                "Check",
                [(label, key) for key, label in CHECK_LABELS.items()],
                stats,
                lambda key, s: s.check_rate(key),
            ),
        ),
        (
            "Where agents do well",
            "Share of cases passed, by kind of model and by size.",
            '<div class="split">'
            + _heatmap(
                "Model type",
                [(family_label(f), f) for f in sorted({r.family for r in records})],
                stats,
                lambda key, s: s.pass_rate(lambda r: r.family == key),
            )
            + _heatmap(
                "Cells to fill",
                [(label, label) for _, label in SIZE_BUCKETS] + [(LARGEST_BUCKET, LARGEST_BUCKET)],
                stats,
                lambda key, s: s.pass_rate(lambda r: size_bucket(r.n_targets) == key),
                skip_empty_rows=True,
            )
            + "</div>",
        ),
        (
            "Every case",
            "",
            f'<details class="more"><summary>Show all {len(cases)} cases</summary>'
            f"{_case_matrix(stats, records)}</details>",
        ),
        ("Why cases did not pass", "", _failure_details(stats)),
    ]
    body = [
        _masthead(run_dir.name),
        _hero(stats, len(cases), engine),
        *(
            _section(f"{number:02d}", title, subtitle, content)
            for number, (title, subtitle, content) in enumerate(sections, start=1)
        ),
        _footer(),
    ]
    page = (
        _HEAD.replace("__TITLE__", escape(f"Tickmark run {run_dir.name}")).replace(
            "__FONTS__", _font_faces()
        )
        + "\n".join(body)
        + _TAIL
    )
    path = run_dir / "report.html"
    path.write_text(page, encoding="utf-8")
    return path


def _font_faces() -> str:
    faces = (
        ("DM Sans", "dm-sans.woff", "100 1000"),
        ("IBM Plex Sans", "ibm-plex-sans.woff", "100 700"),
        ("IBM Plex Mono", "ibm-plex-mono-500.woff", "400 500"),
        ("IBM Plex Mono", "ibm-plex-mono-600.woff", "600 700"),
    )
    css = []
    for family, file, weight in faces:
        path = ASSETS / file
        if path.exists():
            data = base64.b64encode(path.read_bytes()).decode("ascii")
            css.append(
                f'@font-face{{font-family:"{family}";src:url(data:font/woff;base64,{data}) '
                f'format("woff");font-weight:{weight};font-style:normal;font-display:swap}}'
            )
    return "\n".join(css)


def _logo() -> str:
    path = ASSETS / "aai-labs-wordmark.svg"
    return path.read_text(encoding="utf-8") if path.exists() else "<strong>AAI Labs</strong>"


def _masthead(run: str) -> str:
    stamp = datetime.now().strftime("%d %b %Y").upper()
    return (
        f'<header class="masthead"><span class="logo">{_logo()}</span>'
        f'<span class="mono muted">RUN {escape(run.upper())} · {stamp}</span></header>'
    )


def _hero(stats: list[_AgentStats], n_cases: int, engine: str) -> str:
    total = sum(s.n for s in stats)
    graded = sum(len(s.graded) for s in stats)
    correct = sum(s.correct for s in stats)
    passed = sum(s.passed for s in stats)
    hidden = sum(s.counts["values"] for s in stats)
    if not total:
        headline = "No cases attempted yet."
    elif not graded:
        headline = "No graded workbooks yet."
    elif correct == passed:
        headline = f"{_pct(passed, total)} got it right — with real models."
    else:
        headline = (
            f"{_pct(correct, total)} had the right numbers.<br>"
            f'<span class="accent">{_pct(passed, total)} were real models.</span>'
        )
    agents = f"{len(stats)} agent{'s' * (len(stats) != 1)}"
    lede = (
        f"{agents} · {n_cases} financial models · every workbook recalculated in "
        f"{ENGINE_LABELS.get(engine, escape(engine))} and audited against a hidden reference."
    )
    kpis = [
        ("Right numbers", _pct(correct, total), f"{correct} of {total} workbooks"),
        ("Real models", _pct(passed, total), f"{passed} of {total} pass the audit"),
        ("Right numbers, no model", str(hidden), "missed by answer-matching"),
    ]
    tiles = "".join(
        f'<div class="kpi"><span class="label">{label}</span><span class="kpi-value">{value}'
        f'</span><span class="kpi-note">{note}</span></div>'
        for label, value, note in kpis
    )
    return (
        f'<section class="hero"><span class="label accent">Tickmark · by AAI Labs</span>'
        f'<h1>{headline}</h1><p class="lede">{lede}</p><div class="kpis">{tiles}</div></section>'
    )


def _section(number: str, title: str, subtitle: str, content: str) -> str:
    sub = f'<p class="sub">{subtitle}</p>' if subtitle else ""
    return (
        f'<section class="block"><div class="block-head"><span class="num">{number}</span>'
        f"<h2>{title}</h2></div>{sub}{content}</section>"
    )


def _empty() -> str:
    return '<p class="muted">Nothing to show yet.</p>'


def _dumbbell(stats: list[_AgentStats]) -> str:
    if not stats:
        return _empty()
    ticks = "".join(
        f'<span class="db-tick" style="left:{t}%">{t}%</span>' for t in (0, 25, 50, 75, 100)
    )
    grid = "".join(f'<i class="db-grid" style="left:{t}%"></i>' for t in (0, 25, 50, 75, 100))
    rows = [f'<div class="db-row db-axis"><span></span><div class="db-track">{ticks}</div></div>']
    for s in stats:
        value = 100 * s.correct / s.n if s.n else 0
        audit = 100 * s.passed / s.n if s.n else 0
        tip = (
            f"{s.name}\nRight numbers: {s.correct}/{s.n} ({_pct(s.correct, s.n)})\n"
            f"Real models: {s.passed}/{s.n} ({_pct(s.passed, s.n)})"
        )
        if value - audit < 8:
            text = (
                _pct(s.correct, s.n)
                if s.correct == s.passed
                else (f"{_pct(s.passed, s.n)} → {_pct(s.correct, s.n)}")
            )
            labels = f'<span class="db-val right" style="left:{value:.1f}%">{text}</span>'
        else:
            labels = (
                f'<span class="db-val left strong" style="left:{audit:.1f}%">'
                f"{_pct(s.passed, s.n)}</span>"
                f'<span class="db-val right" style="left:{value:.1f}%">'
                f"{_pct(s.correct, s.n)}</span>"
            )
        rows.append(
            f'<div class="db-row" tabindex="0" data-tip="{_attr(tip)}">'
            f'<span class="db-name">{escape(s.name)}</span><div class="db-track">{grid}'
            f'<i class="db-gap" style="left:{audit:.1f}%;width:{value - audit:.1f}%"></i>'
            f'<i class="db-dot value" style="left:{value:.1f}%"></i>'
            f'<i class="db-dot audit" style="left:{audit:.1f}%"></i>{labels}</div></div>'
        )
    legend = (
        '<div class="legend"><span><i class="key-dot audit"></i>Real model (passes the audit)'
        '</span><span><i class="key-dot value"></i>Right numbers (value-only grading)</span></div>'
    )
    return legend + f'<div class="dumbbell">{"".join(rows)}</div>'


def _agent_rows(stats: list[_AgentStats]) -> str:
    if not stats:
        return _empty()
    legend = (
        '<div class="legend">'
        + "".join(
            f'<span title="{_attr(text)}"><i class="key out-{key}"></i>{label}</span>'
            for key, label, text in OUTCOME_CLASSES
        )
        + "</div>"
    )
    rows = []
    for s in stats:
        segments = []
        for key, label, _ in OUTCOME_CLASSES:
            count = s.counts[key]
            if not count:
                continue
            inside = str(count) if count / s.n >= 0.06 else ""
            tip = f"{s.name}\n{label}: {count} of {s.n} ({_pct(count, s.n)})"
            segments.append(
                f'<span class="seg out-{key}" style="flex-grow:{count}" tabindex="0" '
                f'data-tip="{_attr(tip)}">{inside}</span>'
            )
        notes = []
        if (strong := s.strongest_domain()) is not None:
            notes.append(f"<span><b>Strongest</b> {escape(strong)}</span>")
        if (weak := s.weakest_check()) is not None:
            notes.append(f"<span><b>Weakest check</b> {escape(weak)}</span>")
        rows.append(
            f'<div class="agent"><div class="agent-head"><span class="agent-name">'
            f'{escape(s.name)}</span><span class="agent-score"><b>{_pct(s.passed, s.n)}</b> '
            f"real models</span></div>"
            f'<div class="bar">{"".join(segments)}</div>'
            f'<div class="agent-notes">{"".join(notes)}</div></div>'
        )
    return legend + "".join(rows) + _table_view(stats)


def _table_view(stats: list[_AgentStats]) -> str:
    head = (
        "<tr><th>Agent</th><th>Cases</th><th>Pass</th><th>Values only</th><th>Wrong</th>"
        "<th>No result</th><th>Median time</th></tr>"
    )
    body = "".join(
        f'<tr><th scope="row">{escape(s.name)}</th><td>{s.n}</td>'
        + "".join(f"<td>{s.counts[key]}</td>" for key, *_ in OUTCOME_CLASSES)
        + f"<td>{'' if s.median_seconds is None else f'{s.median_seconds:.0f}s'}</td></tr>"
        for s in stats
    )
    return (
        '<details class="more"><summary>Table view</summary><div class="scroll">'
        f'<table class="data"><thead>{head}</thead><tbody>{body}</tbody></table></div></details>'
    )


def _heatmap(
    corner: str,
    rows: list[tuple[str, str]],
    stats: list[_AgentStats],
    rate: Callable[[str, _AgentStats], tuple[int, int] | None],
    *,
    skip_empty_rows: bool = False,
) -> str:
    if not stats:
        return _empty()
    head = f"<tr><th>{corner}</th>" + "".join(f"<th>{escape(s.name)}</th>" for s in stats) + "</tr>"
    body = []
    for label, key in rows:
        values = [rate(key, s) for s in stats]
        if skip_empty_rows and all(v is None for v in values):
            continue
        cells = []
        for s, value in zip(stats, values, strict=True):
            if value is None:
                cells.append('<td class="heat empty">–</td>')
                continue
            passed, total = value
            share = passed / total
            ink = "#ffffff" if share >= 0.55 else "var(--ink)"
            tip = f"{s.name} · {label}\n{passed} of {total} ({_pct(passed, total)})"
            cells.append(
                f'<td class="heat" tabindex="0" data-tip="{_attr(tip)}" style="background:'
                f"color-mix(in oklab, var(--blue-600) {share * 100:.0f}%, #ffffff);"
                f'color:{ink}">{_pct(passed, total)}</td>'
            )
        body.append(f'<tr><th scope="row">{escape(label)}</th>{"".join(cells)}</tr>')
    return (
        f'<div class="scroll"><table class="heatmap"><thead>{head}</thead>'
        f"<tbody>{''.join(body)}</tbody></table>"
        '<div class="scale"><span>0%</span><i></i><span>100%</span></div></div>'
    )


def _grader_comparison(stats: list[_AgentStats]) -> str:
    rows = [(GRADER_LABELS[grader], grader) for grader in GRADERS]
    heat = _heatmap(
        "Grader", [*rows, ("This benchmark", OURS)], stats, lambda key, s: s.grader_rate(key)
    )
    notes = []
    for s in stats:
        parts = []
        for grader in GRADERS:
            accepted, rejected = s.disagreements(grader)
            label = GRADER_LABELS[grader]
            if accepted:
                parts.append(f"<b>{accepted}</b> passed by {label} grading but not real models")
            if rejected:
                parts.append(f"<b>{rejected}</b> real models failed by {label} grading")
        if parts:
            notes.append(f"<li><span>{escape(s.name)}</span> {' · '.join(parts)}</li>")
    listing = f'<ul class="grader-notes">{"".join(notes)}</ul>' if notes else ""
    return heat + listing


def _case_matrix(stats: list[_AgentStats], records: Sequence[RunRecord]) -> str:
    lookup = {(r.agent, r.case_id): r for r in records}
    info = {r.case_id: (r.family, r.n_targets) for r in records}
    groups: dict[str, list[str]] = {}
    for case_id in sorted(info):
        groups.setdefault(info[case_id][0], []).append(case_id)
    head = (
        "<tr><th>Case</th><th>Cells</th>"
        + "".join(f"<th>{escape(s.name)}</th>" for s in stats)
        + "</tr>"
    )
    body = []
    for family in sorted(groups, key=family_label):
        body.append(
            f'<tr class="group"><th colspan="{len(stats) + 2}">{escape(family_label(family))}'
            "</th></tr>"
        )
        for case_id in groups[family]:
            cells = []
            for s in stats:
                record = lookup.get((s.name, case_id))
                if record is None:
                    cells.append("<td></td>")
                    continue
                key = outcome_class(record.outcome)
                label = _outcome_label(record.outcome)
                detail = record.remarks[0] if record.remarks else (record.error or "")
                if hint := _input_hint(record):
                    detail = f"{detail}\n{hint}"
                failed = (
                    f"\nFailed: {', '.join(record.failed_checks)}" if record.failed_checks else ""
                )
                tip = f"{s.name} · {case_id}: {record.outcome}{failed}\n{detail}".strip()
                cells.append(
                    f'<td><span class="pill out-{key}" tabindex="0" data-tip="{_attr(tip)}">'
                    f"{escape(label)}</span></td>"
                )
            body.append(
                f'<tr><th scope="row" class="mono">{escape(case_id)}</th>'
                f'<td class="mono muted">{info[case_id][1] or ""}</td>{"".join(cells)}</tr>'
            )
    return (
        f'<div class="scroll"><table class="data cases"><thead>{head}</thead>'
        f"<tbody>{''.join(body)}</tbody></table></div>"
    )


def _failure_details(stats: list[_AgentStats]) -> str:
    if not stats:
        return _empty()
    blocks = []
    for s in stats:
        failing = [r for r in s.records if r.outcome != "pass"]
        if not failing:
            blocks.append(f'<p class="muted">{escape(s.name)}: every case passed.</p>')
            continue
        items = "".join(
            f'<li><span class="mono">{escape(r.case_id)}</span> <span class="pill out-'
            f'{outcome_class(r.outcome)}">{escape(_outcome_label(r.outcome))}</span>'
            f'<span class="reason">{escape((r.remarks or [r.error or r.status])[0])}'
            + (f"<small>{escape(hint)}</small>" if (hint := _input_hint(r)) else "")
            + "</span></li>"
            for r in failing
        )
        blocks.append(
            f'<details class="more"><summary>{escape(s.name)} · {len(failing)} of {s.n} '
            f'cases</summary><ul class="reasons">{items}</ul></details>'
        )
    return "".join(blocks)


def _footer() -> str:
    outcomes = "".join(
        f'<li><span class="pill out-{key}">{label}</span>{text}</li>'
        for key, label, text in OUTCOME_CLASSES
    )
    checks = " · ".join(CHECK_LABELS.values())
    return (
        '<footer class="method"><span class="label">How to read this report</span>'
        "<p>Each agent got only the empty template and the task. We recalculate its workbook "
        "and compare it with a hidden reference model. Answer-matching benchmarks stop at the "
        "numbers; this one also checks that a client could audit and reuse the model.</p>"
        f'<ul class="outcomes">{outcomes}</ul>'
        f'<p class="muted small"><b>Audit checks</b> · {checks}</p>'
        '<p class="muted small">Generated by Tickmark, the AAI Labs benchmark for financial-model'
        " construction · github.com/kostas-antiup/Tickmark"
        "</p></footer>"
    )


_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
__FONTS__
:root {
  color-scheme: light;
  --blue-50: #f0f0ff; --blue-200: #c6c7f8; --blue-600: #0000f0; --blue-700: #0a0dc2;
  --ink: #0a0a0a; --grey-700: #45464b; --grey-600: #6b6c70; --grey-500: #929397;
  --grey-300: #d5d6d9; --grey-200: #e6e7ea; --grey-100: #f1f2f4; --grey-50: #f8f9fa;
  --font-display: "DM Sans", "IBM Plex Sans", system-ui, sans-serif;
  --font-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --font-mono: "IBM Plex Mono", ui-monospace, "Cascadia Mono", Consolas, monospace;
  --shadow-md: 0 4px 16px rgba(10,10,10,0.06), 0 1px 3px rgba(10,10,10,0.05);
  --ease: cubic-bezier(0.2, 0, 0, 1);
}
* { box-sizing: border-box; }
body { margin: 0; background: #ffffff; color: var(--grey-700); font: 17px/1.55 var(--font-body);
  -webkit-font-smoothing: antialiased; }
main { max-width: 1200px; margin: 0 auto; padding: 28px 32px 80px; }
h1, h2 { font-family: var(--font-display); color: var(--ink); font-weight: 800;
  letter-spacing: -0.02em; margin: 0; text-wrap: balance; }
h1 { font-size: clamp(38px, 5.4vw, 64px); line-height: 1.04; max-width: 17ch; }
h2 { font-size: clamp(26px, 3vw, 33px); line-height: 1.15; }
.mono { font-family: var(--font-mono); }
.label { font-family: var(--font-mono); font-size: 13px; font-weight: 500; letter-spacing: 0.14em;
  text-transform: uppercase; color: var(--grey-500); }
.accent, .label.accent { color: var(--blue-600); }
.muted { color: var(--grey-500); }
.small { font-size: 14px; }
.masthead { display: flex; justify-content: space-between; align-items: center; gap: 16px;
  flex-wrap: wrap; padding-bottom: 20px; border-bottom: 1px solid var(--grey-200); }
.masthead .mono { font-size: 13px; letter-spacing: 0.12em; }
.logo { color: var(--blue-600); display: inline-flex; height: 28px; }
.logo svg { height: 100%; width: auto; display: block; }
.hero { padding: 56px 0 24px; }
.hero h1 { margin: 14px 0 18px; }
.lede { font-size: 20px; color: var(--grey-700); max-width: 60ch; margin: 0; }
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 16px;
  margin-top: 36px; }
.kpi { border: 1px solid var(--grey-200); border-radius: 14px; padding: 22px 24px;
  display: grid; gap: 6px; }
.kpi-value { font-family: var(--font-mono); font-weight: 600; font-size: 52px; line-height: 1;
  color: var(--ink); letter-spacing: -0.02em; }
.kpi:nth-child(2) .kpi-value { color: var(--blue-600); }
.kpi-note { font-size: 15px; color: var(--grey-600); }
.block { margin-top: 40px; padding: 32px; border-radius: 14px; background: #ffffff;
  box-shadow: var(--shadow-md); border: 1px solid var(--grey-100); }
.block-head { display: flex; align-items: baseline; gap: 14px; }
.num { font-family: var(--font-mono); font-size: 16px; color: var(--blue-600); font-weight: 500; }
.sub { margin: 10px 0 0; color: var(--grey-600); font-size: 17px; max-width: 70ch; }
.legend { display: flex; flex-wrap: wrap; gap: 8px 24px; margin: 24px 0 12px; font-size: 15px;
  color: var(--grey-700); }
.legend span { display: inline-flex; align-items: center; gap: 8px; }
.key { width: 14px; height: 14px; border-radius: 4px; display: inline-block; }
.key-dot { width: 14px; height: 14px; border-radius: 50%; display: inline-block; }
.key-dot.audit, .db-dot.audit { background: var(--blue-600); }
.key-dot.value, .db-dot.value { background: #ffffff;
  box-shadow: inset 0 0 0 2.5px var(--blue-600); }
.dumbbell { display: grid; }
.db-row { display: grid; grid-template-columns: minmax(110px, 220px) 1fr; column-gap: 12px;
  align-items: center; min-height: 52px; border-radius: 10px; }
.db-row:not(.db-axis):hover, .db-row:focus { background: var(--grey-50); outline: none; }
.db-axis { min-height: 28px; }
.db-name { text-align: right; font-weight: 500; color: var(--ink); overflow-wrap: anywhere; }
.db-track { position: relative; min-height: 52px; margin: 0 64px 0 52px; }
.db-axis .db-track { min-height: 28px; }
.db-tick { position: absolute; top: 4px; transform: translateX(-50%); font: 13px var(--font-mono);
  color: var(--grey-500); }
.db-grid { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--grey-200); }
.db-gap { position: absolute; top: calc(50% - 1.5px); height: 3px; background: var(--blue-200);
  border-radius: 2px; }
.db-dot { position: absolute; top: 50%; width: 16px; height: 16px; border-radius: 50%;
  transform: translate(-50%, -50%); }
.db-val { position: absolute; top: 50%; font: 500 16px var(--font-mono); color: var(--grey-600);
  white-space: nowrap; }
.db-val.strong { color: var(--blue-600); font-weight: 600; }
.db-val.left { transform: translate(calc(-100% - 14px), -50%); }
.db-val.right { transform: translate(14px, -50%); }
.agent { padding: 18px 0; border-top: 1px solid var(--grey-200); }
.agent:first-of-type { border-top: 0; }
.agent-head { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
  margin-bottom: 10px; }
.agent-name { font-weight: 600; color: var(--ink); font-size: 18px; }
.agent-score { color: var(--grey-600); }
.agent-score b { font-family: var(--font-mono); color: var(--blue-600); font-size: 20px; }
.bar { display: flex; gap: 2px; height: 30px; }
.seg { min-width: 8px; display: flex; align-items: center; justify-content: center;
  font: 600 14px var(--font-mono); transition: filter 120ms var(--ease); }
.seg:first-child { border-radius: 6px 0 0 6px; }
.seg:last-child { border-radius: 0 6px 6px 0; }
.seg:only-child { border-radius: 6px; }
.seg:hover, .seg:focus, .pill:hover, .pill:focus { filter: brightness(0.93); outline: none; }
.agent-notes { display: flex; flex-wrap: wrap; gap: 4px 28px; margin-top: 10px; font-size: 15px;
  color: var(--grey-600); }
.agent-notes b { font-family: var(--font-mono); font-size: 12px; font-weight: 500;
  letter-spacing: 0.12em; text-transform: uppercase; color: var(--grey-500); margin-right: 8px; }
.out-pass { background: var(--blue-600); color: #ffffff; }
.out-values { background: var(--blue-200); color: var(--ink); }
.out-wrong { background: var(--grey-700); color: #ffffff; }
.out-none { background: var(--grey-300); color: var(--ink); }
.split { display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 24px 40px;
  margin-top: 8px; }
.scroll { overflow-x: auto; margin-top: 20px; }
table { border-collapse: separate; border-spacing: 3px; }
th, td { padding: 8px 12px; text-align: left; font-size: 15px; }
thead th { font: 500 12px var(--font-mono); letter-spacing: 0.12em; text-transform: uppercase;
  color: var(--grey-500); vertical-align: bottom; }
tbody th { font-weight: 500; color: var(--ink); white-space: nowrap; }
.heatmap td.heat { font: 600 16px var(--font-mono); text-align: center; min-width: 92px;
  border-radius: 6px; padding: 12px; }
.heatmap td.empty { color: var(--grey-300); text-align: center; }
.scale { display: flex; align-items: center; gap: 10px; margin-top: 10px;
  font: 12px var(--font-mono);
  color: var(--grey-500); }
.scale i { display: inline-block; width: 120px; height: 8px; border-radius: 4px;
  background: linear-gradient(90deg, #ffffff, var(--blue-600));
  box-shadow: inset 0 0 0 1px var(--grey-200); }
table.data td { border-bottom: 1px solid var(--grey-100); }
table.cases tr.group th { padding-top: 18px; font: 500 12px var(--font-mono);
  letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--blue-600); }
.pill { display: inline-block; padding: 3px 10px; border-radius: 999px; white-space: nowrap;
  font: 500 12px var(--font-mono); letter-spacing: 0.06em; text-transform: uppercase; }
details.more { margin-top: 18px; }
details.more > summary { cursor: pointer; font: 500 13px var(--font-mono); letter-spacing: 0.12em;
  text-transform: uppercase; color: var(--blue-600); list-style: none; }
details.more > summary::before { content: "+ "; }
details.more[open] > summary::before { content: "\\2212 "; }
.grader-notes { list-style: none; padding: 0; margin: 18px 0 0; display: grid; gap: 8px;
  font-size: 15px; color: var(--grey-600); }
.grader-notes span { font-weight: 600; color: var(--ink); margin-right: 10px; }
.grader-notes b { font-family: var(--font-mono); color: var(--blue-600); }
.reasons { list-style: none; padding: 0; margin: 12px 0 0; }
.reasons li { display: grid; grid-template-columns: 64px auto 1fr; gap: 12px; align-items: baseline;
  padding: 10px 0; border-top: 1px solid var(--grey-100); font-size: 15px; }
.reason { color: var(--grey-600); }
.reason small { display: block; margin-top: 4px; font-size: 14px; color: var(--grey-500); }
.reasons .pill { justify-self: start; }
.method { margin-top: 56px; padding-top: 28px; border-top: 1px solid var(--grey-200); }
.method p { max-width: 75ch; margin: 12px 0 0; }
.outcomes { list-style: none; padding: 0; margin: 18px 0; display: grid; gap: 10px; }
.outcomes li { display: flex; gap: 14px; align-items: center; }
.outcomes .pill { min-width: 128px; text-align: center; }
#tip { position: fixed; z-index: 10; max-width: 380px; pointer-events: none; background: #ffffff;
  color: var(--ink); border: 1px solid var(--grey-200); border-radius: 10px; padding: 10px 12px;
  font-size: 14px; white-space: pre-line; box-shadow: 0 18px 48px rgba(10,10,10,0.10),
  0 4px 12px rgba(10,10,10,0.06); }
[hidden] { display: none !important; }
@media (max-width: 760px) {
  .db-row { grid-template-columns: 1fr; padding: 6px 0; }
  .db-axis > span:first-child { display: none; }
  .db-name { text-align: left; }
  .db-track { margin: 0 64px 0 48px; }
  .heatmap td.heat { min-width: 64px; padding: 10px 6px; font-size: 15px; }
}
@media (max-width: 640px) {
  main { padding: 20px 16px 64px; }
  .block { padding: 20px; }
  .reasons li { grid-template-columns: 1fr; gap: 4px; }
}
@media print { #tip { display: none; } .block { box-shadow: none; break-inside: avoid; } }
</style>
</head>
<body>
<main>
"""

_TAIL = """
</main>
<div id="tip" role="tooltip" hidden></div>
<script>
(() => {
  const tip = document.getElementById("tip");
  const place = (x, y) => {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    tip.style.left = Math.max(8, Math.min(x + 14, window.innerWidth - w - 8)) + "px";
    tip.style.top = Math.max(8, y - h - 14) + "px";
  };
  document.querySelectorAll("[data-tip]").forEach((el) => {
    const show = (x, y) => { tip.textContent = el.dataset.tip; tip.hidden = false; place(x, y); };
    el.addEventListener("pointermove", (e) => show(e.clientX, e.clientY));
    el.addEventListener("pointerleave", () => { tip.hidden = true; });
    el.addEventListener("focus", () => {
      const r = el.getBoundingClientRect(); show(r.left + r.width / 2, r.top);
    });
    el.addEventListener("blur", () => { tip.hidden = true; });
  });
})();
</script>
</body>
</html>
"""
