from hamcrest import assert_that, equal_to
from tests.shared.givenpy import given, then, when

from tickmark.scoring import exact_match, numeric_tolerance


def test_when_text_has_only_outer_whitespace_then_exact_match_succeeds() -> None:
    with given() as context:
        context.actual = "  42.0\n"
        context.expected = "42.0"

    with when():
        context.result = exact_match(context.actual, context.expected)

    with then():
        assert_that(context.result, equal_to(1.0))


def test_when_text_values_differ_then_exact_match_fails() -> None:
    with given() as context:
        context.actual = "42"
        context.expected = "43"

    with when():
        context.result = exact_match(context.actual, context.expected)

    with then():
        assert_that(context.result, equal_to(0.0))


def test_when_numbers_are_within_tolerance_then_numeric_match_succeeds() -> None:
    with given() as context:
        context.actual = 10.0
        context.expected = 10.0001
        context.tolerance = 0.001

    with when():
        context.result = numeric_tolerance(
            context.actual, context.expected, tolerance=context.tolerance
        )

    with then():
        assert_that(context.result, equal_to(1.0))


def test_when_number_is_not_finite_then_numeric_match_fails() -> None:
    with given() as context:
        context.actual = float("nan")
        context.expected = 10.0

    with when():
        context.result = numeric_tolerance(context.actual, context.expected)

    with then():
        assert_that(context.result, equal_to(0.0))
