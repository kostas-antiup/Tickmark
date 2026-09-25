from hamcrest import assert_that, equal_to, has_length
from tests.shared.givenpy import given, then, when

from tickmark.models import BenchmarkCase, ModelResponse
from tickmark.runner import BenchmarkRunner


class StaticAdapter:
    def generate(self, prompt: str) -> ModelResponse:
        return ModelResponse(text=f"answer:{prompt}", model="test-double")


def test_when_runner_receives_case_then_it_returns_a_matching_score() -> None:
    with given() as context:
        context.cases = [
            BenchmarkCase(case_id="case-1", prompt="revenue", expected="answer:revenue")
        ]
        context.adapter = StaticAdapter()

    with when():
        context.scores = BenchmarkRunner(context.adapter).run(context.cases)

    with then():
        assert_that(context.scores, has_length(1))
        assert_that(context.scores[0].case_id, equal_to("case-1"))
        assert_that(context.scores[0].value, equal_to(1.0))
