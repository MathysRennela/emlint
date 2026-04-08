"""Tests for emlint.report: format_text, format_json, and _xor_fold."""
from __future__ import annotations

import json
import math

import pytest
from hypothesis import given
import hypothesis.strategies as st

from emlint.checks import _xor_fold
from emlint.report import PropertyResult, Report, format_json, format_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _passed(name: str = "completeness", severity: str = "error") -> PropertyResult:
    return PropertyResult(name=name, passed=True, severity=severity, message="ok")


def _failed(name: str = "completeness", severity: str = "error", ce: str = "ce") -> PropertyResult:
    return PropertyResult(name=name, passed=False, severity=severity, message="fail", counter_example=ce)


def _report(*results: PropertyResult) -> Report:
    return Report(results=list(results), num_detectors=4, num_observables=1, num_error_mechanisms=10)


# ---------------------------------------------------------------------------
# _xor_fold
# ---------------------------------------------------------------------------

def test_xor_fold_empty():
    assert _xor_fold([]) == 0.0


def test_xor_fold_single():
    assert _xor_fold([0.3]) == pytest.approx(0.3)


def test_xor_fold_identity():
    """p ⊕ 0 = p."""
    assert _xor_fold([0.25, 0.0]) == pytest.approx(0.25)


def test_xor_fold_symmetry():
    """p1 ⊕ p2 = p2 ⊕ p1."""
    assert _xor_fold([0.1, 0.2]) == pytest.approx(_xor_fold([0.2, 0.1]))


def test_xor_fold_known_value():
    """0.1 ⊕ 0.1 = 0.1*0.9 + 0.1*0.9 = 0.18."""
    assert _xor_fold([0.1, 0.1]) == pytest.approx(0.18)


def test_xor_fold_fixed_point():
    """0.5 ⊕ 0.5 = 0.5."""
    assert _xor_fold([0.5, 0.5]) == pytest.approx(0.5)


@given(st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_xor_fold_result_in_unit_interval(p):
    result = _xor_fold([p, p])
    assert 0.0 <= result <= 1.0


@given(
    p=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    q=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)
def test_xor_fold_commutative(p, q):
    assert _xor_fold([p, q]) == pytest.approx(_xor_fold([q, p]))


# ---------------------------------------------------------------------------
# format_text
# ---------------------------------------------------------------------------

def test_format_text_contains_counts():
    text = format_text(_report(_passed()))
    assert "4" in text   # num_detectors
    assert "1" in text   # num_observables
    assert "10" in text  # num_error_mechanisms


def test_format_text_passed_check_has_checkmark():
    text = format_text(_report(_passed("completeness")))
    assert "✓" in text
    assert "completeness" in text


def test_format_text_failed_check_has_cross():
    text = format_text(_report(_failed("sensitivity")))
    assert "✗" in text
    assert "sensitivity" in text


def test_format_text_counter_example_included():
    text = format_text(_report(_failed(ce="D3 is dead")))
    assert "D3 is dead" in text


def test_format_text_no_counter_example_when_passed():
    text = format_text(_report(_passed()))
    assert "Counter-example" not in text


def test_format_text_multiple_results():
    text = format_text(_report(_passed("completeness"), _failed("sensitivity")))
    assert "completeness" in text
    assert "sensitivity" in text


# ---------------------------------------------------------------------------
# format_json
# ---------------------------------------------------------------------------

def test_format_json_is_valid_json():
    output = format_json(_report(_passed()))
    json.loads(output)  # must not raise


def test_format_json_has_top_level_fields():
    data = json.loads(format_json(_report(_passed())))
    assert "num_detectors" in data
    assert "num_observables" in data
    assert "num_error_mechanisms" in data
    assert "all_passed" in data
    assert "has_errors" in data
    assert "has_warnings" in data
    assert "results" in data


def test_format_json_results_is_list():
    data = json.loads(format_json(_report(_passed(), _failed())))
    assert isinstance(data["results"], list)
    assert len(data["results"]) == 2


def test_format_json_result_has_required_fields():
    data = json.loads(format_json(_report(_passed("completeness"))))
    r = data["results"][0]
    assert r["name"] == "completeness"
    assert r["passed"] is True
    assert "severity" in r
    assert "message" in r
    assert "counter_example" in r


def test_format_json_counter_example_null_when_none():
    data = json.loads(format_json(_report(_passed())))
    assert data["results"][0]["counter_example"] is None


def test_format_json_counter_example_present_when_failed():
    data = json.loads(format_json(_report(_failed(ce="D0 is dead"))))
    assert data["results"][0]["counter_example"] == "D0 is dead"


def test_format_json_all_passed_true_when_all_pass():
    data = json.loads(format_json(_report(_passed(), _passed("sensitivity", "warning"))))
    assert data["all_passed"] is True


def test_format_json_all_passed_false_when_any_fails():
    data = json.loads(format_json(_report(_passed(), _failed())))
    assert data["all_passed"] is False


def test_format_json_has_errors_false_for_warning_only():
    data = json.loads(format_json(_report(_failed("sensitivity", severity="warning"))))
    assert data["has_errors"] is False


def test_format_json_has_errors_true_for_error_severity():
    data = json.loads(format_json(_report(_failed("completeness", severity="error"))))
    assert data["has_errors"] is True


# ---------------------------------------------------------------------------
# Report.all_passed / has_errors / has_warnings — direct unit tests
# ---------------------------------------------------------------------------

def test_all_passed_true_when_empty():
    assert _report().all_passed()


def test_all_passed_true_when_all_pass():
    assert _report(_passed(), _passed("sensitivity", "warning")).all_passed()


def test_all_passed_false_when_any_fails():
    assert not _report(_passed(), _failed()).all_passed()


def test_has_errors_false_when_all_pass():
    assert not _report(_passed(), _passed("sensitivity", "warning")).has_errors()


def test_has_errors_false_when_empty():
    assert not _report().has_errors()


def test_has_errors_true_when_error_severity_fails():
    assert _report(_failed("completeness", severity="error")).has_errors()


def test_has_errors_false_when_only_warning_fails():
    assert not _report(_failed("sensitivity", severity="warning")).has_errors()


def test_has_warnings_false_when_all_pass():
    assert not _report(_passed(), _passed("sensitivity", "warning")).has_warnings()


def test_has_warnings_false_when_empty():
    assert not _report().has_warnings()


def test_has_warnings_true_when_warning_severity_fails():
    assert _report(_failed("sensitivity", severity="warning")).has_warnings()


def test_has_warnings_false_when_only_error_fails():
    assert not _report(_failed("completeness", severity="error")).has_warnings()
