"""Deterministic baseline scoring functions."""

from __future__ import annotations

import math


def exact_match(actual: str, expected: str) -> float:
    """Return 1.0 for equal normalized text and 0.0 otherwise."""

    return float(actual.strip() == expected.strip())


def numeric_tolerance(actual: float, expected: float, tolerance: float = 1e-9) -> float:
    """Return 1.0 when two finite numbers differ by at most ``tolerance``."""

    if not math.isfinite(actual) or not math.isfinite(expected):
        return 0.0
    return float(math.isclose(actual, expected, abs_tol=tolerance, rel_tol=0.0))
