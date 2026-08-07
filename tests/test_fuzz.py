"""Fuzz-style tests for emlint.

These tests use Hypothesis to generate random DEM trees and raw DEM strings,
then run every production check, asserting that:
- no check crashes on any generated input;
- every failing PropertyResult carries both counter_example and
  counter_example_data;
- the dispatcher and the flattened oracle agree on the verdict.

This is adversarial-ish generation with shrinking (Hypothesis), not a
coverage-guided fuzzer, but it exercises malformed-but-parseable structures,
extreme nesting, degenerate probabilities, and empty/detectorless mechanisms
that hand-written tests rarely cover.
"""

from __future__ import annotations

import pytest
import stim
from hypothesis import given, settings
import hypothesis.strategies as st

import emlint
from emlint.checks import ALL_CHECKS
from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


@st.composite
def mechanism_strategy(draw: st.DrawFn) -> ErrorMechanism:
    """A single ErrorMechanism with arbitrary detectors/observables/probability."""
    probability = draw(
        st.one_of(
            st.floats(
                min_value=-1.0, max_value=2.0, allow_nan=False, allow_infinity=False
            ),
            st.just(0.0),
            st.just(0.5),
            st.just(float("nan")),
            st.just(float("inf")),
            st.just(float("-inf")),
        )
    )
    detectors = draw(st.frozensets(st.integers(0, 6), max_size=4))
    observables = draw(st.frozensets(st.integers(0, 3), max_size=2))
    return ErrorMechanism(probability, detectors, observables)


@st.composite
def tree_strategy(draw: st.DrawFn, depth: int = 0) -> ErrorMechanism | RepeatBlock:
    """A random mechanism tree (mechanisms and nested RepeatBlocks).

    Offsets are kept non-negative and absolute_start_offset is 0 so that every
    generated tree is valid (detector IDs never go negative). This lets the
    fuzz tests exercise the checks on well-formed inputs rather than tripping
    the tree validator.
    """
    if depth >= 3 or draw(st.booleans()):
        return draw(mechanism_strategy())
    body = draw(st.lists(tree_strategy(depth + 1), max_size=4))
    count = draw(st.integers(0, 4))
    offset = draw(st.integers(0, 2))
    return RepeatBlock(tuple(body), count, offset, 0)


@st.composite
def model_strategy(draw: st.DrawFn) -> ErrorModel:
    """A random ErrorModel with a mechanism tree and detector coordinates."""
    mechanisms = draw(st.lists(tree_strategy(), max_size=6))
    # Derive detectors/observables from the mechanisms (may be empty).
    detectors = {d for m in mechanisms for d in _flatten_mech_dets(m)}
    observables = {o for m in mechanisms for o in _flatten_mech_obs(m)}
    coords = draw(
        st.one_of(
            st.just({}),
            st.dictionaries(
                st.integers(0, 6),
                st.tuples(st.floats(allow_nan=False), st.floats(allow_nan=False)),
            ),
        )
    )
    return ErrorModel(set(detectors), set(observables), list(mechanisms), dict(coords))


def _flatten_mech_dets(item: ErrorMechanism | RepeatBlock) -> set[int]:
    if isinstance(item, ErrorMechanism):
        return set(item.detectors)
    out: set[int] = set()
    for child in item.body:
        out |= _flatten_mech_dets(child)
    return out


def _flatten_mech_obs(item: ErrorMechanism | RepeatBlock) -> set[int]:
    if isinstance(item, ErrorMechanism):
        return set(item.observables)
    out: set[int] = set()
    for child in item.body:
        out |= _flatten_mech_obs(child)
    return out


# ---------------------------------------------------------------------------
# No-crash + contract invariants on random trees
# ---------------------------------------------------------------------------


@given(model=model_strategy())
@settings(max_examples=200)
def test_all_checks_never_crash_on_random_tree(model: ErrorModel) -> None:
    """Every production check returns a PropertyResult without raising."""
    for name, fn in ALL_CHECKS.items():
        result = fn(model)
        assert result.name == name
        assert result.passed in (True, False)
        if not result.passed:
            # Failing results must carry actionable counter-examples.
            assert result.counter_example is not None
            assert result.counter_example_data is not None


@given(model=model_strategy())
@settings(max_examples=200)
def test_dispatcher_matches_flattened_oracle_on_random_tree(model: ErrorModel) -> None:
    """The dispatcher verdict agrees with running checks on the flat model."""
    flat = ErrorModel(
        set(model.detectors),
        set(model.observables),
        list(model.flattened()),
        dict(model.detector_coords),
    )
    for name, fn in ALL_CHECKS.items():
        try:
            dispatched = fn(model)
        except Exception:
            # Invalid trees may raise uniformly; that is acceptable as long as
            # the flat oracle raises the same way.
            with pytest.raises(Exception):
                fn(flat)
            continue
        oracle = fn(flat)
        assert dispatched.passed == oracle.passed, name


# ---------------------------------------------------------------------------
# Raw DEM string fuzzing through the frontend
# ---------------------------------------------------------------------------


@st.composite
def raw_dem_strategy(draw: st.DrawFn) -> str:
    """Random DEM-ish text: valid instructions, malformed tokens, junk."""
    tokens = draw(
        st.lists(
            st.one_of(
                st.sampled_from(
                    [
                        "error(0.1) D0",
                        "error(0.5) D0 L0",
                        "error(0.0) D1 D2",
                        "detector(1, 2) D0",
                        "detector D1",
                        "shift_detectors 2",
                        "repeat 2 { error(0.1) D0 }",
                        "error(nan) D0",
                        "error(inf) D0",
                        "L0",
                        "D0",
                        "@@@",
                        "error(0.1) D0 ^ D1",
                        "error(0.1) D0 D1 D2 D3",
                        "repeat 0 { error(0.1) D0 }",
                    ]
                ),
                st.text(min_size=1, max_size=8),
            ),
            max_size=8,
        )
    )
    return "\n".join(tokens)


@given(dem_str=raw_dem_strategy())
@settings(max_examples=200)
def test_from_stim_dem_never_crashes_on_random_text(dem_str: str) -> None:
    """from_stim_dem either parses to a model or raises a structured error."""
    try:
        dem = stim.DetectorErrorModel(dem_str)
    except Exception:
        # stim rejected the text; nothing more to assert.
        return
    model = emlint.frontends.from_stim_dem(dem)
    # A parsed model must be traversable without crashing.
    model.flattened()
