"""Tests for check_probability_bounds and its _prob_label helper.

Valid range is the open-closed interval (0, 0.5].
Out-of-range cases: p ≤ 0, p > 0.5, NaN.
"""
from __future__ import annotations

import math

import pytest
from hypothesis import given, assume
import hypothesis.strategies as st

from emlint.checks import _MAX_SHOWN, _prob_label, check_probability_bounds
from emlint.model import ErrorModel
from helpers import _mech, _model


# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_probability_bounds(model)
    assert result.passed
    assert result.name == "probability_bounds"
    assert result.severity == "error"
    assert result.counter_example is None

def test_p_epsilon_passes():
    """p just above 0 is valid."""
    result = check_probability_bounds(_model(_mech(1e-10)))
    assert result.passed

def test_p_half_passes():
    """p = 0.5 is the boundary and must pass."""
    result = check_probability_bounds(_model(_mech(0.5)))
    assert result.passed

def test_p_typical_passes():
    result = check_probability_bounds(_model(_mech(0.1)))
    assert result.passed

def test_multiple_valid_mechanisms_pass():
    mechs = [_mech(p) for p in (0.01, 0.1, 0.25, 0.5)]
    result = check_probability_bounds(_model(*mechs))
    assert result.passed

def test_passing_result_has_no_counter_example():
    result = check_probability_bounds(_model(_mech(0.1)))
    assert result.counter_example is None


# ---------------------------------------------------------------------------
# Failure:
# ---------------------------------------------------------------------------

def test_p_zero_fails():
    result = check_probability_bounds(_model(_mech(0.0)))
    assert not result.passed

def test_p_just_above_half_fails():
    result = check_probability_bounds(_model(_mech(0.5 + 1e-10)))
    assert not result.passed

def test_p_one_fails():
    result = check_probability_bounds(_model(_mech(1.0)))
    assert not result.passed

def test_p_negative_fails():
    result = check_probability_bounds(_model(_mech(-0.1)))
    assert not result.passed

def test_p_high_fails():
    result = check_probability_bounds(_model(_mech(0.9)))
    assert not result.passed

def test_p_nan_fails():
    result = check_probability_bounds(_model(_mech(float("nan"))))
    assert not result.passed

# ---------------------------------------------------------------------------
# Mixed violations: all four categories together
# ---------------------------------------------------------------------------

def test_mixed_violations_all_tags_in_message():
    mechs = [
        _mech(float("nan")),  # NaN
        _mech(-0.1),          # negative
        _mech(0.0),           # zero
        _mech(0.9),           # > 0.5
    ]
    result = check_probability_bounds(_model(*mechs))
    assert not result.passed
    assert "p = NaN" in result.message
    assert "p < 0" in result.message
    assert "p = 0" in result.message
    assert "p > 0.5" in result.message

def test_mixed_valid_and_invalid_counts_only_violations():
    mechs = [_mech(0.1), _mech(0.0), _mech(0.5), _mech(0.9)]
    result = check_probability_bounds(_model(*mechs))
    assert not result.passed
    assert "2" in result.message  # 2 violations: p=0 and p=0.9


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------

@given(st.floats(min_value=1e-10, max_value=0.5, allow_nan=False, allow_infinity=False))
def test_valid_p_always_passes(p):
    """Any p strictly in (0, 0.5] must pass probability_bounds."""
    assert check_probability_bounds(_model(_mech(p))).passed


@given(st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
def test_p_at_most_zero_always_fails(p):
    """p ≤ 0 must always fail (p = 0 is a no-op; p < 0 is unphysical)."""
    result = check_probability_bounds(_model(_mech(p)))
    assert not result.passed


@given(st.floats(min_value=0.5 + 1e-10, allow_nan=False, allow_infinity=False))
def test_p_above_half_always_fails(p):
    """p > 0.5 must always fail."""
    assume(p > 0.5)  # guard against floating-point edge that equals 0.5
    result = check_probability_bounds(_model(_mech(p)))
    assert not result.passed
