"""Provider-neutral execution loop for benchmark cases."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Protocol

from .models import BenchmarkCase, ModelResponse, Score
from .scoring import exact_match


class ModelAdapter(Protocol):
    """Minimum interface required from a model under evaluation."""

    def generate(self, prompt: str) -> ModelResponse:
        """Generate one response for a prompt."""


class BenchmarkRunner:
    """Run cases through an adapter and apply an explicit scoring function."""

    def __init__(
        self,
        adapter: ModelAdapter,
        scorer: Callable[[str, str], float] = exact_match,
    ) -> None:
        self.adapter = adapter
        self.scorer = scorer

    def run(self, cases: Iterable[BenchmarkCase]) -> list[Score]:
        scores: list[Score] = []
        for case in cases:
            response = self.adapter.generate(case.prompt)
            if not isinstance(case.expected, str):
                raise TypeError(f"case {case.case_id!r} requires a string expected value")
            value = self.scorer(response.text, case.expected)
            scores.append(Score(case_id=case.case_id, value=value))
        return scores
