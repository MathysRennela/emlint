from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import dataclass, field


def _validate_exact_int(value: object, label: str) -> None:
    """Require an integer field without accepting booleans as integers."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an exact integer")


def _validate_ids(values: Collection[object], label: str) -> None:
    """Require every identifier in a collection to be a non-negative integer."""
    for value in values:
        _validate_exact_int(value, f"{label} ID")
        if isinstance(value, int) and value < 0:
            raise ValueError(f"{label} ID must be non-negative")


def _validate_shifted_ids(values: Collection[int], offset: int, label: str) -> None:
    """Reject detector IDs that become negative after one scope offset."""
    for value in values:
        absolute = value + offset
        if absolute < 0:
            raise ValueError(f"{label} ID becomes negative after applying offset")


def _validate_progression_ids(
    values: Collection[int], start: int, stride: int, count: int, label: str
) -> None:
    """Reject negative IDs at both endpoints of a symbolic progression."""
    if count == 0:
        return
    _validate_shifted_ids(values, start, label)
    if count > 1:
        _validate_shifted_ids(values, start + (count - 1) * stride, label)


@dataclass(frozen=True)
class ErrorMechanism:
    """A single error mechanism, e.g. "X error on qubit 3 with probability 0.01"."""

    probability: float
    detectors: frozenset[int]
    observables: frozenset[int]
    # Per-^ component signatures from a decomposed error instruction.
    # Each element is (detectors, observables) for one component; empty when
    # the instruction carried no separator targets. Component detector IDs are
    # stored with the same scoping as `detectors` (relative inside repeat bodies).
    decomposition_hints: tuple[tuple[frozenset[int], frozenset[int]], ...] = ()


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
    unknown_instructions: list[str] = field(default_factory=list)

    def _validate_tree(self) -> None:
        """Validate the repeat tree before any traversal can silently skip data."""
        _validate_ids(self.detectors, "model detector")
        _validate_ids(self.observables, "model observable")

        def validate_item(item: ErrorMechanism | RepeatBlock, path: str) -> None:
            if isinstance(item, ErrorMechanism):
                if isinstance(item.probability, bool) or not isinstance(
                    item.probability, (int, float)
                ):
                    raise TypeError(f"{path} probability must be numeric")
                _validate_ids(item.detectors, f"{path} detector")
                _validate_ids(item.observables, f"{path} observable")
                if not isinstance(item.decomposition_hints, tuple):
                    raise TypeError(f"{path} decomposition_hints must be a tuple")
                for ci, (cdets, cobs) in enumerate(item.decomposition_hints):
                    _validate_ids(cdets, f"{path} decomposition_hints[{ci}] detector")
                    _validate_ids(cobs, f"{path} decomposition_hints[{ci}] observable")
                return
            if not isinstance(item, RepeatBlock):
                raise TypeError(f"{path} must be an ErrorMechanism or RepeatBlock")
            _validate_exact_int(item.count, f"{path} count")
            if item.count < 0:
                raise ValueError(f"{path} count must be non-negative")
            _validate_exact_int(
                item.detector_offset_per_iteration,
                f"{path} detector_offset_per_iteration",
            )
            _validate_exact_int(
                item.absolute_start_offset, f"{path} absolute_start_offset"
            )
            if not isinstance(item.body, tuple):
                raise TypeError(f"{path} body must be a tuple")
            for index, child in enumerate(item.body):
                validate_item(child, f"{path}.body[{index}]")

        if not isinstance(self.error_mechanisms, list):
            raise TypeError("error_mechanisms must be a list")
        for index, item in enumerate(self.error_mechanisms):
            validate_item(item, f"error_mechanisms[{index}]")

    def iter_flattened(self) -> Iterator[ErrorMechanism]:
        """Lazily yield absolute mechanisms without materializing the flat list."""
        self._validate_tree()
        yield from self._iter_flattened_unchecked()

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
        self._validate_tree()
        return list(self._iter_flattened_unchecked())

    def _iter_flattened_unchecked(self) -> Iterator[ErrorMechanism]:
        """Lazily expand a tree after the caller completed validation."""

        def walk(
            items: (
                tuple[ErrorMechanism | RepeatBlock, ...]
                | list[ErrorMechanism | RepeatBlock]
            ),
            scope_offset: int,
        ) -> Iterator[ErrorMechanism]:
            for item in items:
                if isinstance(item, ErrorMechanism):
                    _validate_shifted_ids(
                        item.detectors, scope_offset, "absolute detector"
                    )
                    if scope_offset == 0:
                        yield item
                    else:
                        yield ErrorMechanism(
                            probability=item.probability,
                            detectors=frozenset(
                                d + scope_offset for d in item.detectors
                            ),
                            observables=item.observables,
                            decomposition_hints=tuple(
                                (
                                    frozenset(d + scope_offset for d in cdets),
                                    cobs,
                                )
                                for cdets, cobs in item.decomposition_hints
                            ),
                        )
                elif isinstance(item, RepeatBlock):
                    for k in range(item.count):
                        yield from walk(
                            item.body,
                            scope_offset
                            + item.absolute_start_offset
                            + k * item.detector_offset_per_iteration,
                        )

        yield from walk(self.error_mechanisms, 0)

    def _flatten_unchecked(self) -> list[ErrorMechanism]:
        """Expand a tree after the caller has completed model validation."""
        return list(self._iter_flattened_unchecked())
