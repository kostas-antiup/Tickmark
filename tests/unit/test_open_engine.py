import warnings
from contextlib import ExitStack

import pytest
from hamcrest import assert_that, equal_to, has_length
from tests.shared.givenpy import given, then, when

from tickmark import recalculation
from tickmark.recalculation import open_engine


def test_when_no_engine_is_installed_then_auto_warns_and_uses_cached_values(monkeypatch) -> None:
    with given():
        monkeypatch.setattr(recalculation, "available_engine", lambda: "cached")

    with when(), ExitStack() as stack, pytest.warns(UserWarning, match="No Excel or LibreOffice"):
        engine = open_engine("auto", stack)

    with then():
        assert_that(engine.name, equal_to("cached"))


def test_when_cached_is_asked_for_by_name_then_no_warning_is_shown() -> None:
    with when(), ExitStack() as stack, warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        engine = open_engine("cached", stack)

    with then():
        assert_that(engine.name, equal_to("cached"))
        assert_that(caught, has_length(0))
