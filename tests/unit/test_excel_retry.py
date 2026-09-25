from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to
from tests.shared.givenpy import given, then, when

from tickmark import recalculation
from tickmark.recalculation import ExcelRecalculator


class FakeComError(Exception):
    """Stands in for pywintypes.com_error."""


class FlakyExcel(ExcelRecalculator):
    """Fails with a COM error ``failures`` times, then answers."""

    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.restarts = 0

    def _evaluate_many(self, workbook, cells, change_sets):
        if self.failures:
            self.failures -= 1
            raise FakeComError("The RPC server is unavailable.")
        return [{"M!A1": 1} for _ in change_sets]

    def _restart(self) -> None:
        self.restarts += 1


def test_when_excel_drops_the_connection_once_then_it_restarts_and_retries(monkeypatch) -> None:
    with given() as context:
        monkeypatch.setattr(recalculation, "_com_errors", lambda: (FakeComError,))
        context.engine = FlakyExcel(failures=1)

    with when():
        context.result = context.engine.evaluate_many(Path("book.xlsx"), ["M!A1"], [{}])

    with then():
        assert_that(context.result, equal_to([{"M!A1": 1}]))
        assert_that(context.engine.restarts, equal_to(1))


def test_when_excel_keeps_failing_then_the_error_reaches_the_caller(monkeypatch) -> None:
    with given() as context:
        monkeypatch.setattr(recalculation, "_com_errors", lambda: (FakeComError,))
        context.engine = FlakyExcel(failures=2)

    with when(), pytest.raises(FakeComError):
        context.engine.evaluate_many(Path("book.xlsx"), ["M!A1"], [{}])

    with then():
        assert_that(context.engine.restarts, equal_to(1))
