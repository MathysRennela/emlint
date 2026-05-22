"""Shared test helpers for the dem-linter test suite.

Import these directly in test files:
    from helpers import _mech, _model, assert_failed
"""

from __future__ import annotations

from typing import Literal, Protocol, cast

from emlint.model import ErrorMechanism, ErrorModel
from emlint.report import PropertyResult


class FailedResult(Protocol):
    """Narrowed PropertyResult where counter_example and counter_example_data are non-None."""

    name: str
    passed: bool
    severity: Literal["error", "warning"]
    message: str
    counter_example: str
    counter_example_data: dict


def assert_failed(result: PropertyResult) -> FailedResult:
    """Assert that *result* represents a failing check and narrow its optional fields.

    Asserts:
        - ``result.passed`` is False
        - ``result.counter_example`` is not None
        - ``result.counter_example_data`` is not None

    Returns *result* cast to ``FailedResult`` so that callers can subscript
    ``counter_example`` and ``counter_example_data`` without type-checker noise.
    """
    assert not result.passed
    assert result.counter_example is not None
    assert result.counter_example_data is not None
    return cast(FailedResult, result)


def _mech(
    p: float,
    detectors: frozenset[int] = frozenset(),
    observables: frozenset[int] = frozenset(),
) -> ErrorMechanism:
    return ErrorMechanism(probability=p, detectors=detectors, observables=observables)


def _model(*mechs: ErrorMechanism) -> ErrorModel:
    return ErrorModel(
        detectors={d for m in mechs for d in m.detectors},
        observables={o for m in mechs for o in m.observables},
        error_mechanisms=list(mechs),
    )
