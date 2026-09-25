import pytest
from hamcrest import assert_that, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.leaderboard import entry_from_records, ranked, replace_between, table, upsert


def _record(case, outcome, value, formulas, trace, agent="a"):
    scores = {"value_correctness": value, "formula_coverage": formulas, "traceability": trace}
    return {"agent": agent, "case_id": case, "outcome": outcome, "scores": scores}


def test_when_a_run_is_summarised_then_pilot_counts_and_means_are_computed() -> None:
    with given() as context:
        context.records = [
            _record("02_01", "pass", 1.0, 1.0, 1.0),
            _record("06_18", "values only", 1.0, 0.5, 0.5),
            _record("14_07", "fail", 0.5, 0.0, 0.0),
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
        with pytest.raises(ValueError, match="no result"):
            entry_from_records(context.records, "other")


def test_when_entries_are_ranked_then_real_models_come_first() -> None:
    with given() as context:
        base = {"cases": 3, "value_correctness": 0.5, "formula_coverage": 0.5, "traceability": 0.5}
        context.entries = [
            {**base, "name": "values", "real_models": 0, "right_numbers": 3, "interface": "x"},
            {**base, "name": "real", "real_models": 2, "right_numbers": 2, "interface": "x"},
            {**base, "name": "none", "real_models": 0, "right_numbers": 0, "interface": "x"},
        ]

    with when():
        context.names = [e["name"] for e in ranked(context.entries)]
        context.table = table(context.entries)

    with then():
        assert_that(context.names, equal_to(["real", "values", "none"]))
        assert_that(
            context.table, contains_string("| 1 | real | x | **2 / 3** | 2 / 3 | 50% | 50% |")
        )


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
