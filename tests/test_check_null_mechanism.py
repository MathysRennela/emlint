"""Tests for check_null_mechanism.

check_null_mechanism flags error mechanisms whose detector support *and*
observable support are both empty. Such a mechanism cannot appear in the
syndrome sigma = H * e nor in the observable flip ell = L * e for any error
vector e, so it is a provable no-op that no decoder can observe.

Property: no mechanism m satisfies det(m) = ∅ and obs(m) = ∅
"""

from __future__ import annotations

import pytest
from hypothesis import given
import hypothesis.strategies as st

from emlint.model import ErrorModel, RepeatBlock
from emlint.checks import _MAX_SHOWN, check_null_mechanism
from helpers import _mech, _model, assert_failed

# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


def test_empty_model_passes():
    result = check_null_mechanism(_model())
    assert result.passed
    assert result.name == "null_mechanism"
    assert result.severity == "warning"
    assert result.counter_example is None


def test_detector_only_mechanism_passes():
    """Detector support alone is enough: the binding boundary is empty on BOTH sides."""
    result = check_null_mechanism(_model(_mech(0.1, detectors=frozenset({0}))))
    assert result.passed


def test_observable_only_mechanism_passes():
    result = check_null_mechanism(_model(_mech(0.1, observables=frozenset({0}))))
    assert result.passed


def test_even_detector_weight_passes():
    """A weight-2 detector mechanism is NOT a no-op; it must not be flagged.

    This pins the binding severity boundary from DEFERRED_CHECKS.md: the
    predicate is empty support on both sides, never even detector weight.
    Generalizing to even-weight mechanisms would false-fail correct DEMs.
    """
    result = check_null_mechanism(_model(_mech(0.1, detectors=frozenset({0, 1}))))
    assert result.passed


def test_even_weight_with_observables_passes():
    result = check_null_mechanism(
        _model(_mech(0.1, detectors=frozenset({0, 1}), observables=frozenset({0})))
    )
    assert result.passed


def test_real_surface_code_dem_passes():
    """A genuine DEM carries no null mechanisms."""
    import emlint
    import stim

    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z", distance=3, rounds=3
    )
    report = emlint.check(
        circuit.detector_error_model(decompose_errors=False),
        {"null_mechanism": check_null_mechanism},
    )
    assert report.all_passed()


def test_real_surface_code_dem_passes_d5():
    """Stim integration at d=5: a genuine DEM carries no null mechanisms."""
    import emlint
    import stim

    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z", distance=5, rounds=5
    )
    report = emlint.check(
        circuit.detector_error_model(decompose_errors=False),
        {"null_mechanism": check_null_mechanism},
    )
    assert report.all_passed()


# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------


def test_null_mechanism_fails():
    model = _model(_mech(0.25), _mech(0.1, detectors=frozenset({0})))
    result = check_null_mechanism(model)
    assert not result.passed
    assert result.severity == "warning"
    assert result.counter_example is not None
    assert "0.25" in result.counter_example


def test_multiple_null_mechanisms_fail():
    model = _model(_mech(0.25), _mech(0.5), _mech(0.1, detectors=frozenset({0})))
    result = assert_failed(check_null_mechanism(model))
    assert "0.25" in result.counter_example
    assert "0.5" in result.counter_example


def test_counter_example_data_lists_mechanisms():
    model = _model(_mech(0.25))
    result = assert_failed(check_null_mechanism(model))
    assert result.counter_example_data["mechanisms"] == ["error(0.25)"]


@pytest.mark.parametrize("p", [0.25, 0.1, 0.07, 1 / 3, 0.4999999])
def test_counter_example_data_conforms_to_documented_entry_form(p: float):
    """``mechanisms`` entries must be instruction strings of the form
    ``error(p) D<i>… L<j>…`` (docs/checks.md, "Machine-readable output
    contract (stable)"). A null mechanism has no targets, so the entry is the
    bare instruction — never a decorated variant that is not a DEM line.

    Conformance is parse-validity, not string equality with stim's canonical
    rendering: stim prints probabilities at 17 significant digits while
    ``_format_mech`` prints the shortest repr, so ``error(0.1)`` canonicalises
    to ``error(0.1000000000000000056)`` while parsing to the identical DEM.
    """
    import stim

    model = _model(_mech(p))
    result = assert_failed(check_null_mechanism(model))
    for entry in result.counter_example_data["mechanisms"]:
        # Must parse back as exactly one DEM instruction, and must be the bare
        # error(p) line the contract documents.
        parsed = stim.DetectorErrorModel(f"{entry}\n")
        assert len(parsed) == 1
        assert entry.startswith("error(")
        assert " D" not in entry and " L" not in entry


def test_counter_example_names_no_targets():
    """The witness must show the mechanism carries no D or L targets."""
    model = _model(_mech(0.125))
    result = assert_failed(check_null_mechanism(model))
    assert result.counter_example == "error(0.125)"
    assert "D" not in result.counter_example
    assert "L" not in result.counter_example


def test_truncation_reports_overflow():
    n = _MAX_SHOWN + 2
    model = _model(*[_mech(0.01 * (i + 1)) for i in range(n)])
    result = assert_failed(check_null_mechanism(model))
    assert f"and {n - _MAX_SHOWN} more" in result.counter_example
    # Only the human-readable witness is capped: the machine-readable list is
    # complete, matching the schema siblings (detectability, probability_bounds)
    # and docs/checks.md "Machine-readable output contract (stable)".
    assert len(result.counter_example_data["mechanisms"]) == n
    assert result.counter_example_data["instance_count"] == n


def test_truncation_boundary_exactly_max_shown_has_no_overflow():
    model = _model(*[_mech(0.01 * (i + 1)) for i in range(_MAX_SHOWN)])
    result = assert_failed(check_null_mechanism(model))
    assert "more" not in result.counter_example


def test_null_mechanism_inside_repeat_block_is_found():
    """Vacancy inside a REPEAT body must surface through the template path."""
    model = ErrorModel(
        detectors={0},
        observables=set(),
        error_mechanisms=[
            RepeatBlock(
                count=2,
                body=(_mech(0.1, detectors=frozenset({0})), _mech(0.2)),
            )
        ],
    )
    result = assert_failed(check_null_mechanism(model))
    assert "0.2" in result.counter_example


def test_repeat_block_reports_instance_count_not_expanded_list():
    """A repeat body violation is one template standing for N instances.

    The diagnostic follows the repeat-aware family: the witness names the
    template, and ``instance_count`` carries the multiplicity, rather than the
    report expanding every iteration of the repeat body.
    """
    model = ErrorModel(
        detectors=set(),
        observables=set(),
        error_mechanisms=[
            RepeatBlock(count=5, body=(_mech(0.2),)),
        ],
    )
    result = assert_failed(check_null_mechanism(model))
    assert result.counter_example_data["mechanisms"] == ["error(0.2)"]
    assert result.counter_example_data["instance_count"] == 5
    assert "5 null error mechanism instance(s)" in result.message
    assert "1 distinct location(s)" in result.message


def test_nested_repeat_instance_count_is_axis_product():
    """Nested repeats multiply: the instance count is the product of the axes."""
    model = ErrorModel(
        detectors=set(),
        observables=set(),
        error_mechanisms=[
            RepeatBlock(
                count=3,
                body=(RepeatBlock(count=2, body=(_mech(0.2),)),),
            )
        ],
    )
    result = assert_failed(check_null_mechanism(model))
    assert result.counter_example_data["instance_count"] == 6


def test_repeat_path_does_not_expand_the_repeat_body():
    """The check is template-local: a large repeat body is never materialised.

    ``null_mechanism`` is registered as a scope-local check, so evaluating it
    alone on a repeated DEM must not expand the repeat body — the predicate is
    shift-invariant, so the template answer is exact.
    """
    import emlint

    model = ErrorModel(
        detectors=set(),
        observables=set(),
        error_mechanisms=[RepeatBlock(count=100_000, body=(_mech(0.2),))],
    )
    result = assert_failed(check_null_mechanism(model))
    assert result.counter_example_data["instance_count"] == 100_000

    report = emlint.check(
        "repeat 100000 {\n error(0.2)\n}",
        checks={"null_mechanism": check_null_mechanism},
    )
    null_result = assert_failed(
        next(r for r in report.results if r.name == "null_mechanism")
    )
    assert null_result.counter_example_data["instance_count"] == 100_000


def test_reachable_from_stim_parser():
    """The gap is reachable: stim's parser preserves a hand-written targetless error."""
    import emlint
    import stim

    dem = stim.DetectorErrorModel("error(0.125) D0\nerror(0.25)\n")
    report = emlint.check(dem, {"null_mechanism": check_null_mechanism})
    assert not report.all_passed()
    result = next(r for r in report.results if r.name == "null_mechanism")
    assert result.counter_example is not None
    assert "0.25" in result.counter_example


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------


@given(
    dets=st.frozensets(st.integers(0, 10), min_size=1),
    obs=st.frozensets(st.integers(0, 5)),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_nonempty_support_never_flagged(dets, obs, p):
    """Any mechanism with support on at least one side must pass."""
    assert check_null_mechanism(_model(_mech(p, dets, obs))).passed


@given(p=st.floats(min_value=1e-4, max_value=0.5))
def test_empty_support_always_flagged(p):
    """Empty support on both sides is the exact predicate, for any probability."""
    result = check_null_mechanism(_model(_mech(p)))
    assert not result.passed
    assert result.status == "verdict"


@given(
    p_null=st.floats(min_value=1e-4, max_value=0.5),
    dets=st.frozensets(st.integers(0, 10), min_size=1),
    p_live=st.floats(min_value=1e-4, max_value=0.5),
)
def test_only_null_mechanisms_are_reported(p_null, dets, p_live):
    """A live mechanism never appears among the reported witnesses."""
    result = assert_failed(
        check_null_mechanism(_model(_mech(p_null), _mech(p_live, dets)))
    )
    assert len(result.counter_example_data["mechanisms"]) == 1
