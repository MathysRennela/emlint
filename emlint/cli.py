"""Command-line interface for emlint."""
from __future__ import annotations

import argparse
import importlib.metadata
import sys
from pathlib import Path

import emlint
from emlint.checks import ALL_CHECKS
from emlint.report import format_json, format_text

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="emlint",
        description="Static analysis for Detector Error Models.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {importlib.metadata.version('emlint')}",
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    check_cmd = sub.add_parser("check", help="Run checks against a DEM file or string.")
    check_cmd.add_argument(
        "source",
        help="Path to a .dem file, or a raw DEM string.",
    )
    check_cmd.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    check_cmd.add_argument(
        "--check",
        metavar="NAMES",
        help=(
            "Comma-separated list of check names to run (default: all). "
            f"Available: {', '.join(ALL_CHECKS)}."
        ),
    )
    check_cmd.add_argument(
        "--severity",
        choices=["error", "warning"],
        default="warning",
        help="Minimum severity to report (default: warning). "
             "Use 'error' to suppress warnings and only surface error-severity findings.",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    # Resolve check subset
    checks = None
    if args.check:
        names = [n.strip() for n in args.check.split(",")]
        unknown = [n for n in names if n not in ALL_CHECKS]
        if unknown:
            parser.error(
                f"Unknown check(s): {', '.join(unknown)}. "
                f"Available: {', '.join(ALL_CHECKS)}."
            )
        checks = {n: ALL_CHECKS[n] for n in names}

    try:
        report = emlint.check(args.source, checks=checks)
    except FileNotFoundError:
        parser.error(f"File not found: {args.source}")
    except PermissionError:
        parser.error(f"Permission denied: {args.source}")
    except ValueError as exc:
        parser.error(str(exc))

    # Apply severity filter to the displayed output only; exit code is always
    # based on the full report so that error-severity failures are never silently dropped.
    if args.severity == "error":
        from emlint.report import Report as _Report
        display_report = _Report(
            results=[r for r in report.results if r.severity == "error"],
            num_detectors=report.num_detectors,
            num_observables=report.num_observables,
            num_error_mechanisms=report.num_error_mechanisms,
        )
    else:
        display_report = report

    formatter = format_json if args.format == "json" else format_text
    print(formatter(display_report))

    if report.has_errors():
        sys.exit(1)
    elif args.severity != "error" and report.has_warnings():
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
