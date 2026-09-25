import pytest
from hamcrest import assert_that, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.leaderboard import (
    CHECKS,
    entry_from_records,
    ranked,
    ranks,
    replace_between,
    svg_card,
    table,
    upsert,
)


def _record(case, outcome, value, formulas, trace, agent="a", passed_checks=0, seconds=10.0):
    scores = {"value_correctness": value, "formula_coverage": formulas, "traceability": trace}
    checks = {check: index < passed_checks for index, check in enumerate(CHECKS)}
    return {
        "agent": agent,
        "case_id": case,
        "outcome": outcome,
        "scores": scores,
        "checks": checks,
        "duration_seconds": seconds,
    }


def _entry(name, real, right, checks, **extra):
    base = {"cases": 3, "value_correctness": 0.5, "formula_coverage": 0.5, "traceability": 0.5}
    return {
        **base,
        "name": name,
        "model": "",
        "interface": "x",
        "real_models": real,
        "right_numbers": right,
        "checks_passed": checks,
        "median_seconds": 12,
        **extra,
    }


def test_when_a_run_is_summarised_then_pilot_counts_and_means_are_computed() -> None:
    with given() as context:
        context.records = [
            _record("02_01", "pass", 1.0, 1.0, 1.0, passed_checks=7, seconds=30),
            _record("06_18", "values only", 1.0, 0.5, 0.5, passed_checks=4, seconds=10),
            _record("14_07", "fail", 0.5, 0.0, 0.0, passed_checks=0, seconds=20),
            _record("14_07", "pass", 1.0, 1.0, 1.0, agent="other"),
            _record("09_03", "pass", 1.0, 1.0, 1.0),
        ]

    with when():
        context.entry = entry_from_records(context.records, "a")

    with then():
        assert_that(context.entry["cases"], equal_to(3))
        assert_that(context.entry["real_models"], equal_to(1))
        assert_that(context.entry["right_numbers"], equal_to(2))
        assert_that(context.entry["formula_coverage"], equal_to(0.5))
        assert_that(context.entry["checks_passed"], equal_to(round(11 / 21, 4)))
        assert_that(context.entry["median_seconds"], equal_to(20))
        with pytest.raises(ValueError, match="no result"):
            entry_from_records(context.records, "other")


def test_when_entries_are_ranked_then_ties_share_a_rank() -> None:
    with given() as context:
        context.entries = [
            _entry("values", 0, 3, 0.8),
            _entry("real b", 2, 2, 0.9),
            _entry("real a", 2, 2, 0.9),
            _entry("fewer checks", 2, 2, 0.7),
        ]

    with when():
        context.rows = ranked(context.entries)
        context.ranks = ranks(context.rows)
        context.table = table(context.entries)

    with then():
        names = [e["name"] for e in context.rows]
        assert_that(names, equal_to(["real a", "real b", "fewer checks", "values"]))
        assert_that(context.ranks, equal_to([1, 1, 3, 4]))
        assert_that(
            context.table,
            contains_string(
                "| 1 | real a | x | **2 / 3** | 2 / 3 | 90% | 50% | 50% | 50% | 12 s |"
            ),
        )


def test_when_the_card_is_drawn_then_each_agent_gets_a_ranked_row() -> None:
    with when():
        svg = svg_card(
            [_entry("Agent & Co", 3, 3, 1.0), _entry("Other", 0, 1, 0.3)], ["x"], "today"
        )

    with then():
        assert_that(svg, contains_string("<svg"))
        assert_that(svg, contains_string("Agent &amp; Co"))
        assert_that(svg, contains_string("3/3"))
        assert_that(svg, contains_string("UPDATED today"))


def test_when_a_table_is_rendered_into_the_readme_then_only_the_marked_block_changes() -> None:
    with given() as context:
        context.text = "intro\n<!-- leaderboard:start -->\nold\n<!-- leaderboard:end -->\nend\n"

    with when():
        context.result = replace_between(context.text, "new")

    with then():
        expected = "intro\n<!-- leaderboard:start -->\nnew\n<!-- leaderboard:end -->\nend\n"
        assert_that(context.result, equal_to(expected))


def test_when_an_entry_is_added_twice_then_it_is_replaced() -> None:
    with when():
        entries = upsert([{"name": "A", "model": "m", "v": 1}], {"name": "A", "model": "m", "v": 2})

    with then():
        assert_that(entries, equal_to([{"name": "A", "model": "m", "v": 2}]))
