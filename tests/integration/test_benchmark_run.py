import shutil
from pathlib import Path

import openpyxl
from hamcrest import assert_that, contains_string, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.agents import OUTPUT_NAME, AgentResult, AgentTask, ManualAgent
from tickmark.benchmark_run import collect_records, run_benchmark
from tickmark.cases import load_case
from tickmark.recalculation import CachedValues

CASE_14_07 = Path(__file__).resolve().parents[2] / "data" / "cases" / "14_07"


class GoldenValues:
    """Engine stand-in: any workbook 'calculates' to the golden's saved values."""

    name = "golden-values"
    supports_changes = False

    def evaluate(self, workbook, cells, changes=None):
        return CachedValues().evaluate(CASE_14_07 / "golden.xlsx", cells)


class CopyAgent:
    """Answers with the golden workbook, optionally with G20 overwritten."""

    kind = "cli"

    def __init__(self, name, g20=None):
        self.name = name
        self.g20 = g20
        self.calls = 0

    def solve(self, task: AgentTask) -> AgentResult:
        self.calls += 1
        task.workspace.mkdir(parents=True, exist_ok=True)
        output = task.workspace / OUTPUT_NAME
        shutil.copy2(CASE_14_07 / "golden.xlsx", output)
        if self.g20 is not None:
            book = openpyxl.load_workbook(output)
            book["RentRoll"]["G20"] = self.g20
            book.save(output)
        return AgentResult("completed", output, 1.0)


class BrokenAgent:
    kind = "cli"
    name = "broken"

    def solve(self, task: AgentTask) -> AgentResult:
        raise RuntimeError("adapter bug")


def test_when_agents_run_then_outcomes_and_summary_separate_values_from_auditability(
    tmp_path,
) -> None:
    with given() as context:
        context.case = load_case(CASE_14_07)
        context.agents = [
            CopyAgent("modeller"),
            CopyAgent("hardcoder", g20=9080487),
            BrokenAgent(),
            ManualAgent("person"),
        ]

    with when():
        context.records = run_benchmark(
            context.agents, [context.case], tmp_path, GoldenValues(), progress=lambda _: None
        )

    with then():
        outcomes = {record.agent: record.outcome for record in context.records}
        assert_that(
            outcomes,
            equal_to(
                {
                    "modeller": "pass",
                    "hardcoder": "values only",
                    "broken": "error",
                    "person": "pending",
                }
            ),
        )
        summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
        assert_that(summary, contains_string("| modeller | 1 | 1/1 | 1/1 | 0 | 0 |"))
        assert_that(summary, contains_string("| hardcoder | 1 | 1/1 | 0/1 | 1 | 0 |"))
        assert_that(summary, contains_string("RuntimeError: adapter bug"))
        assert_that((tmp_path / "person" / "14_07" / "TASK.md").exists(), equal_to(True))


class CrashingEngine(GoldenValues):
    """Engine stand-in that fails, like Excel losing its COM connection mid-run."""

    def evaluate(self, workbook, cells, changes=None):
        raise RuntimeError("engine went away")


def test_when_grading_crashes_then_the_run_goes_on_and_a_rerun_only_regrades(tmp_path) -> None:
    with given() as context:
        context.case = load_case(CASE_14_07)
        context.agent = CopyAgent("modeller")

    with when():
        context.crashed = run_benchmark(
            [context.agent, CopyAgent("second")],
            [context.case],
            tmp_path,
            CrashingEngine(),
            progress=lambda _: None,
        )
        context.regraded = run_benchmark(
            [context.agent], [context.case], tmp_path, GoldenValues(), progress=lambda _: None
        )

    with then():
        assert_that([record.outcome for record in context.crashed], equal_to(["error", "error"]))
        assert_that(context.crashed[0].error or "", contains_string("engine went away"))
        assert_that([record.outcome for record in context.regraded], equal_to(["pass"]))
        assert_that(context.agent.calls, equal_to(1))


def test_when_a_run_is_repeated_then_graded_cases_are_not_solved_again(tmp_path) -> None:
    with given() as context:
        context.case = load_case(CASE_14_07)
        context.agent = CopyAgent("modeller")
        run_benchmark([context.agent], [context.case], tmp_path, GoldenValues(), progress=print)

    with when():
        run_benchmark([context.agent], [context.case], tmp_path, GoldenValues(), progress=print)
        context.records = collect_records(tmp_path)

    with then():
        assert_that(context.agent.calls, equal_to(1))
        assert_that([record.outcome for record in context.records], equal_to(["pass"]))
