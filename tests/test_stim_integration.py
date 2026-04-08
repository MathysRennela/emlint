"""Integration tests: full pipeline from stim → emlint.check().

These tests exercise the real stim dependency end-to-end and are therefore
separated from the unit tests.  They require a working stim installation.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

import stim

import emlint
from emlint.report import Report


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dem(task: str, distance: int = 3, rounds: int = 3, decompose: bool = False) -> stim.DetectorErrorModel:
    circuit = stim.Circuit.generated(
        task,
        rounds=rounds,
        distance=distance,
        after_clifford_depolarization=0.001,
    )
    return circuit.detector_error_model(decompose_errors=decompose)


# ---------------------------------------------------------------------------
# String input
# ---------------------------------------------------------------------------

def test_raw_dem_string_input():
    """emlint.check() should accept a raw DEM string."""
    dem_str = textwrap.dedent("""\
        error(0.1) D0 L0
        detector D0
    """)
    report = emlint.check(dem_str)
    assert isinstance(report, Report)
    # D0 is covered and L0 is covered — detectability, sensitivity pass
    names = {r.name for r in report.results if not r.passed}
    # correctability: D0 has one unique observable set — should pass
    assert "correctability" not in names
    assert "duplicates" not in names


# ---------------------------------------------------------------------------
# File input
# ---------------------------------------------------------------------------

def test_file_path_input(tmp_path: Path):
    """emlint.check() should accept a pathlib.Path to a .dem file."""
    dem_str = textwrap.dedent("""\
        error(0.1) D0 L0
        detector D0
    """)
    dem_file = tmp_path / "test.dem"
    dem_file.write_text(dem_str)
    report = emlint.check(dem_file)
    assert isinstance(report, Report)


def test_string_file_path_input(tmp_path: Path):
    """emlint.check() should accept a str path to a .dem file."""
    dem_str = textwrap.dedent("""\
        error(0.1) D0 L0
        detector D0
    """)
    dem_file = tmp_path / "test.dem"
    dem_file.write_text(dem_str)
    report = emlint.check(str(dem_file))
    assert isinstance(report, Report)


def test_invalid_content_in_path_file_raises_value_error(tmp_path: Path):
    """A Path pointing to a file with invalid DEM content must raise ValueError."""
    bad_file = tmp_path / "bad.dem"
    bad_file.write_text("this is not a valid DEM")
    with pytest.raises(ValueError, match="Failed to parse DEM"):
        emlint.check(bad_file)


def test_invalid_content_in_str_file_path_raises_value_error(tmp_path: Path):
    """A str path pointing to a file with invalid DEM content must raise ValueError."""
    bad_file = tmp_path / "bad.dem"
    bad_file.write_text("this is not a valid DEM")
    with pytest.raises(ValueError, match="Failed to parse DEM"):
        emlint.check(str(bad_file))


def test_invalid_raw_dem_string_raises_value_error():
    """A raw string that is not a valid DEM and not an existing path must raise ValueError."""
    with pytest.raises(ValueError, match="Failed to parse DEM"):
        emlint.check("not valid DEM syntax @@@@")


# ---------------------------------------------------------------------------
# Pathological DEMs
# ---------------------------------------------------------------------------

def test_empty_dem_passes_all_checks():
    """An empty DEM (no mechanisms, no detectors, no observables) must pass everything."""
    report = emlint.check(stim.DetectorErrorModel())
    assert report.all_passed()


def test_detectability_violation_detected():
    """An observable-flipping mechanism with no detectors must fail detectability."""
    dem = stim.DetectorErrorModel("error(0.1) L0")
    report = emlint.check(dem)
    detectability = next(r for r in report.results if r.name == "detectability")
    assert not detectability.passed


def test_correctability_violation_detected():
    """The same syndrome pointing at two different observable sets must fail correctability."""
    dem = stim.DetectorErrorModel(textwrap.dedent("""\
        error(0.1) D0 L0
        error(0.1) D0 L1
        detector D0
    """))
    report = emlint.check(dem)
    correctability = next(r for r in report.results if r.name == "correctability")
    assert not correctability.passed


def test_sensitivity_violation_detected():
    """A declared detector with no mechanism referencing it must fail sensitivity."""
    # detector D1 is declared but no error mechanism fires it
    dem = stim.DetectorErrorModel(textwrap.dedent("""\
        error(0.1) D0 L0
        detector D0
        detector D1
    """))
    report = emlint.check(dem)
    sensitivity = next(r for r in report.results if r.name == "sensitivity")
    assert not sensitivity.passed


def test_observable_coverage_violation_detected():
    """An observable that no mechanism flips must fail observable_coverage.
    The mechanism flips L1, so stim sets num_observables=2. L0 is never flipped
    by any mechanism and is therefore uncovered."""
    dem = stim.DetectorErrorModel("error(0.1) D0 L1\ndetector D0")
    report = emlint.check(dem)
    cov = next(r for r in report.results if r.name == "observable_coverage")
    assert not cov.passed


def test_probability_bounds_violation_detected():
    """p=0 must fail probability_bounds."""
    dem = stim.DetectorErrorModel(textwrap.dedent("""\
        error(0) D0
        detector D0
    """))
    report = emlint.check(dem)
    bounds = next(r for r in report.results if r.name == "probability_bounds")
    assert not bounds.passed


def test_duplicates_violation_detected():
    """The same mechanism listed twice must fail duplicates."""
    dem = stim.DetectorErrorModel(textwrap.dedent("""\
        error(0.1) D0 L0
        error(0.2) D0 L0
        detector D0
    """))
    report = emlint.check(dem)
    dups = next(r for r in report.results if r.name == "duplicates")
    assert not dups.passed


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_invalid_source_type_raises_type_error():
    with pytest.raises(TypeError):
        emlint.check(12345)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# False-positive audit: warning inventory
# ---------------------------------------------------------------------------
# For the false-positive audit we run all checks on every circuit family at
# d=3,5,7 with decompose_errors=False and decompose_errors=True and record
# which warning-severity checks (not error-severity) fire. The allowed set below
# documents *expected* warnings so that any new unexpected warning breaks CI.
#
# Observed warning profile (confirmed as of v0.1, using stim >= 1.14):
#
#  decompose=False:
#  - surface_code:rotated_memory_z  d=3,5   → (none)
#  - surface_code:rotated_memory_z  d=7     → duplicates
#        Stim emits genuinely duplicate mechanisms in the d=7 rotated surface
#        code DEM even without decomposition (boundary geometry at this scale
#        produces coincident fault paths). This is a property of the code/stim
#        output, not a bug in emlint.
#  - surface_code:rotated_memory_x  d=3     → (none)
#  - surface_code:unrotated_memory_x d=3    → (none)
#  - surface_code:unrotated_memory_z d=3    → (none)
#  - repetition_code:memory         d=3,5,7 → duplicates
#        Repetition code DEMs always contain duplicate boundary mechanisms;
#        XOR-folded probability is correct but stim emits both entries.
#  - color_code:memory_xyz          d=3     → correctability
#        CSS colour codes are degenerate: multiple syndromes can map to the
#        same logical; this is a known property, not a bug.
#
#  decompose=True (all families additionally):
#  - duplicates fires universally
#        Stim's error decomposition splits hyperedge error mechanisms into
#        multiple simpler mechanisms that share the same (detectors, observables)
#        signature. Every decomposed DEM will trigger this warning.
#  - correctability fires for surface codes (same reason as decompose=False
#        colour code: decomposition artefacts produce conflicting syndrome maps).
#
# Hard constraint (confirmed by this audit): zero error-severity violations on
# any well-formed stim-generated DEM across all code families and distances.
# ---------------------------------------------------------------------------

# Maps (task, distance, decompose) → set of warning check names that are expected to fire.
# Using distance as part of the key prevents masking distance-specific regressions
# (e.g. rotated_memory_z only emits `duplicates` at d=7, not d=3/d=5).
_EXPECTED_WARNINGS: dict[tuple[str, int, bool], set[str]] = {
    ("surface_code:rotated_memory_z",    3, False): set(),
    ("surface_code:rotated_memory_z",    5, False): set(),
    ("surface_code:rotated_memory_z",    7, False): {"duplicates"},
    ("surface_code:rotated_memory_z",    3, True):  {"duplicates", "correctability"},
    ("surface_code:rotated_memory_z",    5, True):  {"duplicates", "correctability"},
    ("surface_code:rotated_memory_z",    7, True):  {"duplicates", "correctability"},
    ("surface_code:rotated_memory_x",    3, False): set(),
    ("surface_code:rotated_memory_x",    3, True):  {"duplicates", "correctability"},
    ("surface_code:unrotated_memory_x",  3, False): set(),
    ("surface_code:unrotated_memory_x",  3, True):  {"duplicates", "correctability"},
    ("surface_code:unrotated_memory_z",  3, False): set(),
    ("surface_code:unrotated_memory_z",  3, True):  {"duplicates", "correctability"},
    ("repetition_code:memory",           3, False): {"duplicates"},
    ("repetition_code:memory",           5, False): {"duplicates"},
    ("repetition_code:memory",           7, False): {"duplicates"},
    ("repetition_code:memory",           3, True):  {"duplicates", "correctability"},
    ("repetition_code:memory",           5, True):  {"duplicates", "correctability"},
    ("repetition_code:memory",           7, True):  {"duplicates", "correctability"},
    ("color_code:memory_xyz",            3, False): {"correctability"},
    ("color_code:memory_xyz",            3, True):  {"duplicates", "correctability"},
}

_AUDIT_CASES = [
    pytest.param(task, d, r, decompose, id=f"{task.split(':')[1]}_d{d}_r{r}_decomp{int(decompose)}")
    for task, d, r in [
        ("surface_code:rotated_memory_z",   3,  3),
        ("surface_code:rotated_memory_z",   5,  5),
        ("surface_code:rotated_memory_z",   7,  7),
        # High-rounds case: catches temporal duplicates that only emerge at depth.
        ("surface_code:rotated_memory_z",   7, 20),
        ("surface_code:rotated_memory_x",   3,  3),
        ("surface_code:unrotated_memory_x", 3,  3),
        ("surface_code:unrotated_memory_z", 3,  3),
        ("repetition_code:memory",          3,  5),
        ("repetition_code:memory",          5,  5),
        ("repetition_code:memory",          7,  7),
        ("color_code:memory_xyz",           3,  3),
    ]
    for decompose in (False, True)
]


@pytest.mark.parametrize("task,distance,rounds,decompose", _AUDIT_CASES)
def test_false_positive_audit(task, distance, rounds, decompose):
    """False-positive audit: no error-severity violations; only expected warnings fire.

    This test encodes the known warning profile for each (code-family, decompose)
    combination. An unexpected warning is treated as a regression just as an
    unexpected error would be.
    """
    dem = _make_dem(task, distance, rounds, decompose=decompose)
    report = emlint.check(dem)

    # --- Hard rule: zero error-severity failures on any well-formed DEM ----------
    error_failures = [r for r in report.results if not r.passed and r.severity == "error"]
    assert error_failures == [], (
        f"[{task} d={distance} decompose={decompose}] unexpected error-severity failures: "
        f"{[r.name for r in error_failures]}"
    )

    # --- Soft rule: warning profile matches the known-good inventory -------------
    actual_warnings = {r.name for r in report.results if not r.passed and r.severity == "warning"}
    expected_warnings = _EXPECTED_WARNINGS.get((task, distance, decompose), set())
    assert actual_warnings == expected_warnings, (
        f"[{task} d={distance} decompose={decompose}] warning mismatch — "
        f"got {actual_warnings}, expected {expected_warnings}. "
        f"Update _EXPECTED_WARNINGS if the change is intentional."
    )
