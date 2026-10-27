from __future__ import annotations

import inspect
from typing import Callable

import pytest

import emlint
from emlint import _ReadOnlyModelView
from emlint.checks import ALL_CHECKS
from emlint.model import ErrorMechanism, ErrorModel
from emlint.report import PropertyResult
from helpers import _mech, _model


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_has_matching_result_name(
    name: str, check_fn: Callable
) -> None:
    result = check_fn(ErrorModel(set(), set(), []))
    assert result.name == name


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_satisfies_result_contract(
    name: str, check_fn: Callable
) -> None:
    result = check_fn(ErrorModel(set(), set(), []))
    assert result.severity in {"error", "warning"}
    if result.status != "verdict":
        # A skip is exit-neutral and explains itself in `message`; the
        # counter-example contract applies to failing verdicts only.
        return
    if result.passed:
        assert result.counter_example is None
        assert result.counter_example_data is None
    else:
        assert result.counter_example is not None
        assert result.counter_example_data is not None


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_reports_counterexamples_on_failure(
    name: str, check_fn: Callable
) -> None:
    """Every production check has a minimal model that violates its property."""
    from emlint.model import ErrorMechanism

    cases = {
        "detectability": ErrorModel(
            set(), {0}, [ErrorMechanism(0.1, frozenset(), frozenset({0}))]
        ),
        "sensitivity": ErrorModel(
            {0}, set(), [ErrorMechanism(0.1, frozenset(), frozenset({1}))]
        ),
        "observable_coverage": ErrorModel(
            set(), {0}, [ErrorMechanism(0.1, frozenset({1}), frozenset())]
        ),
        "probability_bounds": ErrorModel(
            set(), set(), [ErrorMechanism(0.0, frozenset(), frozenset())]
        ),
        "duplicates": ErrorModel(
            set(),
            set(),
            [
                ErrorMechanism(0.1, frozenset(), frozenset()),
                ErrorMechanism(0.2, frozenset(), frozenset()),
            ],
        ),
        "correctability": ErrorModel(
            {0},
            {0, 1},
            [
                ErrorMechanism(0.1, frozenset({0}), frozenset({0})),
                ErrorMechanism(0.1, frozenset({0}), frozenset({1})),
            ],
        ),
        "null_mechanism": ErrorModel(
            set(),
            set(),
            [ErrorMechanism(0.1, frozenset(), frozenset())],
        ),
<<<<<<< HEAD
=======
        "high_probability_mechanisms": ErrorModel(
            set(),
            set(),
            [ErrorMechanism(0.4, frozenset({0}), frozenset())],
        ),
        "connectivity": ErrorModel(
            {0, 1},
            {0},
            [
                ErrorMechanism(0.1, frozenset({0}), frozenset()),
                ErrorMechanism(0.1, frozenset({1}), frozenset({0})),
            ],
        ),
        "boundary_symmetry": ErrorModel(
            {0},
            {0, 1},
            [
                ErrorMechanism(0.1, frozenset(), frozenset({0})),
                ErrorMechanism(0.1, frozenset({0}), frozenset()),
                ErrorMechanism(0.1, frozenset({0}), frozenset({1})),
            ],
        ),
>>>>>>> 5972866 (Release v0.2.4)
    }
    result = check_fn(cases[name])
    assert not result.passed
    assert result.counter_example is not None
    assert result.counter_example_data is not None


_HINT_CHECKS = ("detectability", "sensitivity", "duplicates", "correctability")


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_registered_check_hint_contract(name: str, check_fn: Callable) -> None:
    """The v0.2.2 output contract: hint-carrying checks populate a hypothesis-
    phrased hint on failure; every passing result has hint None."""
    from emlint.model import ErrorMechanism

    cases = {
        "detectability": ErrorModel(
            set(), {0}, [ErrorMechanism(0.1, frozenset(), frozenset({0}))]
        ),
        "sensitivity": ErrorModel(
            {0}, set(), [ErrorMechanism(0.1, frozenset(), frozenset({1}))]
        ),
        "observable_coverage": ErrorModel(
            set(), {0}, [ErrorMechanism(0.1, frozenset({1}), frozenset())]
        ),
        "probability_bounds": ErrorModel(
            set(), set(), [ErrorMechanism(0.0, frozenset(), frozenset())]
        ),
        "duplicates": ErrorModel(
            set(),
            set(),
            [
                ErrorMechanism(0.1, frozenset(), frozenset()),
                ErrorMechanism(0.2, frozenset(), frozenset()),
            ],
        ),
        "correctability": ErrorModel(
            {0},
            {0, 1},
            [
                ErrorMechanism(0.1, frozenset({0}), frozenset({0})),
                ErrorMechanism(0.1, frozenset({0}), frozenset({1})),
            ],
        ),
        "null_mechanism": ErrorModel(
            set(),
            set(),
            [ErrorMechanism(0.1, frozenset(), frozenset())],
        ),
<<<<<<< HEAD
=======
        "high_probability_mechanisms": ErrorModel(
            set(),
            set(),
            [ErrorMechanism(0.4, frozenset({0}), frozenset())],
        ),
        "connectivity": ErrorModel(
            {0, 1},
            {0},
            [
                ErrorMechanism(0.1, frozenset({0}), frozenset()),
                ErrorMechanism(0.1, frozenset({1}), frozenset({0})),
            ],
        ),
        "boundary_symmetry": ErrorModel(
            {0},
            {0, 1},
            [
                ErrorMechanism(0.1, frozenset(), frozenset({0})),
                ErrorMechanism(0.1, frozenset({0}), frozenset()),
                ErrorMechanism(0.1, frozenset({0}), frozenset({1})),
            ],
        ),
>>>>>>> 5972866 (Release v0.2.4)
    }
    result = check_fn(cases[name])
    assert not result.passed
    if name in _HINT_CHECKS:
        assert result.hint is not None
        assert result.hint.startswith("Hypothesis")
    else:
        assert result.hint is None


@pytest.mark.parametrize("name, check_fn", ALL_CHECKS.items())
def test_passing_result_has_no_hint(name: str, check_fn: Callable) -> None:
    result = check_fn(ErrorModel(set(), set(), []))
    if result.passed:
        assert result.hint is None


@pytest.mark.parametrize("check_fn", ALL_CHECKS.values())
def test_validate_check_signature(check_fn: Callable) -> None:
    sig = inspect.signature(check_fn)
    params = list(sig.parameters.values())
    assert params[0].name == "model"
    assert len(params) == 2
<<<<<<< HEAD
    assert params[1].name == "max_shown"
=======
    assert params[1].name in {
        "max_shown",
        "threshold",
        "single_decoding_graph",
        "max_imbalance",
    }
>>>>>>> 5972866 (Release v0.2.4)


# ---------------------------------------------------------------------------
# Dispatcher: read-only view internals
# ---------------------------------------------------------------------------


PASSING_DEM = "error(0.1) D0 L0\ndetector D0\ndetector D0\n"


def test_read_only_view_setattr_fallback_for_internal_fields():
    """Setting an internal (non-read-only) field on the view must succeed via
    the object.__setattr__ fallback (catches the uncovered fallback path)."""
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[ErrorMechanism(0.1, frozenset({0}), frozenset())],
    )
    view = _ReadOnlyModelView(
        model, tuple(model.error_mechanisms), None, validated=True
    )
    view._validated = False  # internal field, not in _READ_ONLY_FIELDS
    assert view._validated is False


def test_read_only_view_rejects_writes_to_public_fields():
    """Writing to a public field on the read-only view must raise."""
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[ErrorMechanism(0.1, frozenset({0}), frozenset())],
    )
    view = _ReadOnlyModelView(
        model, tuple(model.error_mechanisms), None, validated=True
    )
    with pytest.raises(AttributeError, match="read-only"):
        view.detectors = frozenset({1})


def test_read_only_view_validates_tree_when_not_prevalidated():
    """A view constructed with validated=False must validate on first use."""
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[ErrorMechanism(0.1, frozenset({0}), frozenset())],
    )
    view = _ReadOnlyModelView(
        model, tuple(model.error_mechanisms), None, validated=False
    )
    view._validate_tree()  # must not raise
    assert view._validated is True


def test_read_only_view_flattened_without_cache_returns_mechanisms():
    """flattened() with no cache returns the stored mechanisms directly."""
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[ErrorMechanism(0.1, frozenset({0}), frozenset())],
    )
    view = _ReadOnlyModelView(
        model, tuple(model.error_mechanisms), None, validated=True
    )
    flat = view.flattened()
    assert len(flat) == 1
    assert flat[0].detectors == frozenset({0})


def test_all_checks_on_singleton_mechanism_no_detectors_no_observables():
    """A mechanism with no detectors and no observables is degenerate but must
    not crash any check."""
    model = _model(_mech(0.1))
    for name, fn in ALL_CHECKS.items():
        result = fn(model)
        assert result.name == name


def test_custom_check_receives_defensive_copy_on_flat_model():
    """A custom (non-builtin) check on a flat model must receive a defensive
    copy, not the shared dispatcher state (catches the uncovered defensive path)."""

    def custom(model):
        # Mutating the model must not corrupt dispatcher state.
        model.error_mechanisms.clear()
        return PropertyResult(
            name="custom", passed=True, severity="warning", message="ok"
        )

    report = emlint.check(
        PASSING_DEM,
        checks={"custom": custom, "detectability": ALL_CHECKS["detectability"]},
    )
    names = {r.name for r in report.results}
    assert "custom" in names
    assert "detectability" in names
