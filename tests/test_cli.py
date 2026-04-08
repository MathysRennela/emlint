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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PASSING_DEM = "error(0.1) D0 L0\ndetector D0\n"
ERROR_DEM   = "error(0.1) L0\n"          # detectability violation (no detectors)
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
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            main()
    except SystemExit as exc:
        returncode = exc.code if isinstance(exc.code, int) else 0
    finally:
        sys.argv = old_argv
    return _Result(stdout_buf.getvalue(), stderr_buf.getvalue(), returncode)


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
# --check filter
# ---------------------------------------------------------------------------

def test_check_flag_restricts_results(tmp_path):
    dem_file = tmp_path / "ok.dem"
    dem_file.write_text(PASSING_DEM)
    result = _run(["check", str(dem_file), "--format", "json", "--check", "detectability,sensitivity"])
    data = json.loads(result.stdout)
    names = {r["name"] for r in data["results"]}
    assert names == {"detectability", "sensitivity"}


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
    warning_results = [r for r in data["results"] if not r["passed"] and r["severity"] == "warning"]
    assert len(warning_results) > 0
    assert result.returncode == 2
