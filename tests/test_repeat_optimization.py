from __future__ import annotations

from functools import partial
from typing import Any, Callable, cast

import pytest
import stim
from hypothesis import given
import hypothesis.strategies as st

import emlint
import emlint.checks as checks_module
from emlint import _FlattenCache, _ReadOnlyModelView
from emlint.checks import (
    check_correctability,
    check_detectability,
    check_duplicates,
    check_observable_coverage,
    check_probability_bounds,
    check_sensitivity,
    _format_mech,
    _iter_repeat_templates,
    _iter_scope_mechanisms,
    _template_witness,
    _witness,
)
from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock
from emlint.report import PropertyResult
from helpers import assert_failed


def _flat_model(model: ErrorModel) -> ErrorModel:
    """Build the flattened oracle model while preserving source metadata."""
    flat_mechanisms: list[ErrorMechanism | RepeatBlock] = list(model.flattened())
    return ErrorModel(
        set(model.detectors),
        set(model.observables),
        flat_mechanisms,
        dict(model.detector_coords),
    )


def _assert_same_oracle_result(check, model: ErrorModel) -> None:
    """Compare verdicts plus template/dead-set data with the flat oracle."""
    optimized = check(model)
    oracle = check(_flat_model(model))
    assert (optimized.passed, optimized.severity) == (
        oracle.passed,
        oracle.severity,
    )
    assert (optimized.counter_example is None) == (oracle.counter_example is None)
    assert (optimized.counter_example_data is None) == (
        oracle.counter_example_data is None
    )
    if check is check_sensitivity and not optimized.passed:
        assert (
            optimized.counter_example_data["detectors"]
            == oracle.counter_example_data["detectors"]
        )
    if (
        check in (check_detectability, check_probability_bounds)
        and not optimized.passed
    ):
        if check is check_probability_bounds:
            expected = {
                _format_mech(_template_witness(template))
                for template in _iter_repeat_templates(model)
                if template.mechanism.probability != template.mechanism.probability
                or not (0.0 < template.mechanism.probability <= 0.5)
            }
        else:
            expected = {
                _format_mech(_witness(scope))
                for scope in _iter_scope_mechanisms(model)
                if not scope.mechanism.detectors and scope.mechanism.observables
            }
        assert set(optimized.counter_example_data["mechanisms"]) == expected
        assert set(oracle.counter_example_data["mechanisms"]) >= expected
    if check is check_observable_coverage:
        assert optimized.counter_example_data == oracle.counter_example_data


_OPTIMIZED_CHECKS = (
    check_detectability,
    check_probability_bounds,
    check_observable_coverage,
    check_sensitivity,
    check_duplicates,
    check_correctability,
)


def _repeat_model(*, count: int, stride: int, start: int = 10) -> ErrorModel:
    return ErrorModel(
        detectors=set(range(20)),
        observables={0},
        error_mechanisms=[
            RepeatBlock(
                (ErrorMechanism(0.1, frozenset({1}), frozenset({0})),),
                count,
                stride,
                start,
            )
        ],
    )


# Passing cases


def test_nested_normalization_matches_flattened_oracle() -> None:
    inner = RepeatBlock((ErrorMechanism(0.1, frozenset({1}), frozenset({0})),), 2, 3, 4)
    outer = RepeatBlock((inner,), 2, 5, 7)
    model = ErrorModel(set(range(30)), {0}, [outer])
    assert [m.detectors for m in model.flattened()] == [
        frozenset({12}),
        frozenset({15}),
        frozenset({17}),
        frozenset({20}),
    ]
    assert check_detectability(model).passed
    assert check_observable_coverage(model).passed


@pytest.mark.parametrize("stride,count", [(2, 4), (-2, 4), (0, 4), (2, 0), (2, 1)])
def test_sensitivity_edges_match_flattened_oracle(stride: int, count: int) -> None:
    model = _repeat_model(count=count, stride=stride)
    participating = {d for mech in model.flattened() for d in mech.detectors}
    result = check_sensitivity(model)
    dead = set(assert_failed(result).counter_example_data["detectors"])
    assert dead == model.detectors - participating


# Failing cases


@pytest.mark.parametrize(
    "check",
    [
        check_detectability,
        check_probability_bounds,
        check_observable_coverage,
        check_sensitivity,
        check_duplicates,
        check_correctability,
    ],
)
def test_negative_absolute_detector_id_raises_uniformly(check) -> None:
    invalid = ErrorModel(
        {0},
        {0},
        [
            RepeatBlock(
                (ErrorMechanism(0.1, frozenset({0}), frozenset({0})),),
                2,
                -1,
            )
        ],
    )
    with pytest.raises(ValueError):
        check(invalid)
    with pytest.raises(ValueError):
        invalid.flattened()


@pytest.mark.parametrize("bad_count", [True, 1.5])
def test_non_exact_repeat_count_raises_through_all_checks(bad_count) -> None:
    invalid = ErrorModel(set(), set(), [RepeatBlock((), bad_count)])
    for check in (
        check_detectability,
        check_probability_bounds,
        check_observable_coverage,
        check_sensitivity,
        check_duplicates,
        check_correctability,
    ):
        with pytest.raises(TypeError):
            check(invalid)
    with pytest.raises(TypeError):
        invalid.flattened()


def test_invalid_repeat_contract_raises_for_optimized_and_flattened_paths() -> None:
    invalid = ErrorModel(
        set(),
        set(),
        [RepeatBlock((), -1)],
    )
    with pytest.raises(ValueError):
        check_detectability(invalid)
    with pytest.raises(ValueError):
        invalid.flattened()


@pytest.mark.parametrize(
    ("make_model", "error_type"),
    [
        (lambda: ErrorModel(set(), set(), [RepeatBlock((), -1)]), ValueError),
        (lambda: ErrorModel(set(), set(), [RepeatBlock((), True)]), TypeError),
        (
            lambda: ErrorModel(set(), set(), [RepeatBlock((), cast(Any, 1.5))]),
            TypeError,
        ),
        (
            lambda: ErrorModel(
                {0},
                set(),
                [
                    RepeatBlock(
                        (ErrorMechanism(0.1, frozenset({0}), frozenset()),), 1, True
                    )
                ],
            ),
            TypeError,
        ),
        (
            lambda: ErrorModel(
                {0},
                set(),
                [
                    RepeatBlock(
                        (ErrorMechanism(0.1, frozenset({0}), frozenset()),),
                        1,
                        cast(Any, 1.5),
                    )
                ],
            ),
            TypeError,
        ),
        (
            lambda: ErrorModel(
                {0},
                set(),
                [
                    RepeatBlock(
                        (ErrorMechanism(0.1, frozenset({0}), frozenset()),), 1, 0, True
                    )
                ],
            ),
            TypeError,
        ),
        (
            lambda: ErrorModel(
                {0},
                set(),
                [
                    RepeatBlock(
                        (ErrorMechanism(0.1, frozenset({0}), frozenset()),),
                        1,
                        0,
                        cast(Any, 1.5),
                    )
                ],
            ),
            TypeError,
        ),
        (
            lambda: ErrorModel(
                {0},
                set(),
                [RepeatBlock((ErrorMechanism(0.1, frozenset({-1}), frozenset()),), 1)],
            ),
            ValueError,
        ),
        (
            lambda: ErrorModel(
                {0},
                {0},
                [RepeatBlock((ErrorMechanism(0.1, frozenset(), frozenset({-1})),), 1)],
            ),
            ValueError,
        ),
        (
            lambda: ErrorModel(set(), set(), [cast(Any, object())]),
            TypeError,
        ),
        (
            lambda: ErrorModel(
                {0},
                set(),
                [
                    RepeatBlock(
                        (ErrorMechanism(0.1, frozenset({0}), frozenset()),), 1, 0, -1
                    )
                ],
            ),
            ValueError,
        ),
    ],
)
def test_invalid_tree_matrix_raises_through_checks_flatten_and_dispatch(
    make_model: Callable[[], ErrorModel],
    error_type: type[Exception],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = make_model()
    for check in _OPTIMIZED_CHECKS:
        with pytest.raises(error_type):
            check(invalid)
    with pytest.raises(error_type):
        invalid.flattened()

    monkeypatch.setattr(emlint.frontends, "from_stim_dem", lambda dem: invalid)
    with pytest.raises(error_type):
        emlint.check("error(0.1) D0", checks={"detectability": check_detectability})


def test_valid_negative_shift_with_nonnegative_ids_is_accepted() -> None:
    model = ErrorModel(
        {2, 3},
        set(),
        [RepeatBlock((ErrorMechanism(0.1, frozenset({2}), frozenset()),), 2, -1, 1)],
    )
    assert [m.detectors for m in model.flattened()] == [frozenset({3}), frozenset({2})]
    assert check_sensitivity(model).passed


def test_depth_three_normalization_matches_flat_oracle() -> None:
    leaf = ErrorMechanism(0.6, frozenset({1}), frozenset({0}))
    zero = RepeatBlock((leaf,), 0, 7, 2)
    inner = RepeatBlock((zero, leaf), 2, -2, 4)
    middle = RepeatBlock((inner,), 2, 3, 5)
    outer = RepeatBlock((middle,), 2, 11, 7)
    model = ErrorModel(set(range(40)), {0, 1}, [outer])
    flat = _flat_model(model)
    assert [m.detectors for m in model.flattened()] == [
        frozenset({17}),
        frozenset({15}),
        frozenset({20}),
        frozenset({18}),
        frozenset({28}),
        frozenset({26}),
        frozenset({31}),
        frozenset({29}),
    ]
    for check in _OPTIMIZED_CHECKS:
        optimized = check(model)
        oracle = check(flat)
        assert (optimized.passed, optimized.severity) == (
            oracle.passed,
            oracle.severity,
        )


def test_repeat_correctability_diagnostic_has_absolute_iteration_witness() -> None:
    model = ErrorModel(
        {0, 1},
        {0, 1},
        [
            RepeatBlock(
                (ErrorMechanism(0.1, frozenset({0}), frozenset({0})),),
                2,
                1,
                0,
            ),
            ErrorMechanism(0.2, frozenset({1}), frozenset({1})),
        ],
    )
    result = assert_failed(check_correctability(model))
    conflict = result.counter_example_data["conflicts"][0]
    assert {w["mechanism"] for w in conflict["witnesses"]} == {
        "error(0.1) D1 L0",
        "error(0.2) D1 L1",
    }
    assert [w["iteration"] for w in conflict["witnesses"]] == [[1], []]
    assert "iteration (1,)" in result.counter_example


def test_all_optimized_checks_use_the_same_flattened_oracle_contract() -> None:
    model = ErrorModel(
        set(range(30)),
        {0, 1},
        [
            RepeatBlock(
                (
                    ErrorMechanism(0.0, frozenset(), frozenset({0})),
                    ErrorMechanism(0.6, frozenset({1}), frozenset({1})),
                ),
                2,
                2,
                5,
            )
        ],
    )
    for check in (
        check_detectability,
        check_probability_bounds,
        check_observable_coverage,
        check_sensitivity,
    ):
        _assert_same_oracle_result(check, model)


def test_nested_template_data_matches_flattened_oracle() -> None:
    inner = RepeatBlock(
        (
            ErrorMechanism(0.1, frozenset(), frozenset({0})),
            ErrorMechanism(float("nan"), frozenset({1}), frozenset()),
            ErrorMechanism(0.6, frozenset({2}), frozenset()),
        ),
        2,
        3,
        4,
    )
    model = ErrorModel(set(range(20)), {0, 1, 2}, [RepeatBlock((inner,), 2, 5, 6)])
    for check in (
        check_detectability,
        check_probability_bounds,
        check_observable_coverage,
        check_sensitivity,
    ):
        _assert_same_oracle_result(check, model)


def test_nested_checks_match_flattened_oracle() -> None:
    inner = RepeatBlock(
        (ErrorMechanism(0.6, frozenset({1}), frozenset({0})),),
        2,
        -1,
        4,
    )
    model = ErrorModel(set(range(20)), {0, 1}, [RepeatBlock((inner,), 2, 3, 5)])
    flat_mechanisms: list[ErrorMechanism | RepeatBlock] = list(model.flattened())
    flat = ErrorModel(
        set(model.detectors),
        set(model.observables),
        flat_mechanisms,
    )
    checks = (
        check_detectability,
        check_probability_bounds,
        check_observable_coverage,
        check_sensitivity,
        check_duplicates,
        check_correctability,
    )
    for check in checks:
        optimized = check(model)
        oracle = check(flat)
        assert (optimized.passed, optimized.severity) == (
            oracle.passed,
            oracle.severity,
        )
    optimized_sensitivity = assert_failed(check_sensitivity(model))
    oracle_sensitivity = assert_failed(check_sensitivity(flat))
    assert (
        optimized_sensitivity.counter_example_data["detectors"]
        == oracle_sensitivity.counter_example_data["detectors"]
    )


def test_real_stim_repeat_dem_matches_flattened_oracle() -> None:
    for distance in (3, 5):
        dem = stim.Circuit.generated(
            "surface_code:rotated_memory_z",
            distance=distance,
            rounds=10,
            after_clifford_depolarization=0.001,
        ).detector_error_model(decompose_errors=True, flatten_loops=False)
        source = emlint.frontends.from_stim_dem(dem)
        assert any(isinstance(item, RepeatBlock) for item in source.error_mechanisms)
        flat_mechanisms: list[ErrorMechanism | RepeatBlock] = list(source.flattened())
        flat = ErrorModel(
            set(source.detectors),
            set(source.observables),
            flat_mechanisms,
            dict(source.detector_coords),
        )
        for check in (
            check_detectability,
            check_probability_bounds,
            check_observable_coverage,
            check_sensitivity,
        ):
            optimized = check(source)
            oracle = check(flat)
            assert (optimized.passed, optimized.severity) == (
                oracle.passed,
                oracle.severity,
            )


def test_sensitivity_preserves_gaps_between_same_residue_intervals() -> None:
    model = ErrorModel(
        set(range(9)),
        set(),
        [
            RepeatBlock((ErrorMechanism(0.1, frozenset({0}), frozenset()),), 2, 2, 0),
            RepeatBlock((ErrorMechanism(0.1, frozenset({0}), frozenset()),), 2, 2, 6),
        ],
    )
    result = assert_failed(check_sensitivity(model))
    assert result.counter_example_data["detectors"] == [1, 3, 4, 5, 7]


@pytest.mark.parametrize(
    ("probability", "severity"),
    [
        (float("nan"), "error"),
        (float("inf"), "error"),
        (float("-inf"), "error"),
        (-0.1, "error"),
        (0.0, "error"),
        (0.6, "warning"),
    ],
)
def test_repeat_probability_matrix_has_dynamic_severity(
    probability: float, severity: str
) -> None:
    model = ErrorModel(
        {4},
        set(),
        [
            RepeatBlock(
                (ErrorMechanism(probability, frozenset({0}), frozenset()),), 3, 1, 4
            )
        ],
    )
    result = assert_failed(check_probability_bounds(model))
    assert result.severity == severity
    assert result.counter_example_data["mechanisms"] == [f"error({probability}) D4"]
    assert "D4" in result.counter_example


def test_repeat_probability_severity_and_absolute_witnesses() -> None:
    model = ErrorModel(
        {5, 6},
        set(),
        [
            RepeatBlock(
                (
                    ErrorMechanism(float("nan"), frozenset({0}), frozenset()),
                    ErrorMechanism(0.9, frozenset({1}), frozenset()),
                ),
                3,
                1,
                5,
            )
        ],
    )
    result = assert_failed(check_probability_bounds(model))
    assert result.severity == "error"
    assert "D5" in result.counter_example
    assert "D6" in result.counter_example
    assert len(result.counter_example_data["mechanisms"]) == 2


def test_repeat_template_truncation_keeps_all_structured_violations() -> None:
    body = tuple(
        ErrorMechanism(0.0, frozenset({index}), frozenset()) for index in range(12)
    )
    model = ErrorModel(set(range(20)), set(), [RepeatBlock(body, 100, 1, 0)])
    result = assert_failed(check_probability_bounds(model))
    assert "and 2 more" in result.counter_example
    assert len(result.counter_example_data["mechanisms"]) == 12


def test_nested_repeat_created_correctability_conflict_has_paths() -> None:
    model = ErrorModel(
        {0, 1},
        {0, 1},
        [
            RepeatBlock(
                (ErrorMechanism(0.1, frozenset({0}), frozenset({0})),),
                2,
                1,
                0,
            ),
            ErrorMechanism(0.2, frozenset({0}), frozenset({1})),
        ],
    )
    result = assert_failed(check_correctability(model))
    assert set(result.counter_example_data) == {
        "conflicts",
        "total_conflicts",
        "witnesses_truncated",
    }
    assert result.counter_example_data["total_conflicts"] == 1
    assert result.counter_example_data["witnesses_truncated"] is False
    conflict = result.counter_example_data["conflicts"][0]
    assert {tuple(w["iteration"]) for w in conflict["witnesses"]} == {(), (0,)}
    assert "iteration (0,)" in result.counter_example
    assert any(w["iteration"] == [] for w in conflict["witnesses"])


def test_repeat_created_duplicate_signature_is_detected() -> None:
    model = ErrorModel(
        {0, 1},
        set(),
        [
            RepeatBlock((ErrorMechanism(0.1, frozenset({0}), frozenset()),), 2, 1, 0),
            ErrorMechanism(0.2, frozenset({1}), frozenset()),
        ],
    )
    result = assert_failed(check_duplicates(model))
    assert "D1" in result.counter_example
    assert len(result.counter_example_data["mechanisms"]) == 2


def test_probability_severity_is_preserved() -> None:
    warning = ErrorModel(
        {0},
        set(),
        [ErrorMechanism(0.6, frozenset({0}), frozenset())],
    )
    error = ErrorModel(
        {0},
        set(),
        [ErrorMechanism(0.0, frozenset({0}), frozenset())],
    )
    assert check_probability_bounds(warning).severity == "warning"
    assert check_probability_bounds(error).severity == "error"


# Hypothesis: property-based tests


@given(
    detectors=st.frozensets(st.integers(0, 8), min_size=1),
    count=st.integers(0, 5),
    stride=st.integers(-3, 3),
)
def test_generated_sensitivity_matches_flattened(detectors, count, stride) -> None:
    body = (ErrorMechanism(0.1, detectors, frozenset()),)
    model = ErrorModel(set(range(20)), set(), [RepeatBlock(body, count, stride, 20)])
    participating = {d for mech in model.flattened() for d in mech.detectors}
    result = check_sensitivity(model)
    dead = set(assert_failed(result).counter_example_data["detectors"])
    assert dead == model.detectors - participating


def test_scope_local_failure_has_absolute_witness() -> None:
    model = ErrorModel(
        {8},
        {0},
        [RepeatBlock((ErrorMechanism(0.1, frozenset(), frozenset({0})),), 1, 2, 8)],
    )
    result = assert_failed(check_detectability(model))
    assert "L0" in result.counter_example
    assert "error(0.1) L0" in result.counter_example_data["mechanisms"]


def test_proxy_is_immutable_and_custom_views_are_independent() -> None:
    source = "repeat 2 {\n error(0.1) D0\n}"
    captured: list[object] = []

    def first_custom(model: ErrorModel) -> PropertyResult:
        captured.append(model)
        model.detectors.clear()
        model.detector_coords.clear()
        return PropertyResult("first", True, "error", "ok")

    def second_custom(model: ErrorModel) -> PropertyResult:
        captured.append(model)
        assert model.detectors == {0}
        return PropertyResult("second", True, "error", "ok")

    report = emlint.check(
        source,
        checks={"first": first_custom, "second": second_custom},
    )
    model = emlint.frontends.from_stim_dem(stim.DetectorErrorModel(source))
    proxy = _ReadOnlyModelView(
        model, tuple(model.error_mechanisms), _FlattenCache(model)
    )
    assert report.num_error_mechanisms == 1
    assert len(captured) == 2
    assert captured[0] is not captured[1]
    for field, value in (
        ("detectors", frozenset()),
        ("observables", frozenset()),
        ("error_mechanisms", ()),
        ("detector_coords", {}),
    ):
        with pytest.raises(AttributeError):
            setattr(proxy, field, value)
    with pytest.raises(AttributeError):
        cast(Any, proxy).detectors.add(1)
    with pytest.raises(TypeError):
        cast(Any, proxy).detector_coords[0] = (0.0,)


def test_no_repeat_dispatch_matches_direct_flat_checks() -> None:
    source = "error(0.1) D0 L0\ndetector D0\n"
    model = emlint.frontends.from_stim_dem(stim.DetectorErrorModel(source))
    direct = {name: fn(model) for name, fn in emlint.ALL_CHECKS.items()}
    report = emlint.check(source)
    for result in report.results:
        expected = direct[result.name]
        assert result == expected


def test_no_repeat_dispatch_matches_each_direct_flat_check() -> None:
    source = """\
error(0.0) D0
error(0.6) D1
error(0.1) L0
detector D0
detector D1
detector D2
"""
    model = emlint.frontends.from_stim_dem(stim.DetectorErrorModel(source))
    for name, fn in emlint.ALL_CHECKS.items():
        expected = fn(model)
        actual = emlint.check(source, checks={name: fn}).results[0]
        assert actual == expected


def test_no_repeat_dispatch_validates_before_flat_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = ErrorModel(set(), set(), [cast(Any, object())])
    monkeypatch.setattr(emlint.frontends, "from_stim_dem", lambda dem: invalid)
    with pytest.raises(TypeError):
        emlint.check("error(0.1) D0", checks={"detectability": check_detectability})


def test_no_repeat_scope_local_fast_path_does_not_construct_flatten_cache(
    monkeypatch,
) -> None:
    def fail_cache(*args, **kwargs):
        raise AssertionError(
            "scope-local no-repeat dispatch should not construct a flatten cache"
        )

    monkeypatch.setattr(emlint, "_FlattenCache", fail_cache)
    report = emlint.check(
        "error(0.1) D0 L0\ndetector D0\n",
        checks={"detectability": emlint.ALL_CHECKS["detectability"]},
    )
    assert all(result.passed for result in report.results)


def test_no_repeat_cross_scope_checks_use_one_unchecked_flatten(monkeypatch) -> None:
    calls = 0
    original = ErrorModel.flattened

    def counted(self: ErrorModel):
        nonlocal calls
        calls += 1
        return original(self)

    monkeypatch.setattr(ErrorModel, "flattened", counted)
    emlint.check("error(0.1) D0 L0\ndetector D0\n")
    assert calls == 0


def test_dispatcher_uses_one_flatten_and_isolates_custom_checks() -> None:
    source = "repeat 3 {\n error(0.1) D0\n}"
    calls = 0
    original = ErrorModel.flattened

    def counted(self: ErrorModel):
        nonlocal calls
        calls += 1
        return original(self)

    setattr(ErrorModel, "flattened", counted)
    seen: list[object] = []

    def custom(model: ErrorModel) -> PropertyResult:
        seen.append(model)
        model.detectors.clear()
        return PropertyResult("custom", True, "error", "ok")

    try:
        report = emlint.check(
            source,
            checks={"duplicates": emlint.ALL_CHECKS["duplicates"], "custom": custom},
        )
    finally:
        setattr(ErrorModel, "flattened", original)
    assert calls == 0
    assert report.num_error_mechanisms == 1
    assert len(seen) == 1
    assert isinstance(seen[0], ErrorModel)


def test_dispatcher_flatten_counts_by_check_subset() -> None:
    source = "repeat 3 {\n error(0.1) D0\n}"
    original = ErrorModel.flattened
    calls = 0

    def counted(self: ErrorModel):
        nonlocal calls
        calls += 1
        return original(self)

    setattr(ErrorModel, "flattened", counted)
    try:
        for checks in (
            {"detectability": emlint.ALL_CHECKS["detectability"]},
            {"duplicates": emlint.ALL_CHECKS["duplicates"]},
            emlint.ALL_CHECKS,
        ):
            before = calls
            emlint.check(source, checks=checks)
            # Small repeat models use the bounded flat path without
            # re-entering the validating flattened() wrapper.
            assert calls - before == 0
    finally:
        setattr(ErrorModel, "flattened", original)


def test_large_repeat_model_keeps_scope_local_checks_symbolic() -> None:
    source = "repeat 2001 {\n error(0.1) D0\n}"
    original = ErrorModel.flattened
    calls = 0

    def counted(self: ErrorModel):
        nonlocal calls
        calls += 1
        return original(self)

    setattr(ErrorModel, "flattened", counted)
    try:
        emlint.check(
            source,
            checks={"detectability": emlint.ALL_CHECKS["detectability"]},
        )
    finally:
        setattr(ErrorModel, "flattened", original)
    assert calls == 0


def test_missing_registry_entry_does_not_break_other_builtin_routing() -> None:
    original = emlint.ALL_CHECKS.pop("duplicates")
    try:
        report = emlint.check(
            "error(0.1) D0",
            checks={"detectability": emlint.ALL_CHECKS["detectability"]},
        )
        assert report.results[0].passed
    finally:
        emlint.ALL_CHECKS["duplicates"] = original


def test_wrapped_builtin_is_not_optimized():
    wrapped = partial(check_sensitivity)
    report = emlint.check(
        "repeat 2 {\n error(0.1) D0\n}", checks={"sensitivity": wrapped}
    )
    assert report.results[0].name == "sensitivity"


def test_unsupported_cross_scope_shape_uses_exact_flatten_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = ErrorModel(
        {0, 1},
        set(),
        [
            RepeatBlock((ErrorMechanism(0.1, frozenset({0}), frozenset()),), 1, 1, 0),
            RepeatBlock((ErrorMechanism(0.1, frozenset({1}), frozenset()),), 1, 1, 0),
        ],
    )
    calls = 0
    original = model.iter_flattened

    def counted():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(model, "iter_flattened", counted)
    checks_module.check_duplicates(model)
    assert calls == 1
