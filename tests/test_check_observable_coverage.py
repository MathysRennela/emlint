"""Tests for check_observable_coverage.

check_observable_coverage flags every declared logical observable that is never
flipped by any error mechanism.  An uncovered observable is invisible to the
decoder, which always predicts the trivial (no-flip) correction for it and
therefore silently masks any real logical error on that observable.

Property: ∀ℓ ∈ O, ∃m ∈ mechanisms, ℓ ∈ obs(m)
          equivalently: O ⊆ ⋃_{m} obs(m)
"""
from __future__ import annotations

import pytest
from hypothesis import given
import hypothesis.strategies as st

from emlint.checks import _MAX_SHOWN, check_observable_coverage
from emlint.model import ErrorModel
from helpers import _mech, _model


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_observable_coverage(model)
    assert result.passed
    assert result.name == "observable_coverage"
    assert result.severity == "error"
    assert result.counter_example is None


def test_single_observable_covered_passes():
    m = _mech(0.1, observables=frozenset({0}))
    result = check_observable_coverage(_model(m))
    assert result.passed


def test_multiple_observables_all_covered_passes():
    m0 = _mech(0.1, observables=frozenset({0}))
    m1 = _mech(0.1, observables=frozenset({1}))
    result = check_observable_coverage(_model(m0, m1))
    assert result.passed


def test_observable_covered_by_multiple_mechanisms_passes():
    """L0 appearing in two mechanisms still counts as covered."""
    m0 = _mech(0.1, observables=frozenset({0}))
    m1 = _mech(0.2, observables=frozenset({0}))
    result = check_observable_coverage(_model(m0, m1))
    assert result.passed


def test_mechanism_with_no_observables_does_not_satisfy_coverage():
    """A mechanism that flips no observable must not count as covering anything."""
    model = ErrorModel(
        detectors=set(),
        observables={0},
        error_mechanisms=[_mech(0.1, observables=frozenset())],
    )
    result = check_observable_coverage(model)
    assert not result.passed


def test_passing_result_has_no_counter_example():
    m = _mech(0.1, observables=frozenset({0}))
    result = check_observable_coverage(_model(m))
    assert result.counter_example is None


# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------

def test_single_uncovered_observable_fails():
    model = ErrorModel(detectors=set(), observables={0}, error_mechanisms=[])
    result = check_observable_coverage(model)
    assert not result.passed
    assert result.severity == "error"


def test_multiple_uncovered_observables_fail():
    model = ErrorModel(detectors=set(), observables={0, 1, 2}, error_mechanisms=[])
    result = check_observable_coverage(model)
    assert not result.passed


def test_result_name_on_failure():
    model = ErrorModel(detectors=set(), observables={0}, error_mechanisms=[])
    result = check_observable_coverage(model)
    assert result.name == "observable_coverage"


def test_counter_example_not_none_on_failure():
    model = ErrorModel(detectors=set(), observables={0}, error_mechanisms=[])
    result = check_observable_coverage(model)
    assert result.counter_example is not None


def test_only_uncovered_observables_reported():
    """L0 is covered; L1 is not — only L1 must appear in the counter-example."""
    m = _mech(0.1, observables=frozenset({0}))
    model = ErrorModel(
        detectors=set(),
        observables={0, 1},
        error_mechanisms=[m],
    )
    result = check_observable_coverage(model)
    assert not result.passed
    assert "L1" in result.counter_example
    assert "L0" not in result.counter_example


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_truncation_message_when_many_uncovered_observables():
    """More than _MAX_SHOWN uncovered observables should mention the overflow count."""
    n = _MAX_SHOWN + 3
    model = ErrorModel(detectors=set(), observables=set(range(n)), error_mechanisms=[])
    result = check_observable_coverage(model)
    assert not result.passed
    assert "more" in result.counter_example


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------

@given(
    obs=st.frozensets(st.integers(0, 10), min_size=1),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_mechanism_always_covers_its_own_observables(obs, p):
    """The observables of any mechanism are trivially covered by that mechanism."""
    m = _mech(p, observables=obs)
    assert check_observable_coverage(_model(m)).passed


@given(
    o=st.integers(0, 20),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_declared_observable_not_in_any_mechanism_always_fails(o, p):
    """An observable declared in the model but absent from every mechanism must fail."""
    model = ErrorModel(
        detectors=set(),
        observables={o},
        error_mechanisms=[_mech(p, observables=frozenset())],
    )
    assert not check_observable_coverage(model).passed
