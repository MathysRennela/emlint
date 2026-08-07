"""Tests for check_duplicates.

check_duplicates flags every group of mechanisms that share the same
(detectors, observables) signature.  Duplicate signatures mean the same fault
path is listed more than once; a decoder that assumes independence will
miscalculate the effective probability instead of XOR-folding the entries.

Property: the signature map m ↦ (det(m), obs(m)) is injective
          equivalently: ∀m ≠ m', (det(m), obs(m)) ≠ (det(m'), obs(m'))

XOR-fold: p_eff = p1*(1-p2) + p2*(1-p1), iterated for 3+ entries.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
import hypothesis.strategies as st

from emlint.checks import _MAX_SHOWN, check_duplicates
from emlint.model import ErrorModel
from helpers import _mech, _model, assert_failed

# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


def test_empty_model_passes():
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    result = check_duplicates(model)
    assert result.passed
    assert result.name == "duplicates"
    assert result.severity == "warning"
    assert result.counter_example is None


def test_single_mechanism_passes():
    result = check_duplicates(_model(_mech(0.1, detectors=frozenset({0}))))
    assert result.passed


def test_different_signatures_pass():
    """Different detector sets → different signatures → no duplicates."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({1}), observables=frozenset({0}))
    result = check_duplicates(_model(m0, m1))
    assert result.passed


def test_same_detectors_different_observables_passes():
    """(D0, L0) and (D0, L1) are distinct signatures — not duplicates."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_duplicates(_model(m0, m1))
    assert result.passed


def test_same_observables_different_detectors_passes():
    """(D0, L0) and (D1, L0) are distinct signatures — not duplicates."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({1}), observables=frozenset({0}))
    result = check_duplicates(_model(m0, m1))
    assert result.passed


def test_passing_result_has_no_counter_example():
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_duplicates(_model(m))
    assert result.counter_example is None


# ---------------------------------------------------------------------------
# Failing cases — basic
# ---------------------------------------------------------------------------


def test_two_mechanisms_same_signature_fails():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_duplicates(_model(m0, m1))
    assert not result.passed


def test_counter_example_not_none_on_failure():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    assert_failed(check_duplicates(_model(m0, m1)))


def test_counter_example_contains_detector_label():
    m0 = _mech(0.1, detectors=frozenset({3}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({3}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    assert "D3" in result.counter_example


def test_counter_example_contains_both_probabilities():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset())
    ce = assert_failed(check_duplicates(_model(m0, m1))).counter_example
    assert "0.1" in ce and "0.2" in ce


def test_single_duplicate_group_count():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_duplicates(_model(m0, m1))
    assert "Found 1 " in result.message


# ---------------------------------------------------------------------------
# XOR-fold is reported in the counter-example
# ---------------------------------------------------------------------------


def test_xor_fold_two_entries_reported():
    """For p=0.1 and p=0.1 the XOR-fold is 0.1*0.9 + 0.1*0.9 = 0.18."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    assert not result.passed
    assert "0.18" in result.counter_example


def test_xor_fold_three_entries_reported():
    """p ⊕ p ⊕ p with p=0.25 → 0.25⊕0.25=0.375, 0.375⊕0.25=0.4375."""
    mechs = [_mech(0.25, detectors=frozenset({0}), observables=frozenset())] * 3
    result = assert_failed(check_duplicates(_model(*mechs)))
    assert not result.passed
    assert "0.4375" in result.counter_example


# ---------------------------------------------------------------------------
# Multiple distinct duplicate groups
# ---------------------------------------------------------------------------


def test_two_independent_duplicate_groups_counted():
    # Group 1: (D0, ∅) — two entries
    # Group 2: (D1, L0) — two entries
    mechs = [
        _mech(0.1, detectors=frozenset({0}), observables=frozenset()),
        _mech(0.2, detectors=frozenset({0}), observables=frozenset()),
        _mech(0.1, detectors=frozenset({1}), observables=frozenset({0})),
        _mech(0.2, detectors=frozenset({1}), observables=frozenset({0})),
    ]
    result = check_duplicates(_model(*mechs))
    assert not result.passed
    assert "2" in result.message


def test_clean_mechanism_does_not_inflate_duplicate_count():
    """A third mechanism with a unique signature must not be counted as a duplicate."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(
        0.2, detectors=frozenset({0}), observables=frozenset()
    )  # duplicate of m0
    m2 = _mech(0.1, detectors=frozenset({1}), observables=frozenset())  # unique
    result = check_duplicates(_model(m0, m1, m2))
    assert not result.passed
    assert "1" in result.message


def test_counter_example_data_not_truncated_when_counter_example_is():
    """The counter_example string is truncated, but counter_example_data must include all mechanisms."""
    n = _MAX_SHOWN + 3
    mechs = []
    for i in range(n):
        # Each pair shares the same (det, obs) signature, creating n duplicate groups
        mechs.append(_mech(0.1, detectors=frozenset({i}), observables=frozenset()))
        mechs.append(_mech(0.2, detectors=frozenset({i}), observables=frozenset()))
    result = assert_failed(check_duplicates(_model(*mechs)))
    # The counter_example string must be truncated
    assert "more" in result.counter_example
    # But counter_example_data must have all mechanisms
    assert len(result.counter_example_data["mechanisms"]) == n * 2


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------


@given(
    dets=st.frozensets(st.integers(0, 10)),
    obs=st.frozensets(st.integers(0, 5)),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_single_mechanism_never_a_duplicate(dets, obs, p):
    """A model with one mechanism can never have a duplicate signature."""
    assert check_duplicates(_model(_mech(p, detectors=dets, observables=obs))).passed


@given(
    dets1=st.frozensets(st.integers(0, 10)),
    obs1=st.frozensets(st.integers(0, 5)),
    dets2=st.frozensets(st.integers(0, 10)),
    obs2=st.frozensets(st.integers(0, 5)),
    p1=st.floats(min_value=1e-4, max_value=0.5),
    p2=st.floats(min_value=1e-4, max_value=0.5),
)
def test_distinct_signatures_never_duplicate(dets1, obs1, dets2, obs2, p1, p2):
    """Two mechanisms with strictly distinct (det, obs) signatures must pass."""
    from hypothesis import assume

    assume((dets1, obs1) != (dets2, obs2))
    m0 = _mech(p1, detectors=dets1, observables=obs1)
    m1 = _mech(p2, detectors=dets2, observables=obs2)
    assert check_duplicates(_model(m0, m1)).passed


# ---------------------------------------------------------------------------
# counter_example_data
# ---------------------------------------------------------------------------


def test_passing_result_has_no_counter_example_data():
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_duplicates(_model(m))
    assert result.counter_example_data is None


def test_failing_result_has_counter_example_data():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset({0}))
    assert_failed(check_duplicates(_model(m0, m1)))


def test_counter_example_data_has_mechanisms_key():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    assert "mechanisms" in result.counter_example_data


def test_counter_example_data_mechanisms_is_list_of_strings():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({0}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    data = result.counter_example_data
    assert isinstance(data["mechanisms"], list)
    assert all(isinstance(s, str) for s in data["mechanisms"])


def test_counter_example_data_contains_one_entry_per_duplicate_mechanism():
    m0 = _mech(0.1, detectors=frozenset({3}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({3}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    # two mechanisms in the duplicate group → two entries
    assert len(result.counter_example_data["mechanisms"]) == 2


def test_counter_example_data_mechanism_strings_contain_detector_and_probability():
    m0 = _mech(0.1, detectors=frozenset({3}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({3}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    strs = result.counter_example_data["mechanisms"]
    combined = " ".join(strs)
    assert "D3" in combined
    assert "0.1" in combined
    assert "0.2" in combined


# ---------------------------------------------------------------------------
# Detector coordinate labels
# ---------------------------------------------------------------------------


def test_duplicate_with_coordinates_uses_annotated_label():
    """When detector_coords is set, the duplicate counter-example must use 'Dn@(x,y,z)' format."""
    m0 = _mech(0.1, detectors=frozenset({5}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({5}), observables=frozenset())
    model = ErrorModel(
        detectors={5},
        observables=set(),
        error_mechanisms=[m0, m1],
        detector_coords={5: (2.0, 1.0, 0.0)},
    )
    result = assert_failed(check_duplicates(model))
    assert not result.passed
    assert "D5@(2,1,0)" in result.counter_example


def test_duplicate_without_coordinates_uses_plain_label():
    """Without detector_coords the counter-example must fall back to the plain 'Dn' format."""
    m0 = _mech(0.1, detectors=frozenset({5}), observables=frozenset())
    m1 = _mech(0.2, detectors=frozenset({5}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    assert not result.passed
    assert "D5" in result.counter_example
    assert "@" not in result.counter_example


def test_counter_example_data_two_groups_lists_all_mechanisms():
    # Group 1: (D0, ∅) — two entries; Group 2: (D1, L0) — two entries → 4 total
    mechs = [
        _mech(0.1, detectors=frozenset({0}), observables=frozenset()),
        _mech(0.2, detectors=frozenset({0}), observables=frozenset()),
        _mech(0.1, detectors=frozenset({1}), observables=frozenset({0})),
        _mech(0.2, detectors=frozenset({1}), observables=frozenset({0})),
    ]
    result = check_duplicates(_model(*mechs))
    assert result.counter_example_data is not None
    assert len(result.counter_example_data["mechanisms"]) == 4


# ---------------------------------------------------------------------------
# from_stim_dem round-trip
# ---------------------------------------------------------------------------


def test_duplicate_mechanism_from_stim_dem_fails():
    """Two mechanisms with the same (detectors, observables) signature parsed via
    from_stim_dem must fail check_duplicates."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel("error(0.1) D0 L0\nerror(0.2) D0 L0\ndetector D0")
    model = from_stim_dem(dem)
    result = assert_failed(check_duplicates(model))
    assert not result.passed
    assert "D0" in result.counter_example


def test_distinct_mechanisms_from_stim_dem_passes():
    """Mechanisms with distinct signatures parsed via from_stim_dem must pass check_duplicates."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel(
        "error(0.1) D0 L0\nerror(0.1) D1 L0\ndetector D0\ndetector D1"
    )
    model = from_stim_dem(dem)
    assert check_duplicates(model).passed
