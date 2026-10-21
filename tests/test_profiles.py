"""Tests for applicability, profile, and check-customization contracts.

Context metadata turns missing-context situations into explicit skipped results; profiles select
checks and demand context without altering the 0/1/2 exit-code contract.
"""

from __future__ import annotations

import pytest

import emlint
from emlint.checks import ALL_CHECKS
from emlint.profiles import (
    PROFILES,
    Profile,
    applicability_skip,
    applicability_skip_reason,
    parse_context_value,
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


def test_report_is_stamped_with_profile():
    """A PASS certificate is valid only relative to a declared context; the
    producing profile must be stamped onto the report (certifier contract)."""
    report = emlint.check("error(0.1) D0 L0\ndetector D0", profile="strict-dem")
    assert report.profile == "strict-dem"


def test_report_profile_is_none_without_profile():
    report = emlint.check("error(0.1) D0 L0\ndetector D0")
    assert report.profile is None


# ---------------------------------------------------------------------------
# Failing cases (explicit skipped results, never silent omissions)
# ---------------------------------------------------------------------------


def test_post_selected_state_preparation_skips_detectability():
    """The QECirc-470 case: post-selected role without complete_syndrome must
    produce an explicit non-verdict result, never a pass or misleading
    failure. A declared unsupported role is an affirmative user declaration,
    so the status is a plain exit-neutral skip."""
    report = emlint.check(
        "error(0.1) L0",
        context={"circuit_role": "post_selected_verification"},
    )
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "skipped"
    assert not detectability.passed
    assert "applicability" in detectability.message
    assert not report.has_errors()
    assert not report.has_warnings()


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
    """Plain skips of heuristic checks are exit-code neutral: visible on the
    report, but no error/warning contribution. (Inconclusive deterministic
    checks DO drive exit 2 — see test_profile_restricts_battery... above.)
    Exercises the real dispatcher path via emlint.check()."""
    from emlint.checks import ALL_CHECKS

    report = emlint.check(
        "error(0.1) D0 L0\ndetector D0",
        checks={
            "duplicates": ALL_CHECKS["duplicates"],
            "sensitivity": ALL_CHECKS["sensitivity"],
        },
        profile="graphlike-decoder",
    )
    # graphlike-decoder demands decoder context for every check; both selected
    # checks are heuristic, so both surface as plain skips.
    assert {r.name for r in report.results} == {"duplicates", "sensitivity"}
    assert all(r.status == "skipped" for r in report.results)
    assert not report.has_errors()
    assert not report.has_warnings()
    assert report.all_passed()


def test_inconclusive_deterministic_check_triggers_exit_2():
    """An error-severity check without its required context is inconclusive
    and must surface as exit 2 (has_warnings), never a silent exit 0."""
    report = emlint.check("error(0.1) D0 L0\ndetector D0", profile="strict-dem")
    detectability = next(r for r in report.results if r.name == "detectability")
    assert detectability.status == "inconclusive"
    assert detectability.severity == "error"
    assert not report.has_errors()
    assert report.has_warnings()


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


def test_applicability_skip_status_splits_the_two_skip_sources():
    role_skip = applicability_skip(
        "detectability", {"circuit_role": "state_preparation"}, None
    )
    assert role_skip is not None
    reason, status = role_skip
    assert status == "skipped"
    assert "applicability domain" in reason
    missing_skip = applicability_skip(
        "detectability", {"circuit_role": "encoding"}, None
    )
    assert missing_skip is not None
    reason, status = missing_skip
    assert status == "inconclusive"
    assert "complete_syndrome" in reason
    assert (
        applicability_skip(
            "detectability",
            {"circuit_role": "memory", "complete_syndrome": True},
            None,
        )
        is None
    )


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
        # Declared unsupported role → plain exit-neutral skip.
        assert detectability.status == "skipped"
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


# ---------------------------------------------------------------------------
# Severity overrides: profile-declared, gated by the downgrade opt-in
# ---------------------------------------------------------------------------


PASSING_DEM = "error(0.1) D0 L0\ndetector D0\n"


def _profile_with_override() -> Profile:
    return Profile(
        name="audit-override",
        description="test profile with a severity override",
        enabled_checks=("observable_coverage", "detectability"),
        severity_overrides=(("observable_coverage", "warning"),),
    )


def test_profile_severity_override_downgrade_applied(monkeypatch):
    """A profile-declared downgrade override must apply to the verdict when
    allow_severity_downgrade is passed (catches the uncovered override path)."""
    monkeypatch.setitem(PROFILES, "audit-override", _profile_with_override())
    report = emlint.check(
        "detector D0\nerror(0.1) D0 L1\n",  # L1 never flipped -> observable_coverage fails
        profile="audit-override",
        allow_severity_downgrade=True,
    )
    cov = next(r for r in report.results if r.name == "observable_coverage")
    assert not cov.passed
    assert cov.severity == "warning"  # downgraded from error
    assert report.applied_overrides == {"observable_coverage": "error"}


def test_profile_severity_override_downgrade_rejected_without_optin(monkeypatch):
    """A profile downgrade without allow_severity_downgrade must raise."""
    monkeypatch.setitem(PROFILES, "audit-override", _profile_with_override())
    with pytest.raises(ValueError, match="downgrad"):
        emlint.check(
            "detector D0\nerror(0.1) D0 L1\n",
            profile="audit-override",
        )


def test_profile_severity_override_upgrade_applied(monkeypatch):
    """A profile upgrade of a deterministic check to error must apply."""
    prof = Profile(
        name="audit-upgrade",
        description="test profile with an upgrade override",
        enabled_checks=("observable_coverage",),
        severity_overrides=(("observable_coverage", "error"),),
    )
    monkeypatch.setitem(PROFILES, "audit-upgrade", prof)
    report = emlint.check(
        "detector D0\nerror(0.1) D0 L1\n",
        profile="audit-upgrade",
    )
    cov = next(r for r in report.results if r.name == "observable_coverage")
    assert cov.severity == "error"


def test_checks_outside_profile_raise(monkeypatch):
    """Passing an explicit check selection outside the profile's enabled set
    must raise (catches the uncovered dispatcher guard)."""
    # All built-in profiles enable every check, so use a custom one.
    monkeypatch.setitem(
        PROFILES,
        "audit-narrow",
        Profile(
            name="audit-narrow",
            description="only detectability",
            enabled_checks=("detectability",),
        ),
    )
    with pytest.raises(ValueError, match="outside profile"):
        emlint.check(
            PASSING_DEM,
            checks={"sensitivity": ALL_CHECKS["sensitivity"]},
            profile="audit-narrow",
        )


# ---------------------------------------------------------------------------
# parse_context_value and validate_severity_override units
# ---------------------------------------------------------------------------


def test_parse_context_value_booleans_and_strings():
    """parse_context_value maps true/false to bool, everything else to str."""
    assert parse_context_value("true") is True
    assert parse_context_value("TRUE") is True
    assert parse_context_value("false") is False
    assert parse_context_value("False") is False
    assert parse_context_value("memory") == "memory"
    assert parse_context_value("0") == "0"


def test_validate_severity_override_downgrade_rejected():
    """A downgrade without allow_downgrade must raise (catches the uncovered
    rejection path)."""
    with pytest.raises(ValueError, match="downgrad"):
        validate_severity_override("observable_coverage", "warning")


def test_validate_severity_override_downgrade_allowed():
    """A downgrade with allow_downgrade=True must pass."""
    validate_severity_override("observable_coverage", "warning", allow_downgrade=True)
