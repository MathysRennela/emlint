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

from emlint.checks import _MAX_SHOWN, ALL_CHECKS, check_duplicates
from emlint.model import ErrorMechanism, ErrorModel
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


def test_decomposed_vs_plain_no_false_collision():
    """A decomposed mechanism whose components share detectors must not collide
    with an unrelated plain mechanism under the decoder-facing (union)
    signature: `D0 D1 ^ D0` consumes as ({D0,D1}, {}), not ({D1}, {})."""
    decomposed = ErrorMechanism(
        probability=0.1,
        detectors=frozenset({1}),  # XOR-folded merged view
        observables=frozenset(),
        decomposition_hints=(
            (frozenset({0, 1}), frozenset()),
            (frozenset({0}), frozenset()),
        ),
    )
    plain = _mech(0.2, detectors=frozenset({1}))
    result = check_duplicates(_model(decomposed, plain))
    assert result.passed


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
# Fused-probability severity contract (enhanced duplicates)
# ---------------------------------------------------------------------------


def test_structural_duplicates_only_remain_warning():
    """Duplicate signatures are always warning severity — valid Stim output
    legitimately produces coincident merged signatures."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    result = check_duplicates(_model(m0, m1))
    assert not result.passed
    assert result.severity == "warning"


def test_fused_probability_above_half_stays_warning():
    """Even when a duplicate group's XOR-fused probability exceeds 0.5
    (requires a contributing p > 0.5: 0.9 ⊕ 0.45 = 0.54), the finding stays a
    warning — probability_bounds already flags the anomalous entry."""
    m0 = _mech(0.9, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(0.45, detectors=frozenset({0}), observables=frozenset())
    result = assert_failed(check_duplicates(_model(m0, m1)))
    assert result.severity == "warning"


def test_decomposed_mechanisms_duplicate_at_merged_granularity():
    """Two ^-decomposed mechanisms with identical merged signatures are
    reported as duplicates at merged-signature granularity (warning).

    error(0.001) D0 D2   (undecomposed)
    error(0.001) D2 ^ D0 (components {D2}, {D0})

    The counter-example data preserves both contributing mechanisms so
    downstream tooling can inspect decomposition_hints for attribution.
    """
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel(
        "error(0.001) D0 D2\nerror(0.001) D2 ^ D0\ndetector D0\ndetector D2"
    )
    model = from_stim_dem(dem)
    result = assert_failed(check_duplicates(model))
    assert not result.passed
    assert result.severity == "warning"
    # Provenance: every contributing mechanism appears in the structured data.
    assert len(result.counter_example_data["mechanisms"]) == 2


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
    assert "Found 2 duplicate mechanism signature(s)" in result.message


def test_clean_mechanism_does_not_inflate_duplicate_count():
    """A third mechanism with a unique signature must not be counted as a duplicate."""
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset())
    m1 = _mech(
        0.2, detectors=frozenset({0}), observables=frozenset()
    )  # duplicate of m0
    m2 = _mech(0.1, detectors=frozenset({1}), observables=frozenset())  # unique
    result = check_duplicates(_model(m0, m1, m2))
    assert not result.passed
    assert "Found 1 duplicate mechanism signature(s)" in result.message


def test_single_occurrence_signature_is_never_a_duplicate():
    """A signature seen exactly once is not a duplicate even if it carries a
    fused-probability state.

    Guards the group-selection predicate (mutants: `> 1` → `>= 1`, or `and`
    → `or`), which would flag every mechanism with non-None state as a
    duplicate regardless of multiplicity.
    """
    # Three distinct signatures, each occurring exactly once.
    mechs = [
        _mech(0.9, detectors=frozenset({0}), observables=frozenset()),
        _mech(0.45, detectors=frozenset({1}), observables=frozenset()),
        _mech(0.3, detectors=frozenset({2}), observables=frozenset({0})),
    ]
    result = check_duplicates(_model(*mechs))
    assert result.passed
    assert result.counter_example is None


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


def test_signature_count_scales_with_repeat_multiplicity():
    """A duplicate signature inside an isolated REPEAT block recurs once per
    iteration, each at a distinct shifted absolute detector location.

    counter_example_data["signature_count"] and the message must report the
    true number of distinct duplicate signatures across all iterations, not
    just the count found in one representative iteration (regression test
    for undercounting in the cross-scope symbolic fast path).
    """
    from emlint.model import RepeatBlock

    body = (
        _mech(0.1, detectors=frozenset({0}), observables=frozenset()),
        _mech(0.1, detectors=frozenset({0}), observables=frozenset()),
    )
    block = RepeatBlock(
        body=body, count=3, detector_offset_per_iteration=10, absolute_start_offset=0
    )
    model = ErrorModel(
        detectors=set(range(30)), observables=set(), error_mechanisms=[block]
    )
    result = assert_failed(check_duplicates(model))
    assert result.counter_example_data["signature_count"] == 3
    assert "Found 3 duplicate mechanism signature(s)" in result.message
    # Ground truth: flattening confirms 3 distinct duplicate signatures, one
    # per repeat iteration (D0, D10, D20).
    flattened = model.flattened()
    signatures = [(m.detectors, m.observables) for m in flattened]
    duplicate_signatures = {s for s in signatures if signatures.count(s) > 1}
    assert len(duplicate_signatures) == 3


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


def test_signature_collision_message_on_canonical_stim_dem():
    """Regression pin (rescope option A): the canonical stim-generated
    surface-code DEM trips signature injectivity with the honest
    both-hypotheses message — expected behavior, not a bug."""
    import stim

    dem = stim.Circuit.generated(
        "surface_code:rotated_memory_x",
        distance=3,
        rounds=3,
        after_clifford_depolarization=0.001,
    ).detector_error_model(decompose_errors=True)
    result = check_duplicates(_model_from_stim(dem))
    assert not result.passed
    assert "signature collision" in result.message
    assert "concatenating sub-circuit DEMs" in result.message
    assert result.counter_example_data["location_count"] >= 1
    assert (
        result.counter_example_data["signature_count"]
        >= result.counter_example_data["location_count"]
    )


def _model_from_stim(dem):
    from emlint.frontends import from_stim_dem

    return from_stim_dem(dem)


def test_dem_assembly_gate_selects_message_variant():
    import emlint

    dem = "error(0.1) D0 L0\nerror(0.2) D0 L0\ndetector D0"
    default = emlint.check(dem, checks={"duplicates": ALL_CHECKS["duplicates"]})
    mono = emlint.check(
        dem,
        checks={"duplicates": ALL_CHECKS["duplicates"]},
        context={"dem_assembly": "monolithic"},
    )
    concat = emlint.check(
        dem,
        checks={"duplicates": ALL_CHECKS["duplicates"]},
        context={"dem_assembly": "concatenated"},
    )
    d = next(r for r in default.results if r.name == "duplicates")
    m = next(r for r in mono.results if r.name == "duplicates")
    c = next(r for r in concat.results if r.name == "duplicates")
    assert "signature collision" in d.message
    assert "usually benign" in m.message
    assert "concatenated without merging" in c.message
    assert m.counter_example == d.counter_example
    assert c.counter_example_data == d.counter_example_data


def test_dem_assembly_monolithic_message_hint_consistent():
    """Regression (red-team v0.2.2): under dem_assembly=monolithic the message
    claims the finding is benign, so the message must not retain the XOR-fold
    imperative and the hint must not still assert the concatenation hypothesis.
    Under concatenated the hint from check_duplicates already matches and must
    be left unchanged."""
    import emlint

    dem = "error(0.1) D0 L0\nerror(0.2) D0 L0\ndetector D0"
    default = emlint.check(dem, checks={"duplicates": ALL_CHECKS["duplicates"]})
    mono = emlint.check(
        dem,
        checks={"duplicates": ALL_CHECKS["duplicates"]},
        context={"dem_assembly": "monolithic"},
    )
    concat = emlint.check(
        dem,
        checks={"duplicates": ALL_CHECKS["duplicates"]},
        context={"dem_assembly": "concatenated"},
    )
    d = next(r for r in default.results if r.name == "duplicates")
    m = next(r for r in mono.results if r.name == "duplicates")
    c = next(r for r in concat.results if r.name == "duplicates")

    # Monolithic: benign claim, no contradictory fix imperative, hint rewritten.
    assert "usually benign" in m.message
    assert "XOR-fold" not in m.message
    assert "not left as separate entries" not in m.message
    assert m.hint is not None
    assert m.hint.startswith("Hypothesis:")
    assert "concatenated without" not in m.hint

    # Concatenated: XOR instruction kept, hint unchanged from the default.
    assert "XOR-folded" in c.message
    assert c.hint == d.hint
