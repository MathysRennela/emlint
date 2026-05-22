from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ErrorMechanism:
    """A single error mechanism, e.g. "X error on qubit 3 with probability 0.01"."""

    probability: float
    detectors: frozenset[int]
    observables: frozenset[int]


@dataclass(frozen=True)
class RepeatBlock:
    """A repeat block structure, containing a body repeated N times.

    The body is a tuple of ErrorMechanism or nested RepeatBlock nodes.
    This preserves the tree structure of the DEM for the Repeat Rule (v0.2).

    Attributes:
        body: tuple of error mechanisms and/or nested repeat blocks, in order.
            ErrorMechanism.detectors stores IDs that are relative to the start of
            the body scope (i.e. starting from 0 for each independent body walk).
            The absolute ID for mechanism m in iteration k is:
                m.det_id + absolute_start_offset + k * detector_offset_per_iteration.
        count: positive integer, the repetition count.
        detector_offset_per_iteration: total detector index shift accumulated by
            all shift_detectors instructions in one pass of the body. Zero for
            repeat blocks that contain no shift_detectors.
        absolute_start_offset: the cumulative detector index offset at the point
            where this block appears in its parent scope (i.e. the sum of all
            shifts preceding it in the same scope). For top-level blocks this is
            the global accumulated shift; for body blocks it is the accumulated
            shift within the parent body. Used by flattened() to compute the
            correct absolute ID for iteration 0.
    """

    body: tuple[ErrorMechanism | RepeatBlock, ...]
    count: int
    detector_offset_per_iteration: int = 0
    absolute_start_offset: int = 0


@dataclass
class ErrorModel:
    """Frontend-agnostic error model. All checks operate on this."""

    detectors: set[int]
    observables: set[int]
    error_mechanisms: list[ErrorMechanism | RepeatBlock]
    # Maps detector index → coordinate tuple, e.g. {17: (1.0, 0.0, 2.0)}.
    # Populated when the DEM carries detector() coordinate annotations.
    # Empty for DEMs that omit coordinates.
    detector_coords: dict[int, tuple[float, ...]] = field(default_factory=dict)

    def flattened(self) -> list[ErrorMechanism]:
        """Recursively expand the mechanism tree to a flat list.

        Semantics: equivalent to calling dem.flattened() on the source DEM.
        For each RepeatBlock with absolute_start_offset=A, count=N, and
        detector_offset_per_iteration=S, iteration k's body is walked with a
        scope_offset of A + k*S (plus any outer scope_offset from a containing
        block). ErrorMechanism.detectors stores IDs that are scope-relative, so
        the final absolute ID is d + scope_offset.

        Returns:
            A flat list of ErrorMechanism objects with absolute detector indices,
            with all RepeatBlock nesting fully expanded.
        """
        result: list[ErrorMechanism] = []

        def walk(items: tuple[ErrorMechanism | RepeatBlock, ...] | list[ErrorMechanism | RepeatBlock], scope_offset: int) -> None:
            for item in items:
                if isinstance(item, ErrorMechanism):
                    if scope_offset == 0:
                        result.append(item)
                    else:
                        result.append(ErrorMechanism(
                            probability=item.probability,
                            detectors=frozenset(d + scope_offset for d in item.detectors),
                            observables=item.observables,
                        ))
                elif isinstance(item, RepeatBlock):
                    for k in range(item.count):
                        walk(
                            item.body,
                            scope_offset + item.absolute_start_offset + k * item.detector_offset_per_iteration,
                        )

        walk(self.error_mechanisms, 0)
        return result
