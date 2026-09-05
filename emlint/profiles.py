"""Profile and applicability contracts.

Profiles select checks and demand context; applicability metadata turns
missing-context situations into explicit ``skipped`` results instead of silent
passes. Profiles never alter the 0/1/2 exit-code contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# Checks whose invariant is deterministic; these alone may be upgraded to
# "error" by a severity override (heuristic checks cannot). These are also the
# error-severity checks: if one is skipped for missing context, it must surface
# as inconclusive (exit 2), never a silent skip.
_DETERMINISTIC_CHECKS = frozenset(
    {"detectability", "observable_coverage", "probability_bounds"}
)

# Circuit roles under which a check's verdict is meaningless. A run declaring
# such a role gets an explicit skipped result, never a pass/fail.
_UNSUPPORTED_ROLES: dict[str, frozenset[str]] = {
    "detectability": frozenset({"state_preparation", "post_selected_verification"}),
}

# detectability's observable-flip => detector-trigger invariant presumes the
# detectors form the complete available syndrome.
_CHECK_REQUIRED_CONTEXT: dict[str, tuple[str, ...]] = {
    "detectability": ("complete_syndrome",),
}


@dataclass(frozen=True)
class Profile:
    """A named lint configuration: enabled checks plus context demands."""

    name: str
    description: str
    # Check names enabled by this profile (subset of the production registry).
    enabled_checks: tuple[str, ...]
    # Maps a check name (or "*" for every enabled check) to context fields the
    # profile demands before that check may emit a verdict.
    context_requirements: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Per-check severity overrides applied after checks run; validated for
    # direction by validate_severity_override().
    severity_overrides: tuple[tuple[str, str], ...] = ()

    def required_context_for(self, check_name: str) -> tuple[str, ...]:
        """Return the context fields this profile demands for *check_name*."""
        fields: tuple[str, ...] = ()
        for name, required in self.context_requirements:
            if name == check_name or name == "*":
                fields = tuple(dict.fromkeys(fields + required))
        return fields


PROFILES: dict[str, Profile] = {
    "strict-dem": Profile(
        name="strict-dem",
        description=(
            "Default for ordinary compiled DEMs assumed to be single decoding "
            "graphs; demands syndrome-completeness context for detectability."
        ),
        enabled_checks=(
            "correctability",
            "detectability",
            "duplicates",
            "observable_coverage",
            "probability_bounds",
            "sensitivity",
        ),
        context_requirements=(
            ("detectability", ("circuit_role", "complete_syndrome")),
        ),
    ),
    "graphlike-decoder": Profile(
        name="graphlike-decoder",
        description=(
            "For DEMs decoded by a graphlike matcher; requires an explicit "
            "decoder assumption on every check."
        ),
        enabled_checks=(
            "correctability",
            "detectability",
            "duplicates",
            "observable_coverage",
            "probability_bounds",
            "sensitivity",
        ),
        context_requirements=(("*", ("decoder",)),),
    ),
    "surface-code-circuit": Profile(
        name="surface-code-circuit",
        description=(
            "Circuit-level surface-code DEMs where geometric heuristics are "
            "meaningful; no additional context demands."
        ),
        enabled_checks=(
            "correctability",
            "detectability",
            "duplicates",
            "observable_coverage",
            "probability_bounds",
            "sensitivity",
        ),
    ),
    "subsystem-code": Profile(
        name="subsystem-code",
        description=(
            "Subsystem-code DEMs; gauge-related findings stay warnings and "
            "correctability is model-specific."
        ),
        enabled_checks=(
            "correctability",
            "detectability",
            "duplicates",
            "observable_coverage",
            "probability_bounds",
            "sensitivity",
        ),
        context_requirements=(("correctability", ("circuit_role",)),),
    ),
}


def validate_severity_override(
    check_name: str, severity: str, *, allow_downgrade: bool = False
) -> None:
    """Reject overrides outside the allowed directions of the severity contract.

    Heuristic checks may not be upgraded to ``error``. Deterministic checks may
    only be *downgraded* with an explicit opt-in (``allow_downgrade=True``,
    wired to the CLI's ``--allow-severity-downgrade``), because a downgrade
    changes exit codes 1 -> 2 and weakens the error-severity soundness contract.
    The opt-in lives here so every caller — CLI, library API, and profile
    declarations — goes through the same gate.
    """
    if severity not in {"error", "warning"}:
        raise ValueError(f"invalid override severity {severity!r} for {check_name}")
    if severity == "error":
        if check_name not in _DETERMINISTIC_CHECKS:
            raise ValueError(
                f"{check_name} is heuristic and cannot be upgraded to error; "
                "only deterministic checks may be promoted"
            )
    elif not allow_downgrade:
        raise ValueError(
            f"downgrading {check_name} to warning weakens the error-severity "
            "contract; pass --allow-severity-downgrade (CLI) or "
            "allow_downgrade=True (library) to permit it"
        )


def parse_context_value(raw: str) -> bool | str:
    """Parse a CLI/TOML context scalar: booleans stay booleans, rest is str."""
    lowered = raw.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return raw


def _skip_reason(
    check_name: str,
    context: dict[str, bool | str],
    profile: Profile | None,
) -> tuple[str, bool] | None:
    """Return (reason, declared_unsupported_role) or None if the check may run."""
    if not context and profile is None:
        return None
    role = context.get("circuit_role")
    blocked = _UNSUPPORTED_ROLES.get(check_name, frozenset())
    if isinstance(role, str) and role in blocked:
        # An explicit complete_syndrome=True claim re-enables the check: the
        # user asserts the syndrome is complete despite the unusual role.
        if check_name == "detectability" and context.get("complete_syndrome") is True:
            return None
        return (
            f"circuit_role={role!r} is outside the check's applicability domain",
            True,
        )
    required = list(_CHECK_REQUIRED_CONTEXT.get(check_name, ()))
    if profile is not None:
        required = list(
            dict.fromkeys(required + list(profile.required_context_for(check_name)))
        )
    missing = [field for field in required if field not in context]
    if missing:
        return ("missing required context: " + ", ".join(missing), False)
    return None


def applicability_skip_reason(
    check_name: str,
    context: dict[str, bool | str],
    profile: Profile | None,
) -> str | None:
    """Return why *check_name* must be skipped, or None if it may run.

    Combines two sources per the applicability contract:
    - declared unsupported circuit roles (never a verdict);
    - missing context fields required by the check itself or the profile.

    Applicability is opt-in: when no context is declared at all (the default
    invocation), every check runs as before. Demanding context only once the
    user starts declaring it keeps existing behavior byte-identical while
    making partial declarations explicit.
    """
    skip = applicability_skip(check_name, context, profile)
    return skip[0] if skip is not None else None


def applicability_skip(
    check_name: str,
    context: dict[str, bool | str],
    profile: Profile | None,
) -> tuple[str, Literal["skipped", "inconclusive"]] | None:
    """Return (reason, status) why *check_name* must not emit a verdict, or None.

    The status distinguishes the two skip sources per the applicability
    contract:

    - A *declared unsupported circuit role* is an affirmative user declaration
      that the DEM sits outside the check's applicability domain. The check
      reports a plain ``skipped`` result (exit-neutral): ``detectability`` on
      a state-preparation DEM with ``circuit_role=state_preparation`` is the
      canonical case. An explicit ``complete_syndrome=True`` claim re-enables
      the check instead.
    - *Missing required context* means the caller did not supply demanded
      metadata, so the check could not evaluate. Deterministic checks surface
      as ``inconclusive`` (contributes to exit 2) — a run that silently lacks
      its context must never let an error-severity bug hide behind exit 0.
      Warning-severity checks keep the exit-neutral ``skipped``.
    """
    skip = _skip_reason(check_name, context, profile)
    if skip is None:
        return None
    reason, declared_unsupported = skip
    if declared_unsupported or check_name not in _DETERMINISTIC_CHECKS:
        return reason, "skipped"
    return reason, "inconclusive"
