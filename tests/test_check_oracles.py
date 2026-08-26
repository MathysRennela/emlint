"""Independent executable specifications for production checks.

These tests deliberately do not call private implementation helpers.  The
specifications operate on ``model.flattened()`` and use direct set/grouping
operations, so they can detect shared mistakes in the optimized production
paths.
"""

from __future__ import annotations

import math

from hypothesis import given, strategies as st

from emlint.checks import (
    check_correctability,
    check_detectability,
    check_duplicates,
    check_observable_coverage,
    check_probability_bounds,
    check_sensitivity,
)
from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock

_CHECKS = (
    check_detectability,
    check_sensitivity,
    check_observable_coverage,
    check_probability_bounds,
    check_duplicates,
    check_correctability,
)


@st.composite
def _flat_models(draw):
    mechanism_count = draw(st.integers(min_value=0, max_value=8))
    mechanisms = []
    for _ in range(mechanism_count):
        mechanisms.append(
            ErrorMechanism(
                probability=draw(
                    st.one_of(
                        st.floats(
                            min_value=-0.5,
                            max_value=1.5,
                            allow_nan=False,
                            allow_infinity=False,
                        ),
                        st.sampled_from([float("nan"), float("inf"), float("-inf")]),
                    )
                ),
                detectors=draw(st.frozensets(st.integers(0, 8))),
                observables=draw(st.frozensets(st.integers(0, 4))),
            )
        )
    declared_detectors = draw(st.frozensets(st.integers(0, 10)))
    declared_observables = draw(st.frozensets(st.integers(0, 5)))
    return ErrorModel(
        detectors=set(declared_detectors),
        observables=set(declared_observables),
        error_mechanisms=mechanisms,
    )


@st.composite
def _repeat_models(draw):
    body_count = draw(st.integers(min_value=0, max_value=4))
    body = tuple(
        ErrorMechanism(
            probability=draw(
                st.floats(
                    min_value=0.0,
                    max_value=0.9,
                    allow_nan=False,
                    allow_infinity=False,
                )
            ),
            detectors=draw(st.frozensets(st.integers(0, 3))),
            observables=draw(st.frozensets(st.integers(0, 2))),
        )
        for _ in range(body_count)
    )
    count = draw(st.integers(min_value=0, max_value=4))
    stride = draw(st.integers(min_value=0, max_value=3))
    start = draw(st.integers(min_value=0, max_value=4))
    trailing = draw(st.lists(st.integers(0, 3), max_size=3))
    trailing_mechanisms = tuple(
        ErrorMechanism(0.1, frozenset({detector}), frozenset()) for detector in trailing
    )
    block = RepeatBlock(body, count, stride, start)
    return ErrorModel(
        detectors=set(range(16)),
        observables={0, 1, 2},
        error_mechanisms=[block, *trailing_mechanisms],
    )


def _oracle_results(model: ErrorModel) -> dict[str, tuple[bool, str]]:
    mechanisms = model.flattened()

    signatures = [(m.detectors, m.observables) for m in mechanisms]
    syndrome_to_observables: dict[frozenset[int], set[frozenset[int]]] = {}
    for mechanism in mechanisms:
        syndrome_to_observables.setdefault(mechanism.detectors, set()).add(
            mechanism.observables
        )

    probability_invalid = any(
        math.isnan(m.probability) or not (0.0 < m.probability <= 0.5)
        for m in mechanisms
    )
    probability_error = any(
        math.isnan(m.probability)
        or not math.isfinite(m.probability)
        or m.probability <= 0.0
        for m in mechanisms
    )
    return {
        "detectability": (
            all(not m.observables or m.detectors for m in mechanisms),
            "error",
        ),
        "sensitivity": (
            model.detectors <= {d for m in mechanisms for d in m.detectors},
            "warning",
        ),
        "observable_coverage": (
            model.observables <= {o for m in mechanisms for o in m.observables},
            "error",
        ),
        "probability_bounds": (
            not probability_invalid,
            "error" if not probability_invalid or probability_error else "warning",
        ),
        "duplicates": (
            len(signatures) == len(set(signatures)),
            "warning",
        ),
        "correctability": (
            all(
                len(observables) <= 1
                for observables in syndrome_to_observables.values()
            ),
            "warning",
        ),
    }


def _assert_matches_oracle(model: ErrorModel) -> None:
    expected = _oracle_results(model)
    for check in _CHECKS:
        result = check(model)
        assert (result.passed, result.severity) == expected[result.name]


def test_every_registered_check_has_an_oracle_entry():
    """A check missing from `_oracle_results` gets no semantic verification here.

    `_CHECKS`/`_oracle_results` are hand-maintained; a new check added to
    `ALL_CHECKS` without a matching entry would silently skip this file's
    oracle comparison. Guard the registry against that gap explicitly.
    """
    from emlint.checks import ALL_CHECKS

    probe = ErrorModel(detectors=set(), observables=set(), error_mechanisms=[])
    covered = _oracle_results(probe)
    missing = set(ALL_CHECKS) - set(covered)
    assert not missing, f"no oracle entry for: {sorted(missing)}"
    assert {check.__name__ for check in _CHECKS} == {
        f"check_{name}" for name in ALL_CHECKS
    }


@given(model=_flat_models())
def test_checks_match_independent_specifications_on_flat_models(model):
    _assert_matches_oracle(model)


@given(model=_repeat_models())
def test_checks_match_independent_specifications_on_repeat_models(model):
    _assert_matches_oracle(model)


def _flattened_model(model: ErrorModel) -> ErrorModel:
    return ErrorModel(
        detectors=set(model.detectors),
        observables=set(model.observables),
        error_mechanisms=list(model.flattened()),
        detector_coords=dict(model.detector_coords),
    )


@given(model=_repeat_models())
def test_flattening_preserves_each_check_verdict(model):
    flattened = _flattened_model(model)
    for check in _CHECKS:
        source_result = check(model)
        flat_result = check(flattened)
        assert (source_result.passed, source_result.severity) == (
            flat_result.passed,
            flat_result.severity,
        )


@given(model=_flat_models())
def test_permuting_mechanisms_preserves_each_check_verdict(model):
    permuted = ErrorModel(
        detectors=set(model.detectors),
        observables=set(model.observables),
        error_mechanisms=list(reversed(model.error_mechanisms)),
        detector_coords=dict(model.detector_coords),
    )
    for check in _CHECKS:
        original = check(model)
        reordered = check(permuted)
        assert (original.passed, original.severity) == (
            reordered.passed,
            reordered.severity,
        )
