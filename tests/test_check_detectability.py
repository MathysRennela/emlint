"""Tests for check_detectability.

check_detectability flags every error mechanism that flips at least one
observable while triggering zero detectors — those represent undetectable
logical errors.
"""
from __future__ import annotations

import pytest

from hypothesis import given
import hypothesis.strategies as st

from emlint.checks import _MAX_SHOWN, check_detectability
from emlint.model import ErrorModel
from helpers import _mech, _model


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_detectability(model)
    assert result.passed
    assert result.name == "detectability"
    assert result.severity == "error"
    assert result.counter_example is None


def test_mechanism_with_detector_and_observable_passes():
    """A mechanism that triggers D0 AND flips L0 is fine — it is detectable."""
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert result.passed


def test_mechanism_with_detector_only_passes():
    """A mechanism that triggers a detector but flips no observable is not a detectability issue."""
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    result = check_detectability(_model(m))
    assert result.passed


def test_mechanism_with_neither_detector_nor_observable_passes():
    """A silent mechanism (no detectors, no observables) is irrelevant to detectability."""
    m = _mech(0.1, detectors=frozenset(), observables=frozenset())
    result = check_detectability(_model(m))
    assert result.passed


def test_passing_result_has_no_counter_example():
    m = _mech(0.2, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert result.counter_example is None


# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------

def test_single_violation_fails():
    m = _mech(0.1, detectors=frozenset(), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert not result.passed
    assert result.severity == "error"


def test_counter_example_contains_probability():
    m = _mech(0.25, detectors=frozenset(), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert "0.25" in result.counter_example


def test_counter_example_multiple_observables_sorted():
    """Multiple observables in one mechanism must all appear, in ascending order."""
    m = _mech(0.1, detectors=frozenset(), observables=frozenset({3, 1}))
    result = check_detectability(_model(m))
    ce = result.counter_example
    assert "L1" in ce and "L3" in ce
    assert ce.index("L1") < ce.index("L3")


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------

@given(
    dets=st.frozensets(st.integers(0, 10), min_size=1),
    obs=st.frozensets(st.integers(0, 5)),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_mechanism_with_at_least_one_detector_always_passes(dets, obs, p):
    """Any mechanism that fires at least one detector satisfies detectability,
    regardless of which observables it flips."""
    m = _mech(p, detectors=dets, observables=obs)
    assert check_detectability(_model(m)).passed


@given(
    dets=st.frozensets(st.integers(0, 10)),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_mechanism_with_no_observables_always_passes(dets, p):
    """A mechanism that flips no observable is never a detectability violation."""
    m = _mech(p, detectors=dets, observables=frozenset())
    assert check_detectability(_model(m)).passed


@given(
    obs=st.frozensets(st.integers(0, 5), min_size=1),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_mechanism_with_no_detectors_and_observables_always_fails(obs, p):
    """A mechanism with non-empty observables and empty detectors is always a violation."""
    m = _mech(p, detectors=frozenset(), observables=obs)
    assert not check_detectability(_model(m)).passed
