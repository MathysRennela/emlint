from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Callable, Literal


@dataclass
class PropertyResult:
    name: str
    passed: bool
    severity: Literal["error", "warning"]
    message: str
    counter_example: str | None = None
    counter_example_data: dict | None = None
    status: Literal["verdict", "skipped", "inconclusive"] = "verdict"


@dataclass
class Report:
    results: list[PropertyResult]
    num_detectors: int
    num_observables: int
    num_error_mechanisms: int
    # Check names selected out of the battery by user configuration. Surfaced
    # so that omissions are never silent.
    disabled_checks: list[str] = dataclasses.field(default_factory=list)
    # Per-check severity overrides applied after checks ran, as
    # {check_name: original_severity}. Surfaced so weakenings are visible.
    applied_overrides: dict[str, str] = dataclasses.field(default_factory=dict)
    unknown_instructions: list[str] = dataclasses.field(default_factory=list)

    def all_passed(self) -> bool:
        return all(r.passed or r.status == "skipped" for r in self.results)

    @property
    def any_skipped(self) -> bool:
        """True when the battery is partial: some checks did not emit a verdict."""
        return any(r.status != "verdict" for r in self.results)

    def has_errors(self) -> bool:
        return any(not r.passed and r.severity == "error" for r in self.results)

    def has_warnings(self) -> bool:
        return any(not r.passed and r.severity == "warning" for r in self.results)


# The canonical type for all check functions.
# Extension packages should use this to type-check their custom checks.
# Callable[..., PropertyResult] accommodates the optional max_shown parameter
# without breaking structural compatibility.
CheckFn = Callable[..., PropertyResult]


def format_text(report: Report) -> str:
    lines: list[str] = [
        f"Detectors: {report.num_detectors}  "
        f"Observables: {report.num_observables}  "
        f"Error mechanisms: {report.num_error_mechanisms}",
        "",
    ]
    if report.disabled_checks:
        lines.append(
            "  [disabled] checks not run by configuration: "
            + ", ".join(report.disabled_checks)
        )
        lines.append("")
    if report.applied_overrides:
        for name, original in report.applied_overrides.items():
            current = next((r.severity for r in report.results if r.name == name), None)
            if current is None:
                continue
            lines.append(f"  [override] {name}: severity {original} -> {current}")
        lines.append("")
    if report.unknown_instructions:
        lines.append(
            "  [partial-parse] DEM instructions not representable by emlint "
            "(checks ran on a partial view): " + ", ".join(report.unknown_instructions)
        )
        lines.append("")
    if report.any_skipped:
        skipped_names = [r.name for r in report.results if r.status != "verdict"]
        lines.append(
            "  [partial] checks without a verdict (skipped/inconclusive): "
            + ", ".join(skipped_names)
        )
        lines.append("")
    for r in report.results:
        if r.status == "skipped":
            lines.append(f"  - [skipped] {r.name}: {r.message}")
            continue
        if r.status == "inconclusive":
            lines.append(f"  ? [inconclusive] {r.name}: {r.message}")
            continue
        icon = "✓" if r.passed else "✗"
        severity_tag = f" [{r.severity}]" if not r.passed else ""
        lines.append(f"  {icon}{severity_tag} {r.name}: {r.message}")
        if r.counter_example:
            lines.append(f"      Counter-example: {r.counter_example}")
    return "\n".join(lines)


def format_json(report: Report) -> str:
    data = {
        "num_detectors": report.num_detectors,
        "num_observables": report.num_observables,
        "num_error_mechanisms": report.num_error_mechanisms,
        "disabled_checks": report.disabled_checks,
        "applied_overrides": report.applied_overrides,
        "unknown_instructions": report.unknown_instructions,
        "all_passed": report.all_passed(),
        "any_skipped": report.any_skipped,
        "has_errors": report.has_errors(),
        "has_warnings": report.has_warnings(),
        "results": [dataclasses.asdict(r) for r in report.results],
    }
    return json.dumps(data, indent=2)


def format_sarif(report: Report) -> str:
    """Format failed checks as a SARIF 2.1.0 static-analysis report."""
    rules = [
        {
            "id": result.name,
            "shortDescription": {"text": result.name},
            "help": {"text": result.message},
            "properties": {"severity": result.severity},
        }
        for result in report.results
    ]
    results = [
        {
            "ruleId": result.name,
            "level": (
                "error"
                if result.status == "verdict" and result.severity == "error"
                else "warning" if result.status == "verdict" else "note"
            ),
            "message": {"text": result.message},
            "properties": {
                "passed": result.passed,
                "status": result.status,
                "counter_example": result.counter_example,
                "counter_example_data": result.counter_example_data,
            },
        }
        for result in report.results
        if not result.passed
    ]
    data = {
        "$schema": ("https://json.schemastore.org/sarif-2.1.0.json"),
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "emlint", "rules": rules}},
                "results": results,
                "properties": {
                    "num_detectors": report.num_detectors,
                    "num_observables": report.num_observables,
                    "num_error_mechanisms": report.num_error_mechanisms,
                    "disabled_checks": report.disabled_checks,
                    "applied_overrides": report.applied_overrides,
                    "unknown_instructions": report.unknown_instructions,
                    "any_skipped": report.any_skipped,
                },
            }
        ],
    }
    return json.dumps(data, indent=2)
