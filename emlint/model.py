from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ErrorMechanism:
    """A single error mechanism, e.g. "X error on qubit 3 with probability 0.01". """
    probability: float
    detectors: frozenset[int]
    observables: frozenset[int]


@dataclass
class ErrorModel:
    """Frontend-agnostic error model. All checks operate on this."""
    detectors: set[int]
    observables: set[int]
    error_mechanisms: list[ErrorMechanism]
    # Maps detector index → coordinate tuple, e.g. {17: (1.0, 0.0, 2.0)}.
    # Populated when the DEM carries detector() coordinate annotations.
    # Empty for DEMs that omit coordinates.
    detector_coords: dict[int, tuple[float, ...]] = field(default_factory=dict)
