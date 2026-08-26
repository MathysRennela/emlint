"""Command-line interface for emlint."""

from __future__ import annotations

import argparse
import importlib.metadata
import sys

import sys

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib

from pathlib import Path
from typing import Any

import emlint
from emlint.checks import ALL_CHECKS
from emlint.report import format_json, format_sarif, format_text


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
        choices=["text", "json", "sarif"],
        default=None,
        help="Output format (default: text, or project setting).",
    )
    check_cmd.add_argument(
        "--check",
        metavar="NAMES",
        help=(
            "Comma-separated list of check names to run (legacy alias for --only). "
            f"Available: {', '.join(ALL_CHECKS)}."
        ),
    )
    check_cmd.add_argument(
        "--only",
        metavar="NAMES",
        help="Comma-separated list of checks to run (default: all).",
    )
    check_cmd.add_argument(
        "--ignore",
        metavar="NAMES",
        help="Comma-separated list of checks to exclude.",
    )
    check_cmd.add_argument(
        "--severity",
        choices=["error", "warning"],
        default=None,
        help="Minimum severity to report (default: warning, or project setting). "
        "Use 'error' to suppress warnings and only surface error-severity findings.",
    )
    check_cmd.add_argument(
        "--allow-severity-downgrade",
        action="store_true",
        default=False,
        help="Permit severity_overrides that downgrade deterministic checks to "
        "warning (changes exit codes 1 -> 2). Off by default.",
    )
    check_cmd.add_argument(
        "--profile",
        metavar="NAME",
        default=None,
        help="Select a named profile (default: none, or project setting). "
        "Profiles restrict the battery and demand context; they never alter "
        "the 0/1/2 exit-code contract.",
    )
    check_cmd.add_argument(
        "--context",
        metavar="KEY=VALUE",
        action="append",
        default=None,
        help="Applicability metadata, e.g. --context circuit_role=memory. "
        "Repeatable. Checks whose required context is missing are reported "
        "as skipped, never silently omitted.",
    )
    return parser


def _config_path(source: str) -> Path | None:
    """Find the nearest project pyproject.toml for a CLI source."""
    candidate = Path(source)
    start = candidate.parent if candidate.is_file() else Path.cwd()
    for directory in (start, *start.parents):
        path = directory / "pyproject.toml"
        if path.is_file():
            return path
    return None


def _project_settings(source: str) -> dict[str, Any]:
    path = _config_path(source)
    if path is None:
        return {}
    with path.open("rb") as handle:
        document = tomllib.load(handle)
    settings = document.get("tool", {}).get("emlint", {})
    if not isinstance(settings, dict):
        raise TypeError("[tool.emlint] must be a TOML table")
    return settings


def _names(value: str | list[str] | None) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, str):
        return [name.strip() for name in value.split(",") if name.strip()]
    if isinstance(value, list) and all(isinstance(name, str) for name in value):
        return [name.strip() for name in value if name.strip()]
    raise ValueError("check lists must be comma-separated strings or TOML arrays")


def _parse_context_args(pairs: list[str] | None) -> dict[str, bool | str]:
    from emlint.profiles import parse_context_value

    context: dict[str, bool | str] = {}
    if not pairs:
        return context
    for pair in pairs:
        key, sep, raw = pair.partition("=")
        if not sep or not key:
            raise ValueError(f"invalid --context entry {pair!r}; expected KEY=VALUE")
        context[key] = parse_context_value(raw)
    return context


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    try:
        settings = _project_settings(args.source)
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        parser.error(f"Invalid project configuration: {exc}")

    try:
        configured_only = _names(settings.get("only"))
        configured_ignore = _names(settings.get("ignore")) or []
    except ValueError as exc:
        parser.error(f"Invalid project configuration: {exc}")

    configured_context = settings.get("context", {})
    if not isinstance(configured_context, dict):
        parser.error("[tool.emlint] context must be a TOML table")

    configured_overrides = settings.get("severity_overrides", {})
    if not isinstance(configured_overrides, dict):
        parser.error(
            "[tool.emlint] severity_overrides must be a table of "
            "check-name = severity"
        )

    try:
        run_context = dict(configured_context)
        run_context.update(_parse_context_args(args.context))
    except ValueError as exc:
        parser.error(f"Invalid --context: {exc}")

    profile_name = args.profile or settings.get("profile")
    profile_obj = None
    if profile_name is not None:
        from emlint.profiles import PROFILES

        if profile_name not in PROFILES:
            parser.error(
                f"Unknown profile {profile_name!r}. Available: {', '.join(PROFILES)}."
            )
        profile_obj = PROFILES[profile_name]

    if args.check and args.only:
        parser.error("--check and --only cannot be used together")
    selected = (
        _names(args.only or args.check)
        if (args.only or args.check)
        else configured_only
    )
    ignored = (_names(args.ignore) if args.ignore else configured_ignore) or []
    names = list(selected) if selected is not None else list(ALL_CHECKS)
    names = [name for name in names if name not in ignored]
    if profile_obj is not None and selected is None:
        names = [name for name in names if name in profile_obj.enabled_checks]
    unknown = [name for name in names + ignored if name not in ALL_CHECKS]
    if unknown:
        parser.error(
            f"Unknown check(s): {', '.join(dict.fromkeys(unknown))}. "
            f"Available: {', '.join(ALL_CHECKS)}."
        )
    checks = {name: ALL_CHECKS[name] for name in names}

    if profile_obj is not None:
        outside = sorted(set(checks) - set(profile_obj.enabled_checks))
        if outside and set(checks) != set(ALL_CHECKS):
            parser.error(
                f"check(s) {', '.join(outside)} are outside profile "
                f"{profile_name!r}; drop the profile or the explicit check "
                "selection."
            )

    output_format = args.format or settings.get("format", "text")
    severity = args.severity or settings.get("severity", "warning")
    if output_format not in {"text", "json", "sarif"}:
        parser.error("format must be one of: text, json, sarif")
    if severity not in {"error", "warning"}:
        parser.error("severity must be one of: error, warning")

    # Resolve an existing regular file explicitly. Non-files are passed through
    # so emlint.check() can parse raw DEM text and report input failures.
    candidate = Path(args.source)
    source = candidate if candidate.is_file() else args.source

    try:
        report = emlint.check(
            source,
            checks=checks,
            context=run_context,
            profile=profile_name,
            disabled_checks=ignored,
            allow_severity_downgrade=args.allow_severity_downgrade,
        )
    except (OSError, ValueError) as exc:
        print(f"emlint: unable to lint input: {exc}", file=sys.stderr)
        sys.exit(3)

    # Apply per-check severity overrides after the checks ran.
    applied_overrides: dict[str, str] = {}
    if configured_overrides:
        from emlint.profiles import validate_severity_override

        by_name = {r.name: r for r in report.results}
        for name, target in configured_overrides.items():
            if name not in ALL_CHECKS:
                parser.error(
                    f"Unknown check {name!r} in severity_overrides. "
                    f"Available: {', '.join(ALL_CHECKS)}."
                )
            if target not in {"error", "warning"}:
                parser.error(
                    f"Invalid override severity {target!r} for {name}; "
                    "expected 'error' or 'warning'."
                )
            try:
                validate_severity_override(
                    name, target, allow_downgrade=args.allow_severity_downgrade
                )
            except ValueError as exc:
                parser.error(str(exc))
            result = by_name.get(name)
            if result is None or result.status != "verdict":
                # A no-op override (check disabled via only/ignore, skipped by
                # profile, or without a verdict) must not be silent.
                print(
                    f"emlint: warning: severity override for {name!r} had no "
                    "effect (check not run or no verdict emitted)",
                    file=sys.stderr,
                )
                continue
            applied_overrides[name] = result.severity
            result.severity = target  # type: ignore[assignment]
    if applied_overrides:
        # Merge, don't replace: profile-applied overrides recorded by
        # emlint.check() must stay visible alongside config overrides.
        merged = dict(report.applied_overrides)
        merged.update(applied_overrides)
        report.applied_overrides = merged

    # Apply severity filter to the displayed output only; exit code is always
    # based on the full report so that error-severity failures are never silently dropped.
    if severity == "error":
        from emlint.report import Report as _Report

        display_report = _Report(
            results=[
                r
                for r in report.results
                if r.severity == "error" or r.status != "verdict"
            ],
            num_detectors=report.num_detectors,
            num_observables=report.num_observables,
            num_error_mechanisms=report.num_error_mechanisms,
            disabled_checks=report.disabled_checks,
            applied_overrides=report.applied_overrides,
            unknown_instructions=report.unknown_instructions,
        )
    else:
        display_report = report

    formatter = {
        "text": format_text,
        "json": format_json,
        "sarif": format_sarif,
    }[output_format]
    print(formatter(display_report))

    if report.has_errors():
        sys.exit(1)
    elif severity != "error" and report.has_warnings():
        sys.exit(2)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
