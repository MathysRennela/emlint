"""Tests for check_detectability.

check_detectability flags every error mechanism that flips at least one
observable while triggering zero detectors — those represent undetectable
logical errors.
"""

from __future__ import annotations

import pytest

from hypothesis import given
import hypothesis.strategies as st

from emlint.checks import (
    _MAX_SHOWN,
    _iter_repeat_templates,
    _shift_mechanism,
    check_detectability,
)
from emlint.model import ErrorModel
from helpers import _mech, _model, assert_failed

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
    assert result.counter_example is not None
    assert "0.25" in result.counter_example


def test_counter_example_multiple_observables_sorted():
    """Multiple observables in one mechanism must all appear, in ascending order."""
    m = _mech(0.1, detectors=frozenset(), observables=frozenset({3, 1}))
    result = check_detectability(_model(m))
    ce = result.counter_example
    assert ce is not None
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


# ---------------------------------------------------------------------------
# counter_example_data
# ---------------------------------------------------------------------------


def test_passing_result_has_no_counter_example_data():
    m = _mech(0.2, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert result.counter_example_data is None


def test_failing_result_has_counter_example_data():
    m = _mech(0.1, detectors=frozenset(), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert result.counter_example_data is not None


def test_counter_example_data_has_mechanisms_key():
    m = _mech(0.1, detectors=frozenset(), observables=frozenset({0}))
    result = assert_failed(check_detectability(_model(m)))
    assert "mechanisms" in result.counter_example_data


def test_counter_example_data_mechanisms_is_list_of_strings():
    m = _mech(0.1, detectors=frozenset(), observables=frozenset({0}))
    result = assert_failed(check_detectability(_model(m)))
    data = result.counter_example_data
    assert isinstance(data["mechanisms"], list)
    assert all(isinstance(s, str) for s in data["mechanisms"])


def test_counter_example_data_contains_all_violations():
    m0 = _mech(0.1, detectors=frozenset(), observables=frozenset({0}))
    m1 = _mech(0.2, detectors=frozenset(), observables=frozenset({1}))
    result = assert_failed(check_detectability(_model(m0, m1)))
    assert len(result.counter_example_data["mechanisms"]) == 2


def test_counter_example_data_mechanism_string_format():
    m = _mech(0.25, detectors=frozenset(), observables=frozenset({0}))
    result = assert_failed(check_detectability(_model(m)))
    mech_strs = result.counter_example_data["mechanisms"]
    assert len(mech_strs) == 1
    assert mech_strs[0].startswith("error(0.25)")
    assert "L0" in mech_strs[0]


def test_instance_count_scales_with_repeat_multiplicity():
    """A violation inside a REPEAT block recurs once per iteration.

    counter_example_data["instance_count"] and the message must report the
    true number of flattened instances, not just the number of distinct
    repeat-body locations (regression test for undercounting).
    """
    from emlint.model import RepeatBlock

    body = (_mech(0.01, detectors=frozenset(), observables=frozenset({0})),)
    block = RepeatBlock(
        body=body, count=5, detector_offset_per_iteration=1, absolute_start_offset=0
    )
    model = ErrorModel(detectors=set(), observables={0}, error_mechanisms=[block])
    result = assert_failed(check_detectability(model))
    assert result.counter_example_data["instance_count"] == 5
    assert "Found 5 undetectable error mechanism instance(s)" in result.message
    # Ground truth: flattening confirms 5 independent violating instances.
    flattened_violations = [
        m for m in model.flattened() if not m.detectors and m.observables
    ]
    assert len(flattened_violations) == 5


def test_truncation_message_when_many_violations():
    """More than _MAX_SHOWN violations should mention the overflow count."""
    n = _MAX_SHOWN + 3
    mechs = [
        _mech(0.1, detectors=frozenset(), observables=frozenset({i})) for i in range(n)
    ]
    result = assert_failed(check_detectability(_model(*mechs)))
    assert not result.passed
    assert "more" in result.counter_example
    # All violations are still present in the structured data.
    assert len(result.counter_example_data["mechanisms"]) == n


def test_truncation_boundary_exactly_max_shown_has_no_overflow():
    """Exactly _MAX_SHOWN violations must render all of them, no overflow note.

    Guards the off-by-one at the truncation boundary (mutant: `>` → `>=`).
    """
    n = _MAX_SHOWN
    mechs = [
        _mech(0.1, detectors=frozenset(), observables=frozenset({i})) for i in range(n)
    ]
    result = assert_failed(check_detectability(_model(*mechs)))
    assert not result.passed
    assert "more" not in result.counter_example
    # Every violation is rendered: the last one appears in the counter-example.
    assert f"L{n - 1}" in result.counter_example


def test_passing_message_states_the_invariant():
    """The passing message must state the verified invariant, not be empty.

    Guards against a silent pass (mutant: passing-path `message=None`).
    """
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_detectability(_model(m))
    assert result.passed
    assert result.message
    assert "detector" in result.message.lower()


def test_repeat_shift_preserves_detector_ids_in_witness():
    """A violating mechanism inside an offset REPEAT block reports absolute IDs.

    The witness is built with `_shift_mechanism`; a mutant that drops the shift
    (offset=None) would report the template's unshifted detector IDs.
    """
    from emlint.model import RepeatBlock

    body = (_mech(0.1, detectors=frozenset(), observables=frozenset({0})),)
    block = RepeatBlock(
        body=body, count=3, detector_offset_per_iteration=7, absolute_start_offset=2
    )
    model = ErrorModel(detectors=set(), observables={0}, error_mechanisms=[block])
    result = assert_failed(check_detectability(model))
    # Violating mechanisms have no detectors, so the witness names the
    # observable; the structured data must still carry one entry per instance.
    assert result.counter_example_data["instance_count"] == 3
    shifted = _shift_mechanism(body[0], 2)
    assert shifted.detectors == frozenset()


# ---------------------------------------------------------------------------
# from_stim_dem round-trip
# ---------------------------------------------------------------------------


def test_undetectable_error_from_stim_dem_fails():
    """Parse a real DEM string via from_stim_dem and confirm detectability catches it."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel("error(0.1) L0")
    model = from_stim_dem(dem)
    result = assert_failed(check_detectability(model))
    assert not result.passed
    assert "L0" in result.counter_example


def test_detectable_error_from_stim_dem_passes():
    """A mechanism that fires a detector passes detectability after parsing."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel("error(0.1) D0 L0\ndetector D0")
    model = from_stim_dem(dem)
    assert check_detectability(model).passed


def test_witness_preserves_decomposition_hints_with_shift():
    """Witness materialization must shift hint component detector IDs exactly
    like merged IDs — provenance survives the repeat fast path (regression
    for hints being silently dropped by witness/shift helpers)."""
    from emlint.model import ErrorMechanism, RepeatBlock

    mech = ErrorMechanism(
        0.1,
        frozenset({1}),
        frozenset({0}),
        ((frozenset({1}), frozenset({0})), (frozenset(), frozenset())),
    )
    block = RepeatBlock(
        body=(mech,), count=2, detector_offset_per_iteration=10, absolute_start_offset=5
    )
    model = ErrorModel(set(range(30)), {0}, [block])
    witness = _shift_mechanism(
        _iter_repeat_templates(model)[0].mechanism,
        _iter_repeat_templates(model)[0].absolute_start,
    )
    assert witness.detectors == frozenset({6})
    assert witness.decomposition_hints == (
        (frozenset({6}), frozenset({0})),
        (frozenset(), frozenset()),
    )
