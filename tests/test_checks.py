from __future__ import annotations

import inspect
from typing import Callable

import pytest

from emlint.checks import ALL_CHECKS
from emlint.model import ErrorModel


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_has_matching_result_name(
    name: str, check_fn: Callable
) -> None:
    result = check_fn(ErrorModel(set(), set(), []))
    assert result.name == name


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_satisfies_result_contract(
    name: str, check_fn: Callable
) -> None:
    result = check_fn(ErrorModel(set(), set(), []))
    assert result.severity in {"error", "warning"}
    if result.passed:
        assert result.counter_example is None
        assert result.counter_example_data is None
    else:
        assert result.counter_example is not None
        assert result.counter_example_data is not None


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_reports_counterexamples_on_failure(
    name: str, check_fn: Callable
) -> None:
    """Every production check has a minimal model that violates its property."""
    from emlint.model import ErrorMechanism

    cases = {
        "detectability": ErrorModel(
            set(), {0}, [ErrorMechanism(0.1, frozenset(), frozenset({0}))]
        ),
        "sensitivity": ErrorModel({0}, set(), []),
        "observable_coverage": ErrorModel(set(), {0}, []),
        "probability_bounds": ErrorModel(
            set(), set(), [ErrorMechanism(0.0, frozenset(), frozenset())]
        ),
        "duplicates": ErrorModel(
            set(),
            set(),
            [
                ErrorMechanism(0.1, frozenset(), frozenset()),
                ErrorMechanism(0.2, frozenset(), frozenset()),
            ],
        ),
        "correctability": ErrorModel(
            {0},
            {0, 1},
            [
                ErrorMechanism(0.1, frozenset({0}), frozenset({0})),
                ErrorMechanism(0.1, frozenset({0}), frozenset({1})),
            ],
        ),
    }
    result = check_fn(cases[name])
    assert not result.passed
    assert result.counter_example is not None
    assert result.counter_example_data is not None


_HINT_CHECKS = ("detectability", "sensitivity", "duplicates", "correctability")


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_hint_contract(name: str, check_fn: Callable) -> None:
    """The v0.2.2 output contract: hint-carrying checks populate a hypothesis-
    phrased hint on failure; every passing result has hint None."""
    from emlint.model import ErrorMechanism

    cases = {
        "detectability": ErrorModel(
            set(), {0}, [ErrorMechanism(0.1, frozenset(), frozenset({0}))]
        ),
        "sensitivity": ErrorModel({0}, set(), []),
        "observable_coverage": ErrorModel(set(), {0}, []),
        "probability_bounds": ErrorModel(
            set(), set(), [ErrorMechanism(0.0, frozenset(), frozenset())]
        ),
        "duplicates": ErrorModel(
            set(),
            set(),
            [
                ErrorMechanism(0.1, frozenset(), frozenset()),
                ErrorMechanism(0.2, frozenset(), frozenset()),
            ],
        ),
        "correctability": ErrorModel(
            {0},
            {0, 1},
            [
                ErrorMechanism(0.1, frozenset({0}), frozenset({0})),
                ErrorMechanism(0.1, frozenset({0}), frozenset({1})),
            ],
        ),
    }
    result = check_fn(cases[name])
    assert not result.passed
    if name in _HINT_CHECKS:
        assert result.hint is not None
        assert result.hint.startswith("Hypothesis")
    else:
        assert result.hint is None


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_passing_result_has_no_hint(name: str, check_fn: Callable) -> None:
    result = check_fn(ErrorModel(set(), set(), []))
    if result.passed:
        assert result.hint is None


@pytest.mark.parametrize("check_fn", ALL_CHECKS.values())
def test_validate_check_signature(check_fn: Callable) -> None:
    sig = inspect.signature(check_fn)
    params = list(sig.parameters.values())
    assert params[0].name == "model"
    assert len(params) == 2
    assert params[1].name == "max_shown"
