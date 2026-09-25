from hamcrest import assert_that, contains_exactly, equal_to, greater_than_or_equal_to
from tests.shared.givenpy import given, then, when

from tickmark.scenarios import (
    extract_decisions,
    fixed_scenarios,
    one_at_a_time,
    search_candidates,
)
from tickmark.workbook_audit import CellObservation


def test_when_inputs_include_switches_and_years_then_they_get_their_own_scenarios() -> None:
    with given() as context:
        context.inputs = {"M!B2": 100.0, "M!B3": 1, "M!B4": 0, "M!B5": 2025}

    with when():
        context.scenarios = {s.name: s.changes for s in fixed_scenarios(context.inputs)}

    with then():
        assert_that(
            list(context.scenarios), contains_exactly("up", "down", "mixed", "switches", "years")
        )
        assert_that(context.scenarios["switches"], equal_to({"M!B3": 0, "M!B4": 1}))
        assert_that(context.scenarios["years"], equal_to({"M!B5": 2026}))
        assert_that(list(context.scenarios["up"]), equal_to(["M!B2"]))


def test_when_model_has_no_switches_or_years_then_only_factor_scenarios_remain() -> None:
    with given() as context:
        context.inputs = {"M!B2": 100.0, "M!B3": 0.2}

    with when():
        context.names = [s.name for s in fixed_scenarios(context.inputs)]

    with then():
        assert_that(context.names, contains_exactly("up", "down", "mixed"))


def test_when_inputs_change_one_at_a_time_then_each_scenario_touches_one_cell() -> None:
    with given() as context:
        context.inputs = {"M!B2": 100.0, "M!B3": 1, "M!B5": 2025}

    with when():
        context.scenarios = one_at_a_time(context.inputs)

    with then():
        assert_that(
            [dict(s.changes) for s in context.scenarios],
            equal_to([{"M!B2": 100.0 * 1.15}, {"M!B3": 0}, {"M!B5": 2026}]),
        )


def test_when_search_candidates_are_generated_then_they_are_wide_and_repeatable() -> None:
    with given() as context:
        context.inputs = {"M!B2": 100.0, "M!B3": 50.0}

    with when():
        context.first = search_candidates(context.inputs)
        context.second = search_candidates(context.inputs)

    with then():
        assert_that(context.first, equal_to(context.second))
        assert_that(len(context.first), greater_than_or_equal_to(10))
        for scenario in context.first:
            for key, value in scenario.changes.items():
                factor = value / context.inputs[key]
                assert_that(0.4 <= factor <= 1.9, equal_to(True))


def test_when_formulas_branch_then_each_decision_gets_a_sheet_qualified_helper() -> None:
    with given() as context:
        context.observations = {
            "Debt Plan!C5": CellObservation(
                "Debt Plan!C5", 0, "=IF(B2>B3*3,MAX(B2-B3,0),IFERROR(B2/B4,0))"
            ),
            "Debt Plan!C6": CellObservation("Debt Plan!C6", 0, "=MIN(B2:B4)+ABS(B3)"),
            "Debt Plan!C7": CellObservation("Debt Plan!C7", 5),
        }

    with when():
        context.decisions = extract_decisions(
            context.observations, ["Debt Plan!C5", "Debt Plan!C6", "Debt Plan!C7"]
        )

    with then():
        assert_that(
            [d.label for d in context.decisions],
            contains_exactly(
                "IF in Debt Plan!C5",
                "MAX in Debt Plan!C5",
                "IFERROR in Debt Plan!C5",
                "ABS in Debt Plan!C6",
            ),
        )
        assert_that(
            context.decisions[0].helper,
            equal_to("=IF(('Debt Plan'!B2>'Debt Plan'!B3*3),1,0)"),
        )
        assert_that(
            context.decisions[1].helper,
            equal_to("=IF(('Debt Plan'!B2-'Debt Plan'!B3)<=(0),1,0)"),
        )
