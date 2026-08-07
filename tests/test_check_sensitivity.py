"""Tests for check_sensitivity.

check_sensitivity flags every declared detector that is never triggered by any
error mechanism.  A "dead" detector contributes no syndrome information and
either indicates a wiring mistake or a missing fault model.

Property: ∀d ∈ D, ∃m ∈ mechanisms, d ∈ det(m)
          equivalently: D ⊆ ⋃_{m} det(m)
"""

from __future__ import annotations

import pytest
from hypothesis import given
import hypothesis.strategies as st

from emlint.checks import _MAX_SHOWN, check_sensitivity
from emlint.model import ErrorModel
from helpers import _mech, _model, assert_failed

# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_sensitivity(model)
    assert result.passed
    assert result.name == "sensitivity"
    assert result.severity == "warning"
    assert result.counter_example is None


def test_single_mechanism_covers_its_detector():
    m = _mech(0.1, detectors=frozenset({0}))
    result = check_sensitivity(_model(m))
    assert result.passed


def test_multiple_mechanisms_each_cover_different_detectors():
    m0 = _mech(0.1, detectors=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({1}))
    result = check_sensitivity(_model(m0, m1))
    assert result.passed


def test_detector_covered_by_multiple_mechanisms_passes():
    """D0 appearing in two mechanisms still counts as covered."""
    m0 = _mech(0.1, detectors=frozenset({0}))
    m1 = _mech(0.2, detectors=frozenset({0}))
    result = check_sensitivity(_model(m0, m1))
    assert result.passed


def test_mechanism_with_no_detectors_does_not_affect_declared_set():
    """A silent mechanism (empty detectors) must not falsely satisfy the property."""
    # Build a model where D0 is declared but only a silent mechanism exists
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[_mech(0.1, detectors=frozenset())],
    )
    result = check_sensitivity(model)
    assert not result.passed


def test_passing_result_has_no_counter_example():
    m = _mech(0.1, detectors=frozenset({0}))
    result = check_sensitivity(_model(m))
    assert result.counter_example is None


# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------


def test_single_dead_detector_fails():
    model = ErrorModel(detectors={0}, observables=set(), error_mechanisms=[])
    result = check_sensitivity(model)
    assert not result.passed
    assert result.severity == "warning"


def test_multiple_dead_detectors_fail():
    model = ErrorModel(detectors={0, 1, 2}, observables=set(), error_mechanisms=[])
    result = check_sensitivity(model)
    assert not result.passed


def test_result_name_on_failure():
    model = ErrorModel(detectors={0}, observables=set(), error_mechanisms=[])
    result = check_sensitivity(model)
    assert result.name == "sensitivity"


def test_counter_example_not_none_on_failure():
    model = ErrorModel(detectors={0}, observables=set(), error_mechanisms=[])
    assert_failed(check_sensitivity(model))


def test_counter_example_contains_dead_detector_label():
    model = ErrorModel(detectors={3}, observables=set(), error_mechanisms=[])
    result = assert_failed(check_sensitivity(model))
    assert "D3" in result.counter_example


def test_message_contains_dead_count():
    model = ErrorModel(detectors={0, 1}, observables=set(), error_mechanisms=[])
    result = check_sensitivity(model)
    assert "2" in result.message


def test_only_uncovered_detectors_reported():
    """D0 is covered; D1 is dead — only D1 must appear in the counter-example."""
    m = _mech(0.1, detectors=frozenset({0}))
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=[m],
    )
    result = assert_failed(check_sensitivity(model))
    assert not result.passed
    assert "D1" in result.counter_example
    assert "D0" not in result.counter_example


# ---------------------------------------------------------------------------
# Truncation
# ---------------------------------------------------------------------------


def test_truncation_message_when_many_dead_detectors():
    """More than _MAX_SHOWN dead detectors should mention the overflow count."""
    n = _MAX_SHOWN + 3
    model = ErrorModel(detectors=set(range(n)), observables=set(), error_mechanisms=[])
    result = assert_failed(check_sensitivity(model))
    assert not result.passed
    assert "more" in result.counter_example


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------


@given(
    dets=st.frozensets(st.integers(0, 10), min_size=1),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_mechanism_always_covers_its_own_detectors(dets, p):
    """The detectors of any mechanism are trivially covered by that mechanism."""
    m = _mech(p, detectors=dets)
    assert check_sensitivity(_model(m)).passed


@given(
    d=st.integers(0, 20),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_declared_detector_not_in_any_mechanism_always_fails(d, p):
    """A detector declared in the model but absent from every mechanism must fail."""
    model = ErrorModel(
        detectors={d},
        observables=set(),
        error_mechanisms=[_mech(p, detectors=frozenset())],
    )
    assert not check_sensitivity(model).passed


# ---------------------------------------------------------------------------
# counter_example_data
# ---------------------------------------------------------------------------


def test_passing_result_has_no_counter_example_data():
    m = _mech(0.1, detectors=frozenset({0}))
    result = check_sensitivity(_model(m))
    assert result.counter_example_data is None


def test_failing_result_has_counter_example_data():
    model = ErrorModel(detectors={0}, observables=set(), error_mechanisms=[])
    assert_failed(check_sensitivity(model))


def test_counter_example_data_has_detectors_key():
    model = ErrorModel(detectors={0}, observables=set(), error_mechanisms=[])
    result = assert_failed(check_sensitivity(model))
    assert "detectors" in result.counter_example_data


def test_counter_example_data_detectors_is_list_of_ints():
    model = ErrorModel(detectors={3, 7}, observables=set(), error_mechanisms=[])
    result = assert_failed(check_sensitivity(model))
    data = result.counter_example_data
    assert isinstance(data["detectors"], list)
    assert all(isinstance(d, int) for d in data["detectors"])


def test_counter_example_data_contains_all_dead_detectors():
    model = ErrorModel(detectors={3, 7}, observables=set(), error_mechanisms=[])
    result = assert_failed(check_sensitivity(model))
    assert set(result.counter_example_data["detectors"]) == {3, 7}


def test_counter_example_data_excludes_covered_detectors():
    m = _mech(0.1, detectors=frozenset({0}))
    model = ErrorModel(detectors={0, 1}, observables=set(), error_mechanisms=[m])
    result = assert_failed(check_sensitivity(model))
    assert result.counter_example_data["detectors"] == [1]


# ---------------------------------------------------------------------------
# Detector coordinate labels
# ---------------------------------------------------------------------------


def test_dead_detector_with_coordinates_uses_annotated_label():
    """When detector_coords is set, the counter-example must use 'Dn@(x,y,z)' format."""
    model = ErrorModel(
        detectors={17},
        observables=set(),
        error_mechanisms=[],
        detector_coords={17: (1.0, 0.0, 2.0)},
    )
    result = assert_failed(check_sensitivity(model))
    assert not result.passed
    assert "D17@(1,0,2)" in result.counter_example


def test_dead_detector_without_coordinates_uses_plain_label():
    """When detector_coords is absent the counter-example must fall back to 'Dn' format."""
    model = ErrorModel(detectors={17}, observables=set(), error_mechanisms=[])
    result = assert_failed(check_sensitivity(model))
    assert not result.passed
    assert "D17" in result.counter_example
    assert "@" not in result.counter_example


# ---------------------------------------------------------------------------
# from_stim_dem round-trip
# ---------------------------------------------------------------------------


def test_dead_detector_from_stim_dem_fails():
    """A declared detector that no error mechanism fires must fail sensitivity
    after parsing a real DEM string via from_stim_dem."""
    import stim
    from emlint.frontends import from_stim_dem

    # detector D1 is declared but no mechanism references it
    dem = stim.DetectorErrorModel("error(0.1) D0 L0\ndetector D0\ndetector D1")
    model = from_stim_dem(dem)
    result = assert_failed(check_sensitivity(model))
    assert not result.passed
    assert "D1" in result.counter_example


def test_all_detectors_covered_from_stim_dem_passes():
    """Every declared detector is referenced by at least one mechanism — sensitivity must pass."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel("error(0.1) D0 L0\ndetector D0")
    model = from_stim_dem(dem)
    assert check_sensitivity(model).passed
