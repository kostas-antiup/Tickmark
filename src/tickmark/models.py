"""Small, provider-neutral data models used by the benchmark runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchmarkCase:
    """One versioned prompt/task and its expected evaluation metadata."""

    case_id: str
    prompt: str
    expected: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelResponse:
    """A model output plus optional provider metadata."""

    text: str
    model: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Score:
    """Normalized score for one benchmark case."""

    case_id: str
    value: float
    rationale: str = ""
