"""Tests for the emlint CLI (emlint/cli.py).

All tests invoke main() in-process with sys.argv patched so that
pytest-cov instruments every branch inside main().
"""

from __future__ import annotations

import contextlib
import io
import json
import sys

import pytest

from emlint.cli import _build_parser, main
from emlint.profiles import PROFILES, Profile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASSING_DEM = "error(0.1) D0 L0\ndetector D0\n"
ERROR_DEM = "error(0.1) L0\n"  # detectability violation (no detectors)
WARNING_DEM = "error(0.1) D0 L0\nerror(0.1) D0 L0\ndetector D0\n"  # duplicate (warning)


class _Result:
    def __init__(self, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _run(args: list[str]) -> _Result:
    """Invoke main() in-process with argv patched; capture output and exit code."""
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    old_argv = sys.argv
    sys.argv = ["emlint"] + args
    returncode = 0
    try:
        with (
            contextlib.redirect_stdout(stdout_buf),
            contextlib.redirect_stderr(stderr_buf),
        ):
            main()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.argv = old_argv
    return _Result(stdout_buf.getvalue(), stderr_buf.getvalue(), returncode)


def _run_with_cwd(directory, args: list[str]) -> _Result:
    """Run _run from *directory* so project pyproject.toml settings apply."""
    import os

    old_cwd = os.getcwd()
    os.chdir(directory)
    try:
        return _run(args)
    finally:
        os.chdir(old_cwd)


# ---------------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------------


def test_version_flag():
    with pytest.raises(SystemExit) as exc:
        _build_parser().parse_args(["--version"])
    assert exc.value.code == 0


# ---------------------------------------------------------------------------
# Exit codes
# ---------------------------------------------------------------------------


def test_exit_0_on_all_checks_pass(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file)])
    assert result.returncode == 0


def test_exit_1_on_error_severity_failure(tmp_path):
    dem_file = tmp_path / "bad.dem"
    dem_file.write_text(ERROR_DEM)
    result = _run(["check", str(dem_file)])
    assert result.returncode == 1


def test_exit_2_on_warning_only_failure(tmp_path):
    dem_file = tmp_path / "warn.dem"
    dem_file.write_text(WARNING_DEM)
    result = _run(["check", str(dem_file)])
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------


def test_text_format_is_default(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file)])
    assert "Detectors" in result.stdout


def test_json_format_is_valid_json(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--format", "json"])
    data = json.loads(result.stdout)
    assert "results" in data


def test_json_format_all_passed_field(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--format", "json"])
    data = json.loads(result.stdout)
    assert isinstance(data["all_passed"], bool)


# ---------------------------------------------------------------------------
# Vacuity disclosure
# ---------------------------------------------------------------------------


def test_empty_dem_is_disclosed_as_vacuous(tmp_path):
    """A mechanism-free DEM must be disclosed, not read as a clean audit."""
    dem_file = tmp_path / "empty.dem"
    dem_file.write_text("")
    result = _run(["check", str(dem_file)])
    assert "[vacuous]" in result.stdout
    assert "no error mechanisms" in result.stdout


def test_empty_dem_vacuity_disclosure_keeps_exit_0(tmp_path):
    """The disclosure is report-layer only: it carries no severity."""
    dem_file = tmp_path / "empty.dem"
    dem_file.write_text("")
    result = _run(["check", str(dem_file)])
    assert result.returncode == 0


def test_non_empty_dem_has_no_vacuity_disclosure(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file)])
    assert "[vacuous]" not in result.stdout


def test_json_output_carries_vacuity_flag(tmp_path):
    dem_file = tmp_path / "empty.dem"
    dem_file.write_text("")
    result = _run(["check", str(dem_file), "--format", "json"])
    assert json.loads(result.stdout)["is_vacuous"] is True


# ---------------------------------------------------------------------------
# --check filter
# ---------------------------------------------------------------------------


def test_check_flag_restricts_results(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        [
            "check",
            str(dem_file),
            "--format",
            "json",
            "--check",
            "detectability,sensitivity",
        ]
    )
    data = json.loads(result.stdout)
    names = {r["name"] for r in data["results"]}
    assert names == {"detectability", "sensitivity"}


def test_only_flag_restricts_results(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        ["check", str(dem_file), "--format", "json", "--only", "detectability"]
    )
    data = json.loads(result.stdout)
    assert {r["name"] for r in data["results"]} == {"detectability"}


def test_ignore_flag_excludes_results(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        ["check", str(dem_file), "--format", "json", "--ignore", "sensitivity"]
    )
    data = json.loads(result.stdout)
    assert "sensitivity" not in {r["name"] for r in data["results"]}


def test_sarif_format_is_valid(tmp_path):
    dem_file = tmp_path / "bad.dem"
    dem_file.write_text(ERROR_DEM)
    result = _run(["check", str(dem_file), "--format", "sarif"])
    data = json.loads(result.stdout)
    assert data["version"] == "2.1.0"
    assert data["runs"][0]["results"][0]["ruleId"] == "detectability"


def test_project_settings_apply_to_check(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\nonly = ['detectability']\nformat = 'json'\n"
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    monkeypatch.chdir(tmp_path)
    result = _run(["check", str(dem_file)])
    data = json.loads(result.stdout)
    assert {r["name"] for r in data["results"]} == {"detectability"}


def test_check_flag_unknown_name_exits_nonzero(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--check", "nonexistent_check"])
    assert result.returncode != 0
    assert "nonexistent_check" in result.stderr or "nonexistent_check" in result.stdout


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_nonexistent_file_does_not_traceback():
    result = _run(["check", "/nonexistent/path/circuit.dem"])
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_no_subcommand_exits_0():
    result = _run([])
    assert result.returncode == 0


def test_raw_dem_string_input():
    result = _run(["check", PASSING_DEM])
    assert result.returncode == 0


def test_valid_mixed_coordinate_dem_is_linted():
    dem = "detector(1, 2) D0\ndetector(3, 4, 5) D1\nerror(0.01) D0 D1 L0"
    result = _run(["check", dem])
    assert result.returncode == 0
    assert "Detectors" in result.stdout


def test_unparseable_dem_has_distinct_exit_code():
    result = _run(["check", "this is not a DEM"])
    assert result.returncode == 3
    assert "unable to lint input" in result.stderr
    assert "No static checks were run." in result.stderr


def test_directory_input_has_distinct_exit_code(tmp_path):
    result = _run(["check", str(tmp_path)])
    assert result.returncode == 3
    assert "unable to lint input" in result.stderr
    assert "Traceback" not in result.stderr


# ---------------------------------------------------------------------------
# --severity filter
# ---------------------------------------------------------------------------


def test_severity_error_suppresses_warnings(tmp_path):
    """--severity error hides warning-severity results from output."""
    dem_file = tmp_path / "warn.dem"
    dem_file.write_text(WARNING_DEM)
    result = _run(["check", str(dem_file), "--format", "json", "--severity", "error"])
    assert result.returncode == 0
    data = json.loads(result.stdout)
    # No warning-severity results in output
    assert all(r["severity"] == "error" for r in data["results"])


def test_severity_warning_only_exits_2_by_default(tmp_path):
    dem_file = tmp_path / "warn.dem"
    dem_file.write_text(WARNING_DEM)
    result = _run(["check", str(dem_file)])
    assert result.returncode == 2


def test_severity_error_still_exits_1_on_errors(tmp_path):
    """--severity error does not suppress error-severity exit code."""
    dem_file = tmp_path / "bad.dem"
    dem_file.write_text(ERROR_DEM)
    result = _run(["check", str(dem_file), "--severity", "error"])
    assert result.returncode == 1


def test_severity_warning_is_default(tmp_path):
    """Default behaviour includes warnings in output and exits 2 for warnings-only."""
    dem_file = tmp_path / "warn.dem"
    dem_file.write_text(WARNING_DEM)
    result = _run(["check", str(dem_file), "--format", "json"])
    data = json.loads(result.stdout)
    warning_results = [
        r for r in data["results"] if not r["passed"] and r["severity"] == "warning"
    ]
    assert len(warning_results) > 0
    assert result.returncode == 2


# ---------------------------------------------------------------------------
# Disabled-check reporting and severity overrides
# ---------------------------------------------------------------------------


def test_disabled_checks_reported_in_json(tmp_path):
    """--ignore surfaces the omitted check explicitly; omissions are never silent."""
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        ["check", str(dem_file), "--format", "json", "--ignore", "duplicates"]
    )
    data = json.loads(result.stdout)
    assert data["disabled_checks"] == ["duplicates"]
    assert "duplicates" not in {r["name"] for r in data["results"]}


def test_disabled_checks_reported_in_text(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--ignore", "sensitivity"])
    assert "[disabled]" in result.stdout
    assert "sensitivity" in result.stdout


def test_disabled_checks_do_not_affect_exit_code(tmp_path):
    """Disabling a warning check removes its exit-2 contribution."""
    dem_file = tmp_path / "warn.dem"
    dem_file.write_text(WARNING_DEM)
    result = _run(
        ["check", str(dem_file), "--format", "json", "--ignore", "duplicates"]
    )
    assert result.returncode == 0


def test_severity_override_downgrade_applied_and_surfaced(tmp_path):
    """A downgrade override changes severity and appears in applied_overrides."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\nformat = 'json'\n"
        "[tool.emlint.severity_overrides]\n"
        "observable_coverage = 'warning'\n"
    )
    # observable_coverage violation: declared L1 never flipped.
    dem_file = tmp_path / "cov.dem"
    dem_file.write_text("detector D0\nerror(0.1) D0 L1\n")
    monkeypatched = _run_with_cwd(
        tmp_path, ["check", str(dem_file), "--allow-severity-downgrade"]
    )
    data = json.loads(monkeypatched.stdout)
    cov = next(r for r in data["results"] if r["name"] == "observable_coverage")
    assert not cov["passed"]
    assert cov["severity"] == "warning"
    assert data["applied_overrides"] == {"observable_coverage": "error"}


def test_severity_override_upgrade_of_heuristic_check_rejected(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\n" "[tool.emlint.severity_overrides]\n" "duplicates = 'error'\n"
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "heuristic" in result.stderr or "heuristic" in result.stdout


def test_severity_override_unknown_check_rejected(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\n"
        "[tool.emlint.severity_overrides]\n"
        "no_such_check = 'warning'\n"
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "no_such_check" in result.stderr or "no_such_check" in result.stdout


# ---------------------------------------------------------------------------
# --profile pass-through
# ---------------------------------------------------------------------------


def test_profile_context_requirements_enforced_via_cli(tmp_path):
    """--profile must reach emlint.check(): strict-dem demands circuit_role and
    complete_syndrome for detectability, which yields an explicit skip instead
    of a verdict when no context is declared."""
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        ["check", str(dem_file), "--format", "json", "--profile", "strict-dem"]
    )
    data = json.loads(result.stdout)
    detectability = next(r for r in data["results"] if r["name"] == "detectability")
    assert detectability["status"] == "inconclusive"
    assert "complete_syndrome" in detectability["message"]


def test_profile_severity_overrides_applied_via_cli(tmp_path):
    """Profile-declared severity overrides apply on the CLI path."""
    from emlint.profiles import PROFILES

    # Build a one-off profile-like assertion using an existing profile with a
    # context requirement: graphlike-decoder demands `decoder` for every check.
    profile = PROFILES["graphlike-decoder"]
    assert any(name == "*" for name, _ in profile.context_requirements)
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        [
            "check",
            str(dem_file),
            "--format",
            "json",
            "--profile",
            "graphlike-decoder",
        ]
    )
    data = json.loads(result.stdout)
    # Every check is a non-verdict for missing `decoder` context: error-severity
    # checks surface as inconclusive (exit 2), warning-severity ones as skipped.
    assert data["results"]
    assert all(r["status"] in {"inconclusive", "skipped"} for r in data["results"])
    assert all(
        r["status"] == "inconclusive"
        for r in data["results"]
        if r["name"] in {"detectability", "observable_coverage", "probability_bounds"}
    )


def test_filtered_output_preserves_unknown_instructions(
    tmp_path, monkeypatch: pytest.MonkeyPatch
):
    """--severity error display reconstruction keeps the partial-parse flag."""
    from emlint import frontends

    real_from_stim_dem = frontends.from_stim_dem
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)

    def patched(d):
        model = real_from_stim_dem(d)
        model.unknown_instructions.append("adaptive_metadata")
        return model

    monkeypatch.setattr(frontends, "from_stim_dem", patched)
    result = _run(["check", str(dem_file), "--format", "json", "--severity", "error"])
    data = json.loads(result.stdout)
    assert data["unknown_instructions"] == ["adaptive_metadata"]


# ---------------------------------------------------------------------------
# Configuration validation error paths
# ---------------------------------------------------------------------------


def test_cli_rejects_non_table_tool_emlint(tmp_path):
    """[tool.emlint] must be a TOML table (catches the uncovered TypeError)."""
    # foo=1 is a valid table; to force the error we need a non-table value.
    (tmp_path / "pyproject.toml").write_text("tool = { emlint = 'not-a-table' }\n")
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "Invalid project configuration" in result.stderr


def test_cli_rejects_context_not_a_table(tmp_path):
    """[tool.emlint] context must be a TOML table."""
    (tmp_path / "pyproject.toml").write_text("[tool.emlint]\ncontext = 'not-a-table'\n")
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "context must be a TOML table" in result.stderr


def test_cli_rejects_severity_overrides_not_a_table(tmp_path):
    """[tool.emlint] severity_overrides must be a TOML table."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\nseverity_overrides = 'nope'\n"
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "severity_overrides must be a table" in result.stderr


def test_cli_rejects_invalid_context_entry(tmp_path):
    """A malformed --context entry (no '=') must be rejected."""
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--context", "noequals"])
    assert result.returncode != 0
    assert "Invalid --context" in result.stderr


def test_cli_rejects_check_and_only_together(tmp_path):
    """--check and --only cannot be used together."""
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        ["check", str(dem_file), "--check", "detectability", "--only", "sensitivity"]
    )
    assert result.returncode != 0
    assert "--check and --only cannot be used together" in result.stderr


def test_cli_rejects_unknown_profile(tmp_path):
    """An unknown --profile must be rejected."""
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--profile", "no-such-profile"])
    assert result.returncode != 0
    assert "Unknown profile" in result.stderr


def test_cli_rejects_invalid_format_setting(tmp_path):
    """An invalid format in project settings must be rejected."""
    (tmp_path / "pyproject.toml").write_text("[tool.emlint]\nformat = 'xml'\n")
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "format must be one of" in result.stderr


def test_cli_rejects_invalid_severity_setting(tmp_path):
    """An invalid severity in project settings must be rejected."""
    (tmp_path / "pyproject.toml").write_text("[tool.emlint]\nseverity = 'fatal'\n")
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "severity must be one of" in result.stderr


def test_cli_rejects_invalid_override_severity(tmp_path):
    """An invalid override severity value must be rejected."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\n"
        "[tool.emlint.severity_overrides]\n"
        "observable_coverage = 'info'\n"
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "Invalid override severity" in result.stderr


def test_cli_warns_when_override_has_no_effect(tmp_path):
    """An override for a check that did not run must warn, not silently pass."""
    (tmp_path / "pyproject.toml").write_text(
        "[tool.emlint]\n"
        "only = ['detectability']\n"
        "[tool.emlint.severity_overrides]\n"
        "observable_coverage = 'warning'\n"
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(
        tmp_path, ["check", str(dem_file), "--allow-severity-downgrade"]
    )
    assert "had no effect" in result.stderr


def test_cli_rejects_checks_outside_profile(tmp_path, monkeypatch):
    """An explicit --only selection outside the profile must be rejected."""
    monkeypatch.setitem(
        PROFILES,
        "audit-narrow",
        Profile(
            name="audit-narrow",
            description="only detectability",
            enabled_checks=("detectability",),
        ),
    )
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        [
            "check",
            str(dem_file),
            "--profile",
            "audit-narrow",
            "--only",
            "sensitivity",  # not in audit-narrow's enabled set
        ]
    )
    assert result.returncode != 0
    assert "outside profile" in result.stderr


def test_cli_context_boolean_parsing(tmp_path):
    """--context complete_syndrome=true must parse as a boolean and re-enable
    detectability on an unsupported role."""
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(
        [
            "check",
            str(dem_file),
            "--format",
            "json",
            "--context",
            "circuit_role=state_preparation",
            "--context",
            "complete_syndrome=true",
        ]
    )
    data = json.loads(result.stdout)
    detectability = next(r for r in data["results"] if r["name"] == "detectability")
    assert detectability["status"] == "verdict"


def test_names_rejects_non_string_list():
    """_names must reject a list containing non-strings (catches the uncovered
    ValueError path)."""
    from emlint.cli import _names

    with pytest.raises(ValueError, match="check lists must be"):
        _names([1, 2])


def test_cli_rejects_non_string_only_list(tmp_path):
    """A [tool.emlint] only list containing non-strings must be rejected as an
    invalid project configuration (catches the uncovered config error path)."""
    (tmp_path / "pyproject.toml").write_text("[tool.emlint]\nonly = [1, 2]\n")
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "Invalid project configuration" in result.stderr


def test_cli_rejects_non_string_ignore_list(tmp_path):
    """A [tool.emlint] ignore list containing non-strings must be rejected."""
    (tmp_path / "pyproject.toml").write_text("[tool.emlint]\nignore = [1]\n")
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run_with_cwd(tmp_path, ["check", str(dem_file)])
    assert result.returncode != 0
    assert "Invalid project configuration" in result.stderr
