"""Tests for emlint.model — RepeatBlock and ErrorModel.flattened()."""

from __future__ import annotations

import pytest

from emlint.model import ErrorMechanism, RepeatBlock, ErrorModel

# ---------------------------------------------------------------------------
# RepeatBlock construction
# ---------------------------------------------------------------------------


def test_repeat_block_construction():
    """RepeatBlock is a frozen dataclass with body and count."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    block = RepeatBlock(body=(mech,), count=3)
    assert block.count == 3
    assert len(block.body) == 1
    assert block.body[0] is mech


def test_repeat_block_frozen():
    """RepeatBlock is immutable."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    block = RepeatBlock(body=(mech,), count=3)
    with pytest.raises(AttributeError):
        setattr(block, "count", 5)


def test_repeat_block_hashable():
    """RepeatBlock is hashable (all members frozen)."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    block1 = RepeatBlock(body=(mech,), count=3)
    block2 = RepeatBlock(body=(mech,), count=3)
    # Both should be hashable and equal
    assert hash(block1) == hash(block2)
    assert block1 == block2


def test_repeat_block_nested():
    """RepeatBlock can nest other RepeatBlock instances."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    inner_block = RepeatBlock(body=(mech,), count=2)
    outer_block = RepeatBlock(body=(inner_block,), count=3)
    assert outer_block.count == 3
    assert len(outer_block.body) == 1
    assert isinstance(outer_block.body[0], RepeatBlock)


# ---------------------------------------------------------------------------
# ErrorModel.flattened() with flat list (no RepeatBlock)
# ---------------------------------------------------------------------------


def test_flattened_empty():
    """flattened() on an empty model returns an empty list."""
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    assert model.flattened() == []


def test_flattened_single_mechanism():
    """flattened() on a model with a single mechanism returns that mechanism."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[mech],
    )
    flat = model.flattened()
    assert len(flat) == 1
    assert flat[0] is mech


def test_flattened_multiple_mechanisms():
    """flattened() on a model with multiple mechanisms returns them in order."""
    mech1 = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    mech2 = ErrorMechanism(
        probability=0.2, detectors=frozenset({1}), observables=frozenset()
    )
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=[mech1, mech2],
    )
    flat = model.flattened()
    assert flat == [mech1, mech2]


# ---------------------------------------------------------------------------
# ErrorModel.flattened() with RepeatBlock
# ---------------------------------------------------------------------------


def test_flattened_single_repeat_block():
    """flattened() on a model with a single RepeatBlock expands it correctly."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    block = RepeatBlock(body=(mech,), count=2)
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[block],
    )
    flat = model.flattened()
    # The mechanism should appear twice
    assert len(flat) == 2
    assert flat[0] == mech
    assert flat[1] == mech


def test_flattened_repeat_block_with_multiple_items():
    """flattened() on a RepeatBlock with multiple items in body."""
    mech1 = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    mech2 = ErrorMechanism(
        probability=0.2, detectors=frozenset({1}), observables=frozenset()
    )
    block = RepeatBlock(body=(mech1, mech2), count=2)
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=[block],
    )
    flat = model.flattened()
    # Each repetition expands to (mech1, mech2), so 2 repetitions = 4 items
    assert len(flat) == 4
    assert flat[0] == mech1
    assert flat[1] == mech2
    assert flat[2] == mech1
    assert flat[3] == mech2


def test_flattened_nested_repeat_blocks():
    """flattened() on nested RepeatBlock structures expands fully."""
    mech = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    # Inner block: mech repeated 2 times
    inner_block = RepeatBlock(body=(mech,), count=2)
    # Outer block: inner_block repeated 3 times
    outer_block = RepeatBlock(body=(inner_block,), count=3)
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[outer_block],
    )
    flat = model.flattened()
    # 3 outer repetitions * 2 inner repetitions = 6 total
    assert len(flat) == 6
    assert all(m == mech for m in flat)


# ---------------------------------------------------------------------------
# Round-trip semantics
# ---------------------------------------------------------------------------


def test_flattened_roundtrip_no_nesting():
    """flattened() on a flat model returns an equivalent list."""
    mech1 = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    mech2 = ErrorMechanism(
        probability=0.2, detectors=frozenset({1}), observables=frozenset()
    )
    original: list[ErrorMechanism | RepeatBlock] = [mech1, mech2]
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=original,
    )
    flat = model.flattened()
    assert flat == original


def test_iter_flattened_matches_flattened_in_order_for_repeat_edges():
    """Lazy expansion has the same ordered mechanisms as materialized expansion."""
    before = ErrorMechanism(0.1, frozenset({0}), frozenset())
    body = (
        ErrorMechanism(0.2, frozenset({1}), frozenset({0})),
        RepeatBlock(
            (ErrorMechanism(0.3, frozenset({2}), frozenset()),),
            count=2,
            detector_offset_per_iteration=-1,
            absolute_start_offset=3,
        ),
    )
    model = ErrorModel(
        detectors=set(range(10)),
        observables={0},
        error_mechanisms=[
            before,
            RepeatBlock(
                body,
                count=2,
                detector_offset_per_iteration=3,
                absolute_start_offset=1,
            ),
            ErrorMechanism(0.4, frozenset({4}), frozenset()),
            RepeatBlock((ErrorMechanism(0.5, frozenset({5}), frozenset()),), 0, 2, 6),
        ],
    )
    assert list(model.iter_flattened()) == model.flattened()


def test_flattened_distribution_with_mixed_content():
    """flattened() correctly handles a mix of mechanisms and repeat blocks."""
    m1 = ErrorMechanism(
        probability=0.1, detectors=frozenset({0}), observables=frozenset()
    )
    m2 = ErrorMechanism(
        probability=0.2, detectors=frozenset({1}), observables=frozenset()
    )
    m3 = ErrorMechanism(
        probability=0.3, detectors=frozenset({2}), observables=frozenset()
    )

    block = RepeatBlock(body=(m2,), count=2)

    model = ErrorModel(
        detectors={0, 1, 2},
        observables=set(),
        error_mechanisms=[m1, block, m3],
    )
    flat = model.flattened()
    # Expected: m1, m2, m2 (from block), m3
    assert len(flat) == 4
    assert flat[0] == m1
    assert flat[1] == m2
    assert flat[2] == m2
    assert flat[3] == m3


# ---------------------------------------------------------------------------
# detector_coords dimensionality
# ---------------------------------------------------------------------------


def test_coord_dimensionality_uniform_2d_passes():
    """Uniform 2-coord (spatial-only) detectors validate without error."""
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=[],
        detector_coords={0: (0.0, 0.0), 1: (1.0, 0.0)},
    )
    model._validate_tree()  # must not raise


def test_coord_dimensionality_uniform_3d_passes():
    """Uniform 3-coord (spacetime) detectors validate without error."""
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=[],
        detector_coords={0: (0.0, 0.0, 1.0), 1: (1.0, 0.0, 1.0)},
    )
    model._validate_tree()  # must not raise


def test_coord_dimensionality_empty_passes():
    """A model with no coordinates validates without error."""
    model = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    model._validate_tree()  # must not raise


def test_coord_dimensionality_mixed_is_accepted():
    """Stim-valid mixed-dimensional detector coordinates remain lintable."""
    model = ErrorModel(
        detectors={0, 1},
        observables=set(),
        error_mechanisms=[],
        detector_coords={0: (0.0, 0.0), 1: (0.0, 0.0, 1.0)},
    )
    model._validate_tree()
    assert model.flattened() == []
