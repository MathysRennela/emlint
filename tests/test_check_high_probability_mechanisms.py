"""Tests for check_high_probability_mechanisms."""

from __future__ import annotations

import pytest

from emlint.checks import check_high_probability_mechanisms
from emlint.model import ErrorModel
from helpers import _mech, _model, assert_failed


def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_high_probability_mechanisms(model)
    assert result.passed
    assert result.severity == "warning"


def test_low_probability_passes():
    result = check_high_probability_mechanisms(_model(_mech(0.1)))
    assert result.passed


def test_at_threshold_passes():
    result = check_high_probability_mechanisms(_model(_mech(0.3)))
    assert result.passed


def test_above_threshold_fails():
    result = check_high_probability_mechanisms(_model(_mech(0.4)))
    assert not result.passed
    assert result.severity == "warning"
    assert result.counter_example is not None


def test_counter_example_names_mechanism():
    m = _mech(0.4, detectors=frozenset({2}))
    result = assert_failed(check_high_probability_mechanisms(_model(m)))
    assert "0.4" in result.counter_example
    assert "D2" in result.counter_example


def test_custom_threshold():
    result = check_high_probability_mechanisms(_model(_mech(0.25)), threshold=0.2)
    assert not result.passed


@pytest.mark.parametrize("p", [0.01, 0.1, 0.29, 0.3])
def test_valid_never_fail(p):
    assert check_high_probability_mechanisms(_model(_mech(p))).passed
