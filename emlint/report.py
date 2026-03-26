from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from typing import Callable, Literal

from emlint.model import ErrorModel


@dataclass
class PropertyResult:
    name: str
    passed: bool
    severity: Literal["error", "warning"]
    message: str
    counter_example: str | None = None


@dataclass
class Report:
    results: list[PropertyResult]
    num_detectors: int
    num_observables: int
    num_error_mechanisms: int

    def all_passed(self) -> bool:
        return all(r.passed for r in self.results)

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
    for r in report.results:
        icon = "✓" if r.passed else "✗"
        lines.append(f"  {icon} {r.name}: {r.message}")
        if r.counter_example:
            lines.append(f"      Counter-example: {r.counter_example}")
    return "\n".join(lines)


def format_json(report: Report) -> str:
    data = {
        "num_detectors": report.num_detectors,
        "num_observables": report.num_observables,
        "num_error_mechanisms": report.num_error_mechanisms,
        "all_passed": report.all_passed(),
        "has_errors": report.has_errors(),
        "results": [dataclasses.asdict(r) for r in report.results],
    }
    return json.dumps(data, indent=2)
