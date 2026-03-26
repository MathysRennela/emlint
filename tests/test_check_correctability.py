"""Tests for check_correctability.

check_correctability flags every syndrome (detector set) that is produced by
mechanisms with *different* observable sets.  When the decoder sees such a
syndrome it cannot determine the unique logical correction to apply.

The check must NOT flag:
  - mechanisms that share both detectors and observables (degenerate / duplicate
    errors — that is check_duplicates's job)
  - syndromes that appear with only one distinct observable set, regardless of
    how many mechanisms produce them
"""
from __future__ import annotations

import pytest

from hypothesis import given, settings
import hypothesis.strategies as st

from emlint.checks import _MAX_SHOWN, check_correctability
from emlint.model import ErrorModel
from helpers import _mech, _model


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_correctability(model)
    assert result.passed
    assert result.name == "correctability"
    assert result.severity == "warning"
    assert result.counter_example is None


def test_single_mechanism_passes():
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_correctability(_model(m))
    assert result.passed


def test_different_syndromes_different_observables_passes():
    """D0→L0 and D1→L1 have disjoint syndromes — no ambiguity."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({1}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert result.passed


def test_same_syndrome_same_observables_passes():
    """Two mechanisms with identical (detectors, observables) are degenerate —
    check_duplicates handles them; correctability must ignore them."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_correctability(_model(m0, m1))
    assert result.passed


def test_same_syndrome_same_observables_three_copies_passes():
    mechs = [_mech(0.05, detectors=frozenset({0}), observables=frozenset({0})) for _ in range(3)]
    result = check_correctability(_model(*mechs))
    assert result.passed


def test_different_syndromes_same_observable_passes():
    """Different syndromes pointing at the same observable is fine."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({1}), observables=frozenset({0}))
    result = check_correctability(_model(m0, m1))
    assert result.passed


def test_passing_result_has_no_counter_example():
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    assert check_correctability(_model(m)).counter_example is None


# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------

def test_same_syndrome_different_observables_fails():
    """Core case: D0→L0 and D0→L1 share syndrome {D0} but flip different observables."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert not result.passed
    assert result.severity == "warning"


def test_same_syndrome_one_with_no_observable_fails():
    """D0 + no observable vs D0 + L0: the syndrome {D0} is ambiguous."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_correctability(_model(m0, m1))
    assert not result.passed


def test_result_name_and_severity_on_failure():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert result.name == "correctability"
    assert result.severity == "warning"


def test_failure_counter_example_not_none():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert result.counter_example is not None


def test_counter_example_contains_detector_label():
    m0 = _mech(0.1, detectors=frozenset({3}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({3}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert "D3" in result.counter_example


def test_counter_example_contains_both_observable_sets():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    ce = result.counter_example
    assert "L0" in ce and "L1" in ce


def test_message_contains_conflict_count():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert "1" in result.message


def test_two_independent_conflicts_counted():
    # Syndrome {D0}: L0 vs L1  — conflict 1
    # Syndrome {D1}: L0 vs L2  — conflict 2
    mechs = [
        _mech(0.1, detectors=frozenset({0}), observables=frozenset({0})),
        _mech(0.1, detectors=frozenset({0}), observables=frozenset({1})),
        _mech(0.1, detectors=frozenset({1}), observables=frozenset({0})),
        _mech(0.1, detectors=frozenset({1}), observables=frozenset({2})),
    ]
    result = check_correctability(_model(*mechs))
    assert not result.passed
    assert "2" in result.message


def test_clean_syndrome_not_polluting_conflict_count():
    """A third syndrome that is unambiguous must not inflate the conflict count."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))  # conflict
    m2 = _mech(0.1, detectors=frozenset({2}), observables=frozenset({2}))  # clean
    result = check_correctability(_model(m0, m1, m2))
    assert not result.passed
    assert "1" in result.message


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------

def test_truncation_message_when_many_conflicts():
    """More than _MAX_SHOWN conflicting syndromes should mention the overflow count."""
    n = _MAX_SHOWN + 3
    mechs = []
    for i in range(n):
        # Each pair shares detector {i} but has different observables
        mechs.append(_mech(0.1, detectors=frozenset({i}), observables=frozenset({0})))
        mechs.append(_mech(0.1, detectors=frozenset({i}), observables=frozenset({1})))
    result = check_correctability(_model(*mechs))
    assert not result.passed
    assert "more" in result.counter_example


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------

@given(
    dets=st.frozensets(st.integers(0, 10)),
    obs=st.frozensets(st.integers(0, 5)),
    p1=st.floats(min_value=1e-4, max_value=0.5),
    p2=st.floats(min_value=1e-4, max_value=0.5),
)
def test_same_signature_never_conflicts(dets, obs, p1, p2):
    """Two mechanisms that share (detectors, observables) must never trigger correctability."""
    m0 = _mech(p1, detectors=dets, observables=obs)
    m1 = _mech(p2, detectors=dets, observables=obs)
    assert check_correctability(_model(m0, m1)).passed


@given(
    dets=st.frozensets(st.integers(0, 10)),
    obs=st.frozensets(st.integers(0, 5)),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_single_mechanism_always_passes(dets, obs, p):
    """A single mechanism can never produce an ambiguous syndrome."""
    m = _mech(p, detectors=dets, observables=obs)
    assert check_correctability(_model(m)).passed


@given(
    dets=st.frozensets(st.integers(0, 10)),
    obs=st.frozensets(st.integers(0, 5)),
    p=st.floats(min_value=1e-4, max_value=0.5),
    n=st.integers(min_value=1, max_value=5),
)
def test_n_identical_mechanisms_always_passes(dets, obs, p, n):
    """N copies of the same mechanism share both detectors and observables — never a conflict."""
    mechs = [_mech(p, detectors=dets, observables=obs)] * n
    assert check_correctability(_model(*mechs)).passed