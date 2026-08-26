"""Tests for applicability, profile, and check-customization contracts.

Context metadata turns missing-context situations into explicit skipped results; profiles select
checks and demand context without altering the 0/1/2 exit-code contract.
"""

from __future__ import annotations

import pytest

import emlint
from emlint.profiles import (
    PROFILES,
    applicability_skip_reason,
    validate_severity_override,
)

# ---------------------------------------------------------------------------
# Passing cases (verdicts unaffected by opt-in applicability)
# ---------------------------------------------------------------------------


def test_no_context_runs_everything_as_before():
    """Default invocation: no context declared, no skips, full battery."""
    report = emlint.check("error(0.1) L0")
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "verdict"
    assert not detectability.passed  # the error verdict still fires


def test_complete_context_produces_verdicts():
    report = emlint.check(
        "error(0.1) L0",
        context={"circuit_role": "memory", "complete_syndrome": True},
    )
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "verdict"
    assert not detectability.passed


def test_profile_restricts_battery_to_enabled_checks():
    report = emlint.check("error(0.1) D0 L0\ndetector D0", profile="strict-dem")
    ran = {r.name for r in report.results}
    assert ran <= set(PROFILES["strict-dem"].enabled_checks)
    # strict-dem demands circuit_role/complete_syndrome for detectability;
    # without declared context it must appear as an explicit inconclusive
    # result (exit 2), never a silent skip that could mask an error-severity
    # failure behind exit 0.
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "inconclusive"
    assert not detectability.passed
    assert all(
        r.status == "verdict" for r in report.results if r.name != "detectability"
    )


def test_unknown_profile_raises_value_error():
    with pytest.raises(ValueError, match="Unknown profile"):
        emlint.check("error(0.1) D0", profile="no-such-profile")


# ---------------------------------------------------------------------------
# Failing cases (explicit skipped results, never silent omissions)
# ---------------------------------------------------------------------------


def test_post_selected_state_preparation_skips_detectability():
    """The QECirc-470 case: post-selected role without complete_syndrome must
    produce an explicit non-verdict result, never a pass or misleading
    failure. detectability is error-severity, so the status is inconclusive
    (exit 2), not a plain skip."""
    report = emlint.check(
        "error(0.1) L0",
        context={"circuit_role": "post_selected_verification"},
    )
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "inconclusive"
    assert not detectability.passed
    assert "applicability" in detectability.message


def test_missing_required_context_yields_inconclusive_for_error_check():
    report = emlint.check("error(0.1) L0", context={"circuit_role": "memory"})
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "inconclusive"
    assert not detectability.passed
    assert "complete_syndrome" in detectability.message


def test_partial_context_declaration_makes_requirements_explicit():
    """Declaring *any* context opts the run into applicability enforcement."""
    report = emlint.check("error(0.1) L0", context={"noise_convention": "independent"})
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "inconclusive"


def test_state_preparation_with_explicit_syndrome_claim_gets_verdict():
    """An explicit complete_syndrome=true claim re-enables the invariant."""
    report = emlint.check(
        "error(0.1) L0",
        context={
            "circuit_role": "state_preparation",
            "complete_syndrome": True,
        },
    )
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "verdict"
    assert not detectability.passed


def test_skipped_results_do_not_trigger_exit_code_2():
    """Skipped/inconclusive statuses are visible but exit-code neutral."""
    from emlint.report import Report

    from emlint.report import PropertyResult

    report = Report(
        results=[
            PropertyResult(
                name="detectability",
                passed=True,
                severity="error",
                message="skipped: missing required context: complete_syndrome",
                status="skipped",
            )
        ],
        num_detectors=0,
        num_observables=0,
        num_error_mechanisms=0,
    )
    assert not report.has_errors()
    assert not report.has_warnings()
    assert report.all_passed()


def test_heuristic_check_cannot_be_upgraded_to_error():
    with pytest.raises(ValueError, match="heuristic"):
        validate_severity_override("duplicates", "error")


def test_deterministic_check_can_be_upgraded_to_error():
    validate_severity_override("observable_coverage", "error")  # no raise


def test_invalid_override_severity_rejected():
    with pytest.raises(ValueError, match="invalid override severity"):
        validate_severity_override("duplicates", "info")


def test_applicability_skip_reason_direct():
    reason = applicability_skip_reason(
        "detectability", {"circuit_role": "encoding"}, None
    )
    assert reason is not None and "complete_syndrome" in reason
    assert applicability_skip_reason("sensitivity", {}, None) is None


# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------

from hypothesis import given  # noqa: E402
import hypothesis.strategies as st  # noqa: E402

_ROLES = st.sampled_from(
    [
        "memory",
        "syndrome_extraction",
        "encoding",
        "state_preparation",
        "post_selected_verification",
        "lattice_operation",
        "unknown",
    ]
)


@given(role=_ROLES, complete=st.booleans() | st.none())
def test_detectability_verdict_or_skip_never_silent_pass(role, complete):
    """For every context combination, detectability either runs or reports an
    explicit skip — a silent verdict outside its domain is forbidden."""
    context: dict[str, bool | str] = {"circuit_role": role}
    if complete is not None:
        context["complete_syndrome"] = complete
    report = emlint.check("error(0.1) L0", context=context)
    detectability = next(r for r in report.results if r.name == "detectability")
    unsupported = {"state_preparation", "post_selected_verification"}
    if role in unsupported and complete is not True:
        assert detectability.status == "inconclusive"
    elif complete is None:
        # circuit_role declared but complete_syndrome missing → inconclusive
        # (error-severity check without its required context).
        assert detectability.status == "inconclusive"
    else:
        assert detectability.status == "verdict"


@given(
    extra=st.dictionaries(
        st.sampled_from(["decoder", "noise_convention"]),
        st.sampled_from(["mwpm", "correlated", "independent", "adversarial"]),
    )
)
def test_non_role_context_still_enforces_syndrome_requirement(extra):
    """Any non-empty declared context opts into applicability enforcement."""
    context: dict[str, bool | str] = dict(extra)
    report = emlint.check("error(0.1) L0", context=context)
    detectability = next(r for r in report.results if r.name == "detectability")
    if not context or "complete_syndrome" not in context:
        # Empty context = default invocation (no enforcement); any non-empty
        # declaration without complete_syndrome yields an inconclusive result
        # (detectability is error-severity).
        expected = "verdict" if not context else "inconclusive"
        assert detectability.status == expected
    else:
        assert detectability.status == "verdict"
