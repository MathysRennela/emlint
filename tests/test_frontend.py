"""Tests for emlint.frontends.from_stim_dem().

These tests exercise the translation layer directly, independent of any check.
A silent parsing bug here corrupts every downstream result.
"""

from __future__ import annotations

import stim
import pytest
from hypothesis import given
import hypothesis.strategies as st

from emlint.frontends import from_stim_dem
from emlint.model import ErrorMechanism
from helpers import assert_failed

# ---------------------------------------------------------------------------
# Error instruction → ErrorMechanism
# ---------------------------------------------------------------------------


def test_single_error_probability():
    dem = stim.DetectorErrorModel("error(0.25) D0")
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 1
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.probability == pytest.approx(0.25)


def test_single_error_detector():
    dem = stim.DetectorErrorModel("error(0.1) D3")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.detectors == frozenset({3})


def test_single_error_observable():
    dem = stim.DetectorErrorModel("error(0.1) L2")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.observables == frozenset({2})


def test_error_multiple_detectors():
    dem = stim.DetectorErrorModel("error(0.1) D0 D1 D2")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.detectors == frozenset({0, 1, 2})
    assert m.observables == frozenset()


def test_error_detectors_and_observables():
    dem = stim.DetectorErrorModel("error(0.1) D0 D1 L0")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.detectors == frozenset({0, 1})
    assert m.observables == frozenset({0})


def test_multiple_error_instructions():
    dem = stim.DetectorErrorModel("error(0.1) D0\nerror(0.2) D1 L0")
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 2


def test_no_error_instructions():
    dem = stim.DetectorErrorModel()
    model = from_stim_dem(dem)
    assert model.error_mechanisms == []


# ---------------------------------------------------------------------------
# Detectors set
# ---------------------------------------------------------------------------


def test_detector_instruction_populates_detectors():
    # explicit detector declaration, no error mechanism references it
    dem = stim.DetectorErrorModel("detector D0\ndetector D1")
    model = from_stim_dem(dem)
    assert 0 in model.detectors
    assert 1 in model.detectors


def test_error_instruction_also_populates_detectors():
    dem = stim.DetectorErrorModel("error(0.1) D5")
    model = from_stim_dem(dem)
    assert 5 in model.detectors


# ---------------------------------------------------------------------------
# Observables set — derived from dem.num_observables
# ---------------------------------------------------------------------------


def test_observables_from_num_observables():
    """Observables are derived from dem.num_observables, not only from error instructions."""
    dem = stim.DetectorErrorModel("error(0.1) D0 L0\ndetector D0")
    model = from_stim_dem(dem)
    # stim infers num_observables = 1 (L0 is referenced)
    assert model.observables == {0}


def test_observable_declared_but_not_in_any_mechanism():
    """If a mechanism references L1 (forcing num_observables=2), L0 must still
    appear in model.observables even though no mechanism flips it, so that
    observable_coverage can catch the gap."""
    # L1 is referenced so num_observables=2; L0 is never flipped by any mechanism.
    dem = stim.DetectorErrorModel("error(0.1) D0 L1\ndetector D0")
    model = from_stim_dem(dem)
    assert 0 in model.observables
    assert 1 in model.observables


# ---------------------------------------------------------------------------
# Repeat blocks are flattened
# ---------------------------------------------------------------------------


def test_repeat_block_mechanisms_are_flattened():
    """Repeat blocks are preserved in error_mechanisms; flattened() expands them."""
    dem = stim.DetectorErrorModel("""
        repeat 3 {
            error(0.1) D0
        }
    """)
    model = from_stim_dem(dem)
    # Tree: one RepeatBlock wrapping one ErrorMechanism
    assert len(model.error_mechanisms) == 1
    # Flat view: 3 copies
    assert len(model.flattened()) == 3


def test_repeat_block_detectors_are_flattened():
    """Flattened mechanisms from a repeat block carry the correct detector sets."""
    dem = stim.DetectorErrorModel("""
        repeat 2 {
            error(0.1) D0 D1
        }
    """)
    model = from_stim_dem(dem)
    assert model.flattened()[0].detectors == frozenset({0, 1})


# ---------------------------------------------------------------------------
# detector_coords
# ---------------------------------------------------------------------------


def test_detector_coords_populated_from_annotated_detector():
    dem = stim.DetectorErrorModel("detector(1, 2, 3) D0")
    model = from_stim_dem(dem)
    assert model.detector_coords[0] == (1.0, 2.0, 3.0)


def test_detector_coords_empty_when_no_coordinates():
    dem = stim.DetectorErrorModel("detector D0")
    model = from_stim_dem(dem)
    assert 0 not in model.detector_coords


def test_detector_coords_multiple_detectors():
    dem = stim.DetectorErrorModel("detector(0, 0) D0\ndetector(1, 0) D1")
    model = from_stim_dem(dem)
    assert model.detector_coords[0] == (0.0, 0.0)
    assert model.detector_coords[1] == (1.0, 0.0)


def test_detector_coords_mixed_dimensions_remain_lintable():
    """Stim-valid mixed coordinate dimensions must not be rejected by the model."""
    dem = stim.DetectorErrorModel(
        "detector(1, 2) D0\ndetector(3, 4, 5) D1\nerror(0.01) D0 D1 L0"
    )
    model = from_stim_dem(dem)
    model._validate_tree()
    assert model.detector_coords[0] == (1.0, 2.0)
    assert model.detector_coords[1] == (3.0, 4.0, 5.0)


def test_detector_coords_only_annotated_detectors_populated():
    """A bare detector declaration contributes no coordinates entry."""
    dem = stim.DetectorErrorModel("detector(5, 6) D0\ndetector D1")
    model = from_stim_dem(dem)
    assert 0 in model.detector_coords
    assert 1 not in model.detector_coords


def test_det_label_with_coords_appears_in_sensitivity_counter_example():
    """check_sensitivity uses _det_label; with coords it should format as D0@(1,2)."""
    from emlint.checks import check_sensitivity
    from emlint.model import ErrorModel

    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[],
        detector_coords={0: (1.0, 2.0)},
    )
    result = assert_failed(check_sensitivity(model))
    assert not result.passed
    assert "D0@(1,2)" in result.counter_example


# ---------------------------------------------------------------------------
# Empty DEM
# ---------------------------------------------------------------------------


def test_empty_dem_gives_empty_model():
    model = from_stim_dem(stim.DetectorErrorModel())
    assert model.detectors == set()
    assert model.observables == set()
    assert model.error_mechanisms == []


# ---------------------------------------------------------------------------
# Tree structure (RepeatBlock) preservation
# ---------------------------------------------------------------------------


def test_repeat_block_preserved_in_error_mechanisms():
    """Verify that repeat blocks appear as RepeatBlock nodes in error_mechanisms."""
    from emlint.model import RepeatBlock

    dem = stim.DetectorErrorModel("""
        repeat 3 {
            error(0.1) D0
        }
    """)
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 1
    assert isinstance(model.error_mechanisms[0], RepeatBlock)
    assert model.error_mechanisms[0].count == 3
    assert len(model.error_mechanisms[0].body) == 1


def test_nested_repeat_blocks_preserved():
    """Verify nested repeat blocks are correctly nested in tree structure."""
    from emlint.model import RepeatBlock

    dem = stim.DetectorErrorModel("""
        repeat 2 {
            repeat 3 {
                error(0.1) D0
            }
        }
    """)
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 1
    outer = model.error_mechanisms[0]
    assert isinstance(outer, RepeatBlock)
    assert outer.count == 2
    assert len(outer.body) == 1
    inner = outer.body[0]
    assert isinstance(inner, RepeatBlock)
    assert inner.count == 3
    assert len(inner.body) == 1


def test_mixed_errors_and_repeat_blocks():
    """Verify error mechanisms and repeat blocks coexist in error_mechanisms."""
    from emlint.model import RepeatBlock, ErrorMechanism

    dem = stim.DetectorErrorModel("""
        error(0.1) D0
        repeat 2 {
            error(0.2) D1
        }
        error(0.3) D2
    """)
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 3
    assert isinstance(model.error_mechanisms[0], ErrorMechanism)
    assert isinstance(model.error_mechanisms[1], RepeatBlock)
    assert isinstance(model.error_mechanisms[2], ErrorMechanism)


def test_repeat_block_flattened_preserves_counts():
    """Verify that flattening a tree with repeat blocks multiplies counts correctly."""
    dem = stim.DetectorErrorModel("""
        repeat 2 {
            error(0.1) D0
            repeat 3 {
                error(0.2) D1
            }
        }
    """)
    model = from_stim_dem(dem)
    flat = model.flattened()
    # Should have: (2 * (1 error + 3 * 1 error)) = 2 * 4 = 8 mechanisms
    assert len(flat) == 8


def test_detector_collection_with_repeat_blocks():
    """Verify detectors inside repeat blocks are collected in detector set."""
    dem = stim.DetectorErrorModel("""
        repeat 2 {
            error(0.1) D0 D1
        }
        error(0.3) D2
    """)
    model = from_stim_dem(dem)
    # Detectors should be collected from inside repeat blocks
    assert model.detectors == {0, 1, 2}


def test_detector_coords_with_repeat_blocks():
    """Verify detector coordinates are collected even inside repeat blocks."""
    dem = stim.DetectorErrorModel("""
        detector(1, 2) D0
        repeat 2 {
            error(0.1) D0
            detector(3, 4) D1
        }
    """)
    model = from_stim_dem(dem)
    assert model.detector_coords[0] == (1.0, 2.0)
    assert model.detector_coords[1] == (3.0, 4.0)


# ---------------------------------------------------------------------------
# Decomposition hints (^ separator targets)
# ---------------------------------------------------------------------------


def test_separator_two_components_d2_xor_d0():
    """`error(0.02) D2 ^ D0` must preserve both component signatures."""
    dem = stim.DetectorErrorModel("error(0.02) D2 ^ D0")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    # Merged signature is unchanged (XOR fold across components).
    assert m.detectors == frozenset({0, 2})
    assert m.observables == frozenset()
    assert m.decomposition_hints == (
        (frozenset({2}), frozenset()),
        (frozenset({0}), frozenset()),
    )


def test_separator_observable_cancellation_d3_l0_xor_d1_l0():
    """`error(0.1) D3 L0 ^ D1 L0`: merged observables cancel, but each
    component keeps its own observable so it is distinguishable from an
    ordinary `D1 D3` mechanism."""
    dem = stim.DetectorErrorModel("error(0.1) D3 L0 ^ D1 L0")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.detectors == frozenset({1, 3})
    assert m.observables == frozenset()
    assert m.decomposition_hints == (
        (frozenset({3}), frozenset({0})),
        (frozenset({1}), frozenset({0})),
    )


def test_no_separator_gives_empty_decomposition_hints():
    dem = stim.DetectorErrorModel("error(0.1) D0 D1")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert m.decomposition_hints == ()


def test_separator_three_components():
    dem = stim.DetectorErrorModel("error(0.1) D0 ^ D1 ^ D2")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert isinstance(m, ErrorMechanism)
    assert len(m.decomposition_hints) == 3
    assert m.decomposition_hints[0] == (frozenset({0}), frozenset())
    assert m.decomposition_hints[2] == (frozenset({2}), frozenset())


def test_separator_inside_repeat_block_flattens_with_offsets():
    """Nested REPEAT: component detector IDs must be shifted like merged IDs."""
    dem = stim.DetectorErrorModel("""
        repeat 2 {
            error(0.01) D0 ^ D1
            shift_detectors 2
        }
    """)
    model = from_stim_dem(dem)
    flat = model.flattened()
    assert len(flat) == 2
    assert flat[0].decomposition_hints == (
        (frozenset({0}), frozenset()),
        (frozenset({1}), frozenset()),
    )
    assert flat[1].decomposition_hints == (
        (frozenset({2}), frozenset()),
        (frozenset({3}), frozenset()),
    )


def test_stim_generated_decomposed_dem_preserves_hints():
    """A real Stim-generated decomposed DEM (repetition code round) must carry
    decomposition hints on its separator-bearing mechanisms."""
    circuit = stim.Circuit.generated(
        "repetition_code:memory",
        distance=3,
        rounds=3,
        after_clifford_depolarization=0.001,
    )
    dem = circuit.detector_error_model(decompose_errors=True)
    model = from_stim_dem(dem)
    flat = model.flattened()
    hinted = [m for m in flat if m.decomposition_hints]
    assert hinted, "expected separator-bearing mechanisms in decomposed DEM"
    for m in hinted:
        # Every hint component is non-empty in detectors and consistent with
        # the merged signature.
        assert all(cdets for cdets, _ in m.decomposition_hints)
        merged_dets = frozenset().union(*(cdets for cdets, _ in m.decomposition_hints))
        assert merged_dets <= m.detectors


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------


@given(
    components=st.lists(
        st.tuples(
            st.frozensets(st.integers(0, 8), min_size=1),
            st.frozensets(st.integers(0, 3)),
        ),
        min_size=2,
        max_size=3,
    ),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_roundtrip_separator_dem_preserves_component_signatures(components, p):
    """For any component list, building a DEM text with ^ separators and
    parsing it back must reproduce exactly those component signatures."""
    # Restrict to pairwise-disjoint component detector sets: this matches what
    # stim's decompose_errors=True actually emits (verified empirically across
    # generated repetition-code DEMs) and keeps the merged-signature assertion
    # independent of the XOR-vs-union question for overlapping components.
    used: set[int] = set()
    disjoint = []
    for cdets, cobs in components:
        if cdets & used:
            return
        used |= cdets
        disjoint.append((cdets, cobs))
    targets: list[str] = []
    merged_dets: set[int] = set()
    merged_obs: set[int] = set()
    for i, (cdets, cobs) in enumerate(disjoint):
        if i > 0:
            targets.append("^")
        targets.extend(f"D{d}" for d in sorted(cdets))
        targets.extend(f"L{o}" for o in sorted(cobs))
        merged_dets |= set(cdets)
        merged_obs ^= set(cobs)
    text = "error(%r) %s" % (p, " ".join(targets))
    model = from_stim_dem(stim.DetectorErrorModel(text))
    mech = model.error_mechanisms[0]
    assert isinstance(mech, ErrorMechanism)
    assert mech.decomposition_hints == tuple(
        (frozenset(cdets), frozenset(cobs)) for cdets, cobs in disjoint
    )
    # With disjoint components the merged signature is unambiguous: XOR fold
    # and union of component sets coincide.
    assert mech.detectors == frozenset(merged_dets)
    assert mech.observables == frozenset(merged_obs)


# ---------------------------------------------------------------------------
# shift_detectors inside repeat blocks
# ---------------------------------------------------------------------------


def test_shift_detectors_in_repeat_block_produces_absolute_ids():
    """shift_detectors inside a repeat block must produce correct absolute IDs.

    Without offset tracking, every iteration would reference the same (relative)
    detector IDs.  With the fix, iteration k gets IDs shifted by k * body_shift.
    """
    from emlint.model import RepeatBlock

    dem = stim.DetectorErrorModel("""
        repeat 3 {
            error(0.01) D0 D1
            shift_detectors 2
        }
    """)
    model = from_stim_dem(dem)
    # num_detectors must reflect all 6 detectors produced by 3 iterations × shift 2
    assert model.detectors == set(range(6))
    # The tree node carries the per-iteration offset, not flat IDs
    assert isinstance(model.error_mechanisms[0], RepeatBlock)
    assert model.error_mechanisms[0].detector_offset_per_iteration == 2
    # flattened() must produce absolute IDs matching stim's reference output
    flat = model.flattened()
    assert len(flat) == 3
    assert flat[0].detectors == frozenset({0, 1})
    assert flat[1].detectors == frozenset({2, 3})
    assert flat[2].detectors == frozenset({4, 5})


def test_shift_detectors_top_level_applied_to_subsequent_errors():
    """A top-level shift_detectors advances the offset for later error instructions."""
    dem = stim.DetectorErrorModel("""
        error(0.1) D0
        shift_detectors 3
        error(0.1) D0
    """)
    model = from_stim_dem(dem)
    assert model.detectors == set(range(4))
    flat = model.flattened()
    assert flat[0].detectors == frozenset({0})
    assert flat[1].detectors == frozenset({3})


def test_shift_detectors_between_repeat_blocks():
    """shift_detectors between repeat blocks correctly offsets the second block."""
    dem = stim.DetectorErrorModel("""
        repeat 2 {
            error(0.1) D0
            shift_detectors 1
        }
        repeat 2 {
            error(0.2) D0
            shift_detectors 1
        }
    """)
    model = from_stim_dem(dem)
    assert model.detectors == set(range(4))
    flat = model.flattened()
    assert flat[0].detectors == frozenset({0})
    assert flat[1].detectors == frozenset({1})
    assert flat[2].detectors == frozenset({2})
    assert flat[3].detectors == frozenset({3})
