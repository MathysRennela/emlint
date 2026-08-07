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

from hypothesis import given
import hypothesis.strategies as st

import emlint.checks as checks_module
from emlint.checks import _MAX_SHOWN, check_correctability
from emlint.model import ErrorModel
from helpers import _mech, _model, assert_failed

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
    mechs = [
        _mech(0.05, detectors=frozenset({0}), observables=frozenset({0}))
        for _ in range(3)
    ]
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
    assert_failed(check_correctability(_model(m0, m1)))


def test_counter_example_contains_detector_label():
    m0 = _mech(0.1, detectors=frozenset({3}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({3}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    assert "D3" in result.counter_example


def test_counter_example_contains_both_observable_sets():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    ce = assert_failed(check_correctability(_model(m0, m1))).counter_example
    assert "L0" in ce and "L1" in ce


def test_message_contains_conflict_count():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert "Found 1 " in result.message


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
    assert "Found 1 " in result.message


def test_empty_syndrome_different_observables_fails():
    """Empty syndrome (frozenset()) with different observables is a conflict."""
    m0 = _mech(0.1, detectors=frozenset(), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset(), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert not result.passed
    assert "Found 1 " in result.message


def test_three_distinct_observable_sets_in_conflict():
    """A syndrome mapping to 3+ distinct observable sets must be flagged."""
    mechs = [
        _mech(0.1, detectors=frozenset({0}), observables=frozenset({0})),
        _mech(0.1, detectors=frozenset({0}), observables=frozenset({1})),
        _mech(0.1, detectors=frozenset({0}), observables=frozenset({2})),
    ]
    result = check_correctability(_model(*mechs))
    assert not result.passed
    # All three observable sets should appear in the counter_example
    ce = assert_failed(result).counter_example
    assert "L0" in ce and "L1" in ce and "L2" in ce


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
    result = assert_failed(check_correctability(_model(*mechs)))
    assert not result.passed
    assert "more" in result.counter_example


def test_provenance_is_indexed_only_for_rendered_conflicts(monkeypatch):
    """Large conflict sets must not collect provenance for truncated output."""
    n = _MAX_SHOWN + 3
    mechs = []
    for i in range(n):
        mechs.append(_mech(0.1, detectors=frozenset({i}), observables=frozenset({0})))
        mechs.append(_mech(0.1, detectors=frozenset({i}), observables=frozenset({1})))

    captured = []
    original = checks_module._origin_mechanisms

    def capture(model, signatures):
        captured.append(signatures)
        return original(model, signatures)

    monkeypatch.setattr(checks_module, "_origin_mechanisms", capture)
    result = assert_failed(check_correctability(_model(*mechs)))

    assert len(captured) == 1
    assert captured[0] == {
        (frozenset({i}), frozenset({observable}))
        for i in range(_MAX_SHOWN)
        for observable in (0, 1)
    }
    assert len(result.counter_example_data["conflicts"]) == _MAX_SHOWN
    assert result.counter_example_data["total_conflicts"] == n
    assert result.counter_example_data["witnesses_truncated"] is True
    assert all(
        conflict["witnesses"] for conflict in result.counter_example_data["conflicts"]
    )


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


# ---------------------------------------------------------------------------
# counter_example_data
# ---------------------------------------------------------------------------


def test_passing_result_has_no_counter_example_data():
    m = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    result = check_correctability(_model(m))
    assert result.counter_example_data is None


def test_failing_result_has_counter_example_data():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = check_correctability(_model(m0, m1))
    assert result.counter_example_data is not None


def test_counter_example_data_has_conflicts_key():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    data = result.counter_example_data
    assert "conflicts" in data


def test_counter_example_data_conflicts_is_list_of_dicts():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    conflicts = result.counter_example_data["conflicts"]
    assert isinstance(conflicts, list)
    assert all(isinstance(c, dict) for c in conflicts)
    assert all("syndrome" in c and "observable_sets" in c for c in conflicts)


def test_counter_example_data_syndrome_is_sorted_list_of_ints():
    m0 = _mech(0.1, detectors=frozenset({3, 7}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({3, 7}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    syndrome = result.counter_example_data["conflicts"][0]["syndrome"]
    assert isinstance(syndrome, list)
    assert all(isinstance(d, int) for d in syndrome)
    assert syndrome == sorted(syndrome)
    assert set(syndrome) == {3, 7}


def test_counter_example_data_observable_sets_is_list_of_lists():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    obs_sets = result.counter_example_data["conflicts"][0]["observable_sets"]
    assert isinstance(obs_sets, list)
    assert all(isinstance(s, list) for s in obs_sets)


def test_counter_example_data_observable_sets_contains_both_conflicting_sets():
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    obs_sets = result.counter_example_data["conflicts"][0]["observable_sets"]
    assert [0] in obs_sets
    assert [1] in obs_sets


def test_counter_example_data_contains_rendered_conflicts_and_total_count():
    # Two conflicts: syndrome {D0} and {D1}
    m0 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({0}), observables=frozenset({1}))
    m2 = _mech(0.1, detectors=frozenset({1}), observables=frozenset({0}))
    m3 = _mech(0.1, detectors=frozenset({1}), observables=frozenset({2}))
    result = check_correctability(_model(m0, m1, m2, m3))
    assert result.counter_example_data is not None
    conflicts = result.counter_example_data["conflicts"]
    assert len(conflicts) == 2
    assert result.counter_example_data["total_conflicts"] == 2
    assert result.counter_example_data["witnesses_truncated"] is False
    syndromes = [c["syndrome"] for c in conflicts]
    assert [0] in syndromes
    assert [1] in syndromes


# ---------------------------------------------------------------------------
# Detector coordinate labels
# ---------------------------------------------------------------------------


def test_conflicting_syndrome_with_coordinates_uses_annotated_label():
    """When detector_coords is populated, conflicts must show 'Dn@(x,y)' in the counter-example."""
    m0 = _mech(0.1, detectors=frozenset({4}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({4}), observables=frozenset({1}))
    model = ErrorModel(
        detectors={4},
        observables={0, 1},
        error_mechanisms=[m0, m1],
        detector_coords={4: (3.0, 1.0)},
    )
    result = assert_failed(check_correctability(model))
    assert not result.passed
    assert "D4@(3,1)" in result.counter_example


def test_conflicting_syndrome_without_coordinates_uses_plain_label():
    """Without detector_coords the counter-example must use the plain 'Dn' format."""
    m0 = _mech(0.1, detectors=frozenset({4}), observables=frozenset({0}))
    m1 = _mech(0.1, detectors=frozenset({4}), observables=frozenset({1}))
    result = assert_failed(check_correctability(_model(m0, m1)))
    assert not result.passed
    assert "D4" in result.counter_example
    assert "@" not in result.counter_example


# ---------------------------------------------------------------------------
# from_stim_dem round-trip
# ---------------------------------------------------------------------------


def test_ambiguous_syndrome_from_stim_dem_fails():
    """Two mechanisms that share a detector but flip different observables must
    fail correctability after parsing a real DEM string via from_stim_dem."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel("error(0.1) D0 L0\nerror(0.1) D0 L1\ndetector D0")
    model = from_stim_dem(dem)
    result = assert_failed(check_correctability(model))
    assert not result.passed
    assert "D0" in result.counter_example


def test_unambiguous_dem_from_stim_dem_passes():
    """Each syndrome maps to exactly one observable set — correctability must pass."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel(
        "error(0.1) D0 L0\nerror(0.1) D1 L1\ndetector D0\ndetector D1"
    )
    model = from_stim_dem(dem)
    assert check_correctability(model).passed


# ---------------------------------------------------------------------------
# Decomposed DEM (^ component XOR semantics)
# ---------------------------------------------------------------------------


def test_decomposed_observable_cancels_no_conflict():
    """error(p) D0 L0 ^ D1 L0 has net obs={} because L0 appears in both ^ components
    (XOR semantics: even occurrences cancel).  Together with a standalone
    error(q) D0 D1 (obs={}), syndrome {D0,D1} maps to a unique observable set {}.
    Requires frontends.py to XOR-fold observables across ^ boundaries."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel(
        "error(0.001) D0 D1\nerror(0.001) D0 L0 ^ D1 L0\ndetector D0\ndetector D1"
    )
    model = from_stim_dem(dem)
    assert check_correctability(model).passed


def test_decomposed_observable_survives_odd_count():
    """error(p) D0 L0 ^ D1: L0 appears once (odd) so net obs={L0}.
    Only one syndrome→observable mapping — correctability must pass."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel("error(0.001) D0 L0 ^ D1\ndetector D0\ndetector D1")
    model = from_stim_dem(dem)
    assert check_correctability(model).passed


def test_decomposed_three_components_l0_odd_no_conflict():
    """error(p) D0 L0 ^ D1 L0 ^ D2 L0: L0 appears 3 times (odd) → net {L0}.
    Single mechanism, no conflict."""
    import stim
    from emlint.frontends import from_stim_dem

    dem = stim.DetectorErrorModel(
        "error(0.001) D0 L0 ^ D1 L0 ^ D2 L0\ndetector D0\ndetector D1\ndetector D2"
    )
    model = from_stim_dem(dem)
    assert check_correctability(model).passed
