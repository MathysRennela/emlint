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
    _observable_distances,
    check_boundary_symmetry,
    check_connectivity,
    check_correctability,
    check_detectability,
    check_duplicates,
<<<<<<< HEAD
=======
    check_high_probability_mechanisms,
>>>>>>> 5972866 (Release v0.2.4)
    check_null_mechanism,
    check_observable_coverage,
    check_probability_bounds,
    check_sensitivity,
)
from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock

_CHECKS = (
    check_boundary_symmetry,
    check_connectivity,
    check_correctability,
    check_detectability,
    check_duplicates,
    check_high_probability_mechanisms,
    check_null_mechanism,
    check_observable_coverage,
    check_probability_bounds,
<<<<<<< HEAD
    check_duplicates,
    check_correctability,
    check_null_mechanism,
=======
    check_sensitivity,
>>>>>>> 5972866 (Release v0.2.4)
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


def _connectivity_oracle(model: ErrorModel) -> bool:
    g: dict[object, set[object]] = {d: set() for d in model.detectors}
    boundary_nodes = (
        {obs: f"boundary_L{obs}" for obs in model.observables}
        if model.observables
        else {}
    )
    for mech in model.flattened():
        dets = sorted(mech.detectors)
        if len(dets) == 0:
            continue
        if len(dets) == 1:
            if mech.observables and boundary_nodes:
                known = [obs for obs in mech.observables if obs in boundary_nodes]
                if known:
                    for obs in known:
                        g.setdefault(dets[0], set()).add(boundary_nodes[obs])
                        g.setdefault(boundary_nodes[obs], set()).add(dets[0])
                else:
                    g.setdefault(dets[0], set()).add("boundary_noobs")
                    g.setdefault("boundary_noobs", set()).add(dets[0])
            elif boundary_nodes:
                g.setdefault(dets[0], set()).add("boundary_noobs")
                g.setdefault("boundary_noobs", set()).add(dets[0])
            else:
                g.setdefault(dets[0], set()).add("boundary")
                g.setdefault("boundary", set()).add(dets[0])
        else:
            for i in range(len(dets)):
                for j in range(i + 1, len(dets)):
                    g.setdefault(dets[i], set()).add(dets[j])
                    g.setdefault(dets[j], set()).add(dets[i])
    unseen = set(g)
    components = 0
    while unseen:
        components += 1
        start = unseen.pop()
        stack = [start]
        while stack:
            node = stack.pop()
            for neighbour in g.get(node, ()):
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    stack.append(neighbour)
    return components <= 1


def _boundary_symmetry_oracle(model: ErrorModel) -> bool:
    if len(model.observables) < 2:
        return True
    reachable = {
        obs: d for obs, d in _observable_distances(model).items() if d is not None
    }
    if not reachable:
        return True
    return max(reachable.values()) - min(reachable.values()) <= 0


def _oracle_results(model: ErrorModel) -> dict[str, tuple[bool, str]]:
    mechanisms = model.flattened()

    signatures = [(m.detectors, m.observables) for m in mechanisms]
    syndrome_to_observables: dict[frozenset[int], set[frozenset[int]]] = {}
    for mechanism in mechanisms:
        syndrome_to_observables.setdefault(mechanism.detectors, set()).add(
            mechanism.observables
        )

    probability_invalid = any(
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
        # A mechanism-free DEM is reported as skipped (passed=False, status
        # "skipped"): the two predicates cannot separate a dead object from an
        # empty audit, and the report layer discloses the model as vacuous.
        "sensitivity": (
            (
                False
                if not mechanisms
                else model.detectors <= {d for m in mechanisms for d in m.detectors}
            ),
            "warning",
        ),
        "observable_coverage": (
            (
                False
                if not mechanisms
                else model.observables <= {o for m in mechanisms for o in m.observables}
            ),
            "error",
        ),
        "probability_bounds": (
            not probability_invalid,
            "error",
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
        "null_mechanism": (
            all(m.detectors or m.observables for m in mechanisms),
            "warning",
        ),
<<<<<<< HEAD
=======
        "high_probability_mechanisms": (
            all(not (m.probability > 0.3) for m in mechanisms),
            "warning",
        ),
        "connectivity": (
            _connectivity_oracle(model),
            "warning",
        ),
        "boundary_symmetry": (
            _boundary_symmetry_oracle(model),
            "warning",
        ),
>>>>>>> 5972866 (Release v0.2.4)
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
