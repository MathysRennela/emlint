from __future__ import annotations

import pytest

import emlint

_SYNTHETIC_BUGS = [
    pytest.param(
        "empty syndrome logical error",
        "error(0.1) L0",
        "detectability",
        id="detectability",
    ),
    pytest.param(
        "zero-probability mechanism",
        "error(0) D0\ndetector D0",
        "probability_bounds",
        id="probability_bounds",
    ),
    pytest.param(
        "uncovered observable",
        "error(0.1) D0 L1\ndetector D0",
        "observable_coverage",
        id="observable_coverage",
    ),
    pytest.param(
        "dead detector",
        "error(0.1) D0 L0\ndetector D0\ndetector D1",
        "sensitivity",
        id="sensitivity",
    ),
    pytest.param(
        "duplicate mechanism",
        "error(0.1) D0 L0\nerror(0.2) D0 L0\ndetector D0",
        "duplicates",
        id="duplicates",
    ),
    pytest.param(
        "conflicting observable syndrome",
        "error(0.1) D0 L0\nerror(0.1) D0 L1\ndetector D0",
        "correctability",
        id="correctability",
    ),
]


@pytest.mark.parametrize("bug_name,dem_text,expected_check", _SYNTHETIC_BUGS)
def test_synthetic_bug_corpus_kills_mutation(
    bug_name: str, dem_text: str, expected_check: str
) -> None:
    """Each minimal injected defect is caught by its intended production check."""
    report = emlint.check(dem_text)
    failures = {result.name for result in report.results if not result.passed}

    assert expected_check in failures, (
        f"Synthetic mutation {bug_name!r} was not caught by {expected_check!r}; "
        f"observed failures: {sorted(failures)}"
    )

    result = next(result for result in report.results if result.name == expected_check)
    assert result.counter_example is not None
    assert result.counter_example_data is not None


def test_every_registered_check_has_a_synthetic_bug():
    """A check missing from `_SYNTHETIC_BUGS` gets no mutation-kill coverage here.

    `_SYNTHETIC_BUGS` is a hand-maintained list; a new check added to
    `ALL_CHECKS` without a matching minimal counter-example would silently
    skip this corpus. Guard the registry against that gap explicitly.
    """
    covered = {param.id for param in _SYNTHETIC_BUGS}
    missing = set(emlint.ALL_CHECKS) - covered
    assert not missing, f"no synthetic bug for: {sorted(missing)}"
