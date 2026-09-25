from typing import Any


class GivenScope:
    def __init__(self, steps):
        self.steps = steps or []

        class Context:
            pass

        self.context: Any = Context()
        self.started_steps = []

    def __enter__(self):
        context = self.context
        for step in self.steps:
            result = step(context)
            self.started_steps.append(result)
            if result and hasattr(result, "__enter__"):
                result.__enter__()
        return context

    def __exit__(self, exc_type, value, traceback):
        for step in reversed(self.started_steps):
            if step and hasattr(step, "__exit__"):
                step.__exit__(exc_type, value, traceback)


def given(steps=None):
    return GivenScope(steps)


def when(description=None):
    return _MockContext()


def then(message=None):
    return _MockContext()


class _MockContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, value, traceback):
        return False
