""" "
Property checks for detector error models.

All checks must be pure functions that take an ErrorModel and return a PropertyResult.
They should not raise exceptions.
Any internal errors should be caught and reported as failed checks with appropriate severity and messaging.
They must include counter_example and counter_example_data when passed=False.
"""

from __future__ import annotations

import heapq
import itertools
import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from emlint.model import (
    ErrorMechanism,
    ErrorModel,
    RepeatBlock,
    _shift_target_label,
    _validate_progression_ids,
    _validate_shifted_ids,
)
from emlint.report import CheckFn, PropertyResult

_MAX_SHOWN = 10  # max counter-examples shown in truncated lists


@dataclass(frozen=True)
class _ScopeMechanism:
    mechanism: ErrorMechanism
    absolute_start: int
    detector_stride: int
    count: int


@dataclass(frozen=True)
class _RepeatTemplate:
    mechanism: ErrorMechanism
    absolute_start: int
    repeat_axes: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class _CrossScopeReduction:
    signature_states: dict[
        tuple[frozenset[int], frozenset[int]], tuple[int, float, list[float] | None]
    ]
    conflicts: dict[frozenset[int], set[frozenset[int]]]
    multiplicity: int = 1


def _consumer_signature(
    mechanism: ErrorMechanism,
) -> tuple[frozenset[int], frozenset[int]]:
    """Return the mechanism signature as downstream decoders consume it.

    For decomposed mechanisms (``^``-separated components), decoder-facing
    consumers such as sinter and pymatching treat each component as an
    independent fault: detector symptoms merge by union of component sets,
    while observable frame changes compose by XOR (firing both components of
    ``D0 L0 ^ D1 L0`` flips L0 twice, i.e. not at all). For hand-written DEMs
    whose components share detectors, the XOR-folded ``mechanism.detectors``
    under-reports the syndrome; the union over decomposition_hints restores
    it. Mechanisms without hints are returned unchanged.
    """
    if not mechanism.decomposition_hints:
        return (mechanism.detectors, mechanism.observables)
    dets: set[int] = set()
    for cdets, _cobs in mechanism.decomposition_hints:
        dets |= cdets
    return (frozenset(dets), mechanism.observables)


def _decomposition_structure(mechanism: ErrorMechanism) -> tuple:
    """Return a canonical decomposition structure for component-aware reporting.

    A plain (undecomposed) mechanism is ``("plain",)``. A ``^``-decomposed
    mechanism is ``("decomposed", components)`` where ``components`` is the
    sorted tuple of its per-component ``(detectors, observables)`` pairs.

    Two mechanisms with the same merged signature but different decomposition
    structures are distinct fault paths that collide only at the decoder-facing
    (union) granularity, not true duplicates of the same path.
    """

    if not mechanism.decomposition_hints:
        return ("plain",)
    components = tuple(
        (tuple(sorted(cdets)), tuple(sorted(cobs)))
        for cdets, cobs in mechanism.decomposition_hints
    )
    return ("decomposed", components)


def _decompositions_per_signature(
    model: ErrorModel,
) -> dict[tuple[frozenset[int], frozenset[int]], set[tuple]]:
    """Map each merged signature to the distinct decomposition structures it spans.

    Iterates the flattened mechanisms so the map is faithful to the decoder-
    facing view: a signature is mixed when it is produced by mechanisms with
    different decomposition structures, including collisions that only arise
    across repeat iterations (a plain mechanism in one round and a decomposed
    mechanism with the same merged signature in another). A signature whose set
    has more than one element is a mixed group: distinct fault paths that
    collide at the merged-signature granularity but are not true duplicates.
    """

    result: dict[tuple[frozenset[int], frozenset[int]], set[tuple]] = {}
    for mechanism in model.flattened():
        signature = _consumer_signature(mechanism)
        result.setdefault(signature, set()).add(_decomposition_structure(mechanism))
    return result


def _reduce_cross_scope_mechanisms(
    mechanisms: Iterable[ErrorMechanism],
) -> _CrossScopeReduction:
    """Reduce mechanisms exactly for both cross-scope predicates."""
    signature_states: dict[
        tuple[frozenset[int], frozenset[int]], tuple[int, float, list[float] | None]
    ] = {}
    first_observable: dict[frozenset[int], frozenset[int]] = {}
    conflicts: dict[frozenset[int], set[frozenset[int]]] = {}

    for mechanism in mechanisms:
        signature = _consumer_signature(mechanism)
        state = signature_states.get(signature)
        if state is None:
            signature_states[signature] = (1, mechanism.probability, None)
        else:
            count, p_effective, probabilities = state
            if probabilities is None:
                probabilities = [p_effective]
            probabilities.append(mechanism.probability)
            p_effective = p_effective * (
                1 - mechanism.probability
            ) + mechanism.probability * (1 - p_effective)
            signature_states[signature] = (
                count + 1,
                p_effective,
                probabilities,
            )
        existing = first_observable.get(signature[0])
        if existing is None:
            first_observable[signature[0]] = signature[1]
        elif existing != signature[1]:
            conflicts.setdefault(signature[0], {existing}).add(signature[1])

    return _CrossScopeReduction(signature_states, conflicts)


def _shift_mechanism(mechanism: ErrorMechanism, offset: int) -> ErrorMechanism:
    """Return a mechanism with detector IDs translated by ``offset``.

    Decomposition-hint component detector IDs shift identically so hint
    provenance stays consistent with the merged signature on repeat paths.
    """
    if offset == 0:
        return mechanism
    return ErrorMechanism(
        probability=mechanism.probability,
        detectors=frozenset(d + offset for d in mechanism.detectors),
        observables=mechanism.observables,
        decomposition_hints=tuple(
            (frozenset(d + offset for d in cdets), cobs)
            for cdets, cobs in mechanism.decomposition_hints
        ),
        repeated_targets=tuple(
            _shift_target_label(label, offset) for label in mechanism.repeated_targets
        ),
        component_detector_target_counts=(mechanism.component_detector_target_counts),
    )


def _symbolic_cross_scope_reduction(
    model: ErrorModel,
) -> _CrossScopeReduction | None:
    """Return an exact no-cross-iteration reduction for a narrow repeat shape."""
    if len(model.error_mechanisms) != 1:
        return None
    block = model.error_mechanisms[0]
    if not isinstance(block, RepeatBlock):
        return None
    if block.count == 0:
        return _CrossScopeReduction({}, {})
    if block.detector_offset_per_iteration == 0:
        return None
    if any(not isinstance(item, ErrorMechanism) for item in block.body):
        return None

    body = [item for item in block.body if isinstance(item, ErrorMechanism)]
    if not body:
        return _CrossScopeReduction({}, {})
    for item in body:
        _validate_progression_ids(
            item.detectors,
            block.absolute_start_offset,
            block.detector_offset_per_iteration,
            block.count,
            "absolute detector",
        )
    if block.count <= 1:
        return _reduce_cross_scope_mechanisms(
            _shift_mechanism(item, block.absolute_start_offset) for item in body
        )

    detector_sets = [item.detectors for item in body]
    if any(not detectors for detectors in detector_sets):
        return None
    min_detector = min(min(detectors) for detectors in detector_sets)
    max_detector = max(max(detectors) for detectors in detector_sets)
    body_span = max_detector - min_detector
    stride = abs(block.detector_offset_per_iteration)
    max_delta = min(block.count - 1, body_span // stride)

    # Equality between two finite translated detector sets depends only on the
    # iteration difference. Check every possible difference that can overlap.
    for delta in range(1, max_delta + 1):
        offset = delta * block.detector_offset_per_iteration
        shifted = [_shift_mechanism(item, offset) for item in body]
        for left in body:
            for right in shifted:
                if left.detectors == right.detectors:
                    return None

    reduction = _reduce_cross_scope_mechanisms(
        _shift_mechanism(item, block.absolute_start_offset) for item in body
    )
    return _CrossScopeReduction(
        signature_states=reduction.signature_states,
        conflicts=reduction.conflicts,
        multiplicity=block.count,
    )


def _cross_scope_reduction(model: ErrorModel) -> _CrossScopeReduction:
    """Build or reuse one exact streaming reduction for both cross-scope checks."""
    cached = getattr(model, "_cross_scope_reduction", None)
    if cached is not None:
        return cached

    model._validate_tree()
    reduction = _symbolic_cross_scope_reduction(model)
    if reduction is None:
        reduction = _reduce_cross_scope_mechanisms(model.iter_flattened())
    if hasattr(model, "_cross_scope_reduction"):
        object.__setattr__(model, "_cross_scope_reduction", reduction)
    return reduction


def _iter_repeat_templates(model: ErrorModel) -> tuple[_RepeatTemplate, ...]:
    """Return repeat-body templates without expanding repeat counts.

    Each repeat axis is represented as ``(count, detector_stride)``.  The
    detector IDs of a concrete instance are obtained by adding the template's
    absolute start and one valid multiple of every axis stride.
    """
    cached = getattr(model, "_repeat_templates", None)
    if cached is not None:
        return cached

    model._validate_tree()
    result: list[_RepeatTemplate] = []

    def walk(
        items: (
            tuple[ErrorMechanism | RepeatBlock, ...]
            | list[ErrorMechanism | RepeatBlock]
        ),
        scope_start: int,
        repeat_axes: tuple[tuple[int, int], ...],
    ) -> None:
        for item in items:
            if isinstance(item, ErrorMechanism):
                min_offset = scope_start + sum(
                    min(0, (count - 1) * stride) for count, stride in repeat_axes
                )
                max_offset = scope_start + sum(
                    max(0, (count - 1) * stride) for count, stride in repeat_axes
                )
                _validate_shifted_ids(item.detectors, min_offset, "absolute detector")
                _validate_shifted_ids(item.detectors, max_offset, "absolute detector")
                result.append(_RepeatTemplate(item, scope_start, repeat_axes))
            elif isinstance(item, RepeatBlock):
                if item.count == 0:
                    continue
                walk(
                    item.body,
                    scope_start + item.absolute_start_offset,
                    repeat_axes + ((item.count, item.detector_offset_per_iteration),),
                )

    walk(model.error_mechanisms, 0, ())
    templates = tuple(result)
    if hasattr(model, "_repeat_templates"):
        object.__setattr__(model, "_repeat_templates", templates)
    return templates


def _iter_scope_mechanisms(model: ErrorModel) -> list[_ScopeMechanism]:
    """Return mechanism templates with nested scopes inlined and outer counts intact."""
    model._validate_tree()
    result: list[_ScopeMechanism] = []

    def walk(items, scope_start: int, scope_stride: int, scope_count: int) -> None:
        for item in items:
            if isinstance(item, ErrorMechanism):
                _validate_progression_ids(
                    item.detectors,
                    scope_start,
                    scope_stride,
                    scope_count,
                    "absolute detector",
                )
                result.append(
                    _ScopeMechanism(item, scope_start, scope_stride, scope_count)
                )
            elif isinstance(item, RepeatBlock):
                if item.count == 0:
                    continue
                for k in range(item.count):
                    walk(
                        item.body,
                        scope_start
                        + item.absolute_start_offset
                        + k * item.detector_offset_per_iteration,
                        scope_stride,
                        scope_count,
                    )

    for item in model.error_mechanisms:
        if isinstance(item, ErrorMechanism):
            result.append(_ScopeMechanism(item, 0, 0, 1))
        else:
            if item.count:
                walk(
                    item.body,
                    item.absolute_start_offset,
                    item.detector_offset_per_iteration,
                    item.count,
                )
    return result


def _origin_mechanisms(
    model: ErrorModel,
    signatures: set[tuple[frozenset[int], frozenset[int]]],
) -> dict[
    tuple[frozenset[int], frozenset[int]], list[tuple[ErrorMechanism, tuple[int, ...]]]
]:
    """Index rendered-conflict signatures for concrete failure witnesses.

    The signature filter bounds stored provenance, but traversal still visits
    expanded repeat iterations. This helper is not repeat-count independent;
    a future streaming witness index would be a separate optimization.
    """
    model._validate_tree()
    result: dict[
        tuple[frozenset[int], frozenset[int]],
        list[tuple[ErrorMechanism, tuple[int, ...]]],
    ] = {}

    def walk(items, scope_start: int, path: tuple[int, ...]) -> None:
        for item in items:
            if isinstance(item, ErrorMechanism):
                _validate_shifted_ids(item.detectors, scope_start, "absolute detector")
                if scope_start == 0:
                    witness = item
                else:
                    witness = ErrorMechanism(
                        item.probability,
                        frozenset(d + scope_start for d in item.detectors),
                        item.observables,
                        decomposition_hints=tuple(
                            (
                                frozenset(d + scope_start for d in cdets),
                                cobs,
                            )
                            for cdets, cobs in item.decomposition_hints
                        ),
                        repeated_targets=tuple(
                            _shift_target_label(label, scope_start)
                            for label in item.repeated_targets
                        ),
                        component_detector_target_counts=(
                            item.component_detector_target_counts
                        ),
                    )
                absolute_signature = (witness.detectors, witness.observables)
                if absolute_signature in signatures:
                    result.setdefault(absolute_signature, []).append((witness, path))
            elif isinstance(item, RepeatBlock):
                for k in range(item.count):
                    walk(
                        item.body,
                        scope_start
                        + item.absolute_start_offset
                        + k * item.detector_offset_per_iteration,
                        path + (k,),
                    )

    walk(model.error_mechanisms, 0, ())
    return result


def _template_multiplicity(template: _RepeatTemplate) -> int:
    """Return how many concrete mechanism instances this template represents.

    A repeat-body template is walked once per body position, not once per
    absolute instance (see _iter_repeat_templates). The actual number of
    flattened mechanism instances it stands for is the product of the repeat
    counts of every enclosing axis (1 for a template with no enclosing repeat).
    """
    total = 1
    for count, _stride in template.repeat_axes:
        total *= count
    return total


def _det_label(d: int, coords: dict[int, tuple[float, ...]]) -> str:
    """Format a detector as 'D17@(1,0,2)' when coordinates are available, else 'D17'."""
    c = coords.get(d)
    if c is not None:
        coord_str = ",".join(f"{v:g}" for v in c)
        return f"D{d}@({coord_str})"
    return f"D{d}"


def _xor_fold(probs: list[float]) -> float:
    """XOR-fold a list of probabilities: p1 ⊕ p2 ⊕ … = p1(1-p2) + p2(1-p1) iterated.

    Two independent faults p and q that produce the same (detectors,
    observables) signature are indistinguishable to a decoder and occur
    exclusively-or — exactly one fires — so the fused probability is exclusive
    addition, never plain addition. Derived in Blume-Kohout & Young,
    arXiv:2504.14643 Eq. 22, under the independent-event model class; the same
    derivation shows the fused attenuation a = -ln(1-2p) is just a_p + a_q.

    The identity element is 0.0 (no error), so an empty list returns 0.0.
    """
    if not probs:
        return 0.0
    p = probs[0]
    for q in probs[1:]:
        p = p * (1 - q) + q * (1 - p)
    return p


def _format_mech(mech) -> str:
    """Format a mechanism as 'error(p) D1 D2 L1'."""
    targets = [f"D{d}" for d in sorted(mech.detectors)] + [
        f"L{o}" for o in sorted(mech.observables)
    ]
    suffix = (" " + " ".join(targets)) if targets else ""
    return f"error({mech.probability}){suffix}"


def _has_error_mechanisms(model: ErrorModel) -> bool:
    """Return True when the model declares a mechanism at any nesting depth.

    This is declaration-based, not effect-based: a mechanism whose targets
    cancel under parity folding still counts as declared.

    Walks the repeat tree without expanding it, so a ``REPEAT 1e15`` block is
    inspected once. An empty body, or a body holding only nested empty blocks,
    counts as no mechanism. The tree is validated first, so a malformed model
    raises the same error here as on the flattening path instead of being
    silently reported as vacuous.
    """
    model._validate_tree()

    def walk(items) -> bool:
        for item in items:
            if isinstance(item, ErrorMechanism):
                return True
            if isinstance(item, RepeatBlock) and item.count and walk(item.body):
                return True
        return False

    return walk(model.error_mechanisms)


def _iter_declared_mechanisms(items):
    """Yield each ``ErrorMechanism`` node once, without expanding repeat blocks.

    Inside a repeat body, detector IDs are iteration-relative, which is exactly
    what the instruction text said — the right granularity for a parse-level
    diagnostic.
    """
    for item in items:
        if isinstance(item, ErrorMechanism):
            yield item
        elif isinstance(item, RepeatBlock) and item.count:
            yield from _iter_declared_mechanisms(item.body)


def _repeated_target_failure(
    repeated: list[ErrorMechanism], max_shown: int
) -> PropertyResult:
    """Build the ``duplicates`` failure for instructions that repeat a target."""
    lines = [
        f"error({mech.probability}) repeats {' '.join(mech.repeated_targets)}"
        for mech in repeated[:max_shown]
    ]
    if len(repeated) > max_shown:
        lines.append(f"(and {len(repeated) - max_shown} more)")
    return PropertyResult(
        name="duplicates",
        passed=False,
        severity="warning",
        message=(
            f"Found {len(repeated)} mechanism(s) that repeat a target inside "
            f"one instruction. The parity fold is unambiguous (a repeated "
            f"target cancels), but DEM readers disagree: some cancel, some "
            f"keep a self-loop, and at least one mainstream decoder rejects "
            f"the model. Stim itself folds duplicates before export, so this "
            f"shape comes from another producer or a hand edit."
        ),
        counter_example="\n".join(lines),
        counter_example_data={
            "mechanism_count": len(repeated),
            "mechanisms": [
                f"error({mech.probability}) repeats "
                f"{' '.join(mech.repeated_targets)}"
                for mech in repeated
            ],
        },
        hint=(
            "Re-export the DEM from a producer that XOR-folds repeated "
            "targets, or delete the duplicate target (D0 D0 has no effect)."
        ),
    )


def check_detectability(
    model: ErrorModel, max_shown: int = _MAX_SHOWN
) -> PropertyResult:
    """Verify every error mechanism that flips observables also triggers detectors.

    This check is about *detectability*: a logical error that leaves the syndrome
    trivially empty cannot be detected, and therefore not corrected, by any decoder.
    It does not verify whether the syndrome uniquely identifies which observable
    was flipped; that stronger guarantee is checked by check_correctability.

    Property: ∀m ∈ mechanisms, obs(m) ≠ ∅ → det(m) ≠ ∅

    Note: violating mechanisms have an empty detector set by definition, so
    counter-examples name observables only; coordinate-annotated detector
    labels (as used by sensitivity/duplicates/correctability) do not apply.
    """
    violating_templates = [
        template
        for template in _iter_repeat_templates(model)
        if not template.mechanism.detectors and template.mechanism.observables
    ]

    if violating_templates:
        violations = [
            _shift_mechanism(template.mechanism, template.absolute_start)
            for template in violating_templates
        ]
        total_instances = sum(
            _template_multiplicity(template) for template in violating_templates
        )
        lines = []
        for mech in violations[:max_shown]:
            obs_str = ", ".join(f"L{o}" for o in sorted(mech.observables))
            lines.append(
                f"error({mech.probability}) flips {obs_str} but triggers 0 detectors"
            )
        counter = "; ".join(lines)
        if len(violations) > max_shown:
            counter += f" (and {len(violations) - max_shown} more)"

        return PropertyResult(
            name="detectability",
            passed=False,
            severity="error",
            message=(
                f"Found {total_instances} undetectable error mechanism instance(s) "
                f"across {len(violations)} distinct location(s) that flip observable(s)."
            ),
            counter_example=counter,
            counter_example_data={
                "mechanisms": [_format_mech(m) for m in violations],
                "instance_count": total_instances,
            },
            hint=(
                "Hypothesis: an observable flip with no detector syndrome often "
                "comes from a fault path after the last stabilizer-measurement "
                "round, or from a data-qubit region whose measurement is not "
                "wrapped in a DETECTOR; inspect the circuit region between the "
                "fault location and the observable's final measurement."
            ),
        )

    return PropertyResult(
        name="detectability",
        passed=True,
        severity="error",
        message="All error mechanisms that flip observables also trigger detectors.",
    )


def check_sensitivity(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """Verify every declared detector is triggered by at least one error mechanism.

    A detector that is never triggered by any modelled fault is either wired
    incorrectly or redundant.  It contributes no information to decoding and
    may indicate a missing fault model.

    Limit: a detector whose outcome is constant modulo the reference sample
    (always fires, or never fires) also has no mechanism in the DEM, so this
    predicate cannot distinguish it from a dead detector. That is why the
    finding is a ``warning``, not an ``error``.

    Property: ∀d ∈ D, ∃m ∈ mechanisms, d ∈ det(m)
              equivalently: D ⊆ ⋃_{m} det(m)

    A model with no mechanisms at all is reported as ``skipped``: every
    declared detector is trivially un-triggered, so this predicate cannot
    separate a dead detector from an empty audit. The report layer already
    discloses such a model as vacuous; failing each declared detector here
    would turn a legitimate noiseless artifact (for example an ideal reference
    DEM compiled by clifft or LightStim) into an ``error``-grade report.
    """
    if not _has_error_mechanisms(model):
        return PropertyResult(
            name="sensitivity",
            passed=False,
            severity="warning",
            status="skipped",
            message=(
                "skipped: the DEM declares no error mechanisms, so no detector "
                "can be shown to be dead; the report discloses the model as "
                "vacuous."
            ),
        )

    intervals: dict[tuple[int, int], list[tuple[int, int]]] = {}
    participating: set[int] = set()
    templates = _iter_repeat_templates(model)
    has_nested_repeats = any(len(template.repeat_axes) > 1 for template in templates)

    if has_nested_repeats:
        # The exact progression summary below is for one repeat axis. Keep the
        # existing expansion path for nested scopes until their multi-axis
        # membership proof is implemented.
        scopes = _iter_scope_mechanisms(model)
        for scope in scopes:
            for detector in scope.mechanism.detectors:
                start = detector + scope.absolute_start
                if scope.count == 1 or scope.detector_stride == 0:
                    participating.add(start)
                    continue
                stride = abs(scope.detector_stride)
                residue = start % stride
                end = start + (scope.count - 1) * scope.detector_stride
                lo, hi = sorted((start, end))
                intervals.setdefault((stride, residue), []).append((lo, hi))
    else:
        for template in templates:
            for detector in template.mechanism.detectors:
                start = detector + template.absolute_start
                if not template.repeat_axes:
                    participating.add(start)
                    continue
                count, detector_stride = template.repeat_axes[0]
                if count == 1 or detector_stride == 0:
                    participating.add(start)
                    continue
                stride = abs(detector_stride)
                residue = start % stride
                end = start + (count - 1) * detector_stride
                lo, hi = sorted((start, end))
                intervals.setdefault((stride, residue), []).append((lo, hi))

    merged: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for key, ranges in intervals.items():
        stride, _ = key
        for lo, hi in sorted(ranges):
            if merged.setdefault(key, []) and lo <= merged[key][-1][1] + stride:
                prev_lo, prev_hi = merged[key][-1]
                merged[key][-1] = (prev_lo, max(prev_hi, hi))
            else:
                merged[key].append((lo, hi))

    indexed_ranges: dict[int, dict[int, tuple[list[int], list[tuple[int, int]]]]] = {}
    for (stride, residue), ranges in merged.items():
        indexed_ranges.setdefault(stride, {})[residue] = (
            [lo for lo, _ in ranges],
            ranges,
        )

    def is_participating(detector: int) -> bool:
        if detector in participating:
            return True
        for stride, residue_ranges in indexed_ranges.items():
            residue = detector % stride
            indexed = residue_ranges.get(residue)
            if indexed is None:
                continue
            starts, ranges = indexed
            position = bisect_right(starts, detector) - 1
            if position >= 0 and ranges[position][1] >= detector:
                return True
        return False

    dead = sorted(d for d in model.detectors if not is_participating(d))

    if dead:
        counter = "Detector(s) not triggered by any error mechanism: " + ", ".join(
            _det_label(d, model.detector_coords) for d in dead[:max_shown]
        )
        if len(dead) > max_shown:
            counter += f" (and {len(dead) - max_shown} more)"
        return PropertyResult(
            name="sensitivity",
            passed=False,
            severity="warning",
            message=f"{len(dead)} detector(s) are never triggered by any error mechanism.",
            counter_example=counter,
            counter_example_data={"detectors": dead},
            hint=(
                "Hypothesis: a detector no mechanism ever triggers is either "
                "miswired or redundant. Expected shape: at least one mechanism "
                "per stabilizer check per round; look for a missing noise "
                "instruction on the gates feeding this detector, or a DETECTOR "
                "declared on a comparison that never receives a fault. "
                "Limit: a detector with a constant outcome (fires every shot, "
                "or never fires) also has no mechanism in the DEM, so it is "
                "indistinguishable from a dead detector here; check the "
                "reference sample before treating this as a wiring bug."
            ),
        )

    return PropertyResult(
        name="sensitivity",
        passed=True,
        severity="warning",
        message="All detectors are triggered by at least one error mechanism.",
    )


def check_observable_coverage(
    model: ErrorModel, max_shown: int = _MAX_SHOWN
) -> PropertyResult:
    """Verify every declared logical observable is flipped by at least one error mechanism.

    An observable that never appears in any mechanism is either perfectly protected
    (implausible) or the OBSERVABLE_INCLUDE instruction is not linked to any data qubits.
    In both cases the decoder will always predict the trivial correction for that
    observable, masking real logical errors entirely.

    Property: ∀ℓ ∈ O, ∃m ∈ mechanisms, ℓ ∈ obs(m)
              equivalently: O ⊆ ⋃_{m} obs(m)

    A model with no mechanisms at all is reported as ``skipped`` rather than as
    one ``error`` per declared observable. Noiseless compiles keep their
    observables declared (clifft's ideal reference, LightStim's sequential
    compile), and the report layer already discloses the model as vacuous;
    failing every observable would make a correct control artifact exit 1.
    """
    if not _has_error_mechanisms(model):
        return PropertyResult(
            name="observable_coverage",
            passed=False,
            severity="error",
            status="skipped",
            message=(
                "skipped: the DEM declares no error mechanisms, so no observable "
                "can be shown to be uncovered; the report discloses the model as "
                "vacuous."
            ),
        )

    covered = {
        observable
        for template in _iter_repeat_templates(model)
        for observable in template.mechanism.observables
    }

    uncovered = sorted(model.observables - covered)

    if uncovered:
        counter = "Observable(s) not flipped by any error mechanism: " + ", ".join(
            f"L{o}" for o in uncovered[:max_shown]
        )
        if len(uncovered) > max_shown:
            counter += f" (and {len(uncovered) - max_shown} more)"
        return PropertyResult(
            name="observable_coverage",
            passed=False,
            severity="error",
            message=(
                f"{len(uncovered)} logical observable(s) are never flipped by any "
                f"error mechanism. The decoder will always predict the correct logical "
                f"outcome for these observables, masking real logical errors entirely."
            ),
            counter_example=counter,
            counter_example_data={"observables": uncovered},
        )

    return PropertyResult(
        name="observable_coverage",
        passed=True,
        severity="error",
        message="All declared observables are flipped by at least one error mechanism.",
    )


def _prob_label(p: float) -> tuple[str, str]:
    """Return (summary_tag, counter_example_hint) for an out-of-range probability."""
    if math.isnan(p):
        return "p = NaN", "NaN probability"
    if not math.isfinite(p):
        return "p = ±inf", "infinite probability"
    if p < 0.0:
        return "p < 0", "negative probability"
    if p == 0.0:
        return "p = 0", "zero probability"
    return "p > 0.5", "use complementary probability (p → 1−p)"


# Tags that represent unphysical probabilities; p > 0.5 is merely anomalous.
_UNPHYSICAL_TAGS = {"p = NaN", "p = ±inf", "p < 0", "p = 0"}


def check_probability_bounds(
    model: ErrorModel, max_shown: int = _MAX_SHOWN
) -> PropertyResult:
    """Verify every error mechanism has a finite, strictly positive probability.

    Probabilities above 0.5 are not flagged here; they are handled by the
    separate warning-only check ``high_probability_mechanisms``.

    p = 0 is a no-op that should be pruned from the DEM.
    p < 0, p = NaN or p = ±inf indicates a genuine error upstream. On compiler
    output the culprit is the compiler; on syndrome-learned DEMs these values
    are documented estimator outputs (partial hyperedge subtraction, negative
    moment radicands, vanishing denominators — Takou & Brown,
    arXiv:2510.23797, Eqs. 1, 2, 4), so on such input the finding names an
    estimator bug instead.

    p > 0.5 is anomalous: for a physical single-fault channel the lower-probability
    branch should be used instead (p → 1−p), though valid use-cases such as
    conditioned or adversarial models may legitimately exceed 0.5. The attenuation
    formalism gives a second reason to flag it: a = −ln(1−2p) is undefined at
    p ≥ 0.5, so such a mechanism falls outside the estimable model class of
    Blume-Kohout & Young (arXiv:2504.14643).

    Severity: "error" — every remaining violation is unphysical (NaN, ±inf, ≤ 0).
    Probabilities with 0.5 < p ≤ 1 are not flagged here; they belong to the
    warning-only check ``high_probability_mechanisms``.

    Property: ∀m ∈ mechanisms, 0 < p(m) (finite); p > 0.5 is a separate check.
    """
    violating_templates = [
        template
        for template in _iter_repeat_templates(model)
        if math.isnan(template.mechanism.probability)
        or math.isinf(template.mechanism.probability)
        or template.mechanism.probability <= 0.0
    ]
    if violating_templates:
        violations = [
            _shift_mechanism(template.mechanism, template.absolute_start)
            for template in violating_templates
        ]
        lines: list[str] = []
        tag_counts: Counter[str] = Counter()
        for template, mech in zip(violating_templates, violations):
            p = mech.probability
            tag, hint = _prob_label(p)
            tag_counts[tag] += _template_multiplicity(template)
            if len(lines) < max_shown:
                target_parts = [f"D{d}" for d in sorted(mech.detectors)] + [
                    f"L{o}" for o in sorted(mech.observables)
                ]
                targets = (" " + " ".join(target_parts)) if target_parts else ""
                lines.append(f"error({p}){targets} — {hint}")
        counter = "; ".join(lines)
        if len(violations) > max_shown:
            counter += f" (and {len(violations) - max_shown} more)"
        total_instances = sum(tag_counts.values())
        parts = [f"{n} with {tag}" for tag, n in tag_counts.items()]

        return PropertyResult(
            name="probability_bounds",
            passed=False,
            severity="error",
            message=(
                f"Found {total_instances} error mechanism instance(s) across "
                f"{len(violations)} distinct location(s) with out-of-range "
                f"probability ({', '.join(parts)})."
            ),
            counter_example=counter,
            counter_example_data={
                "mechanisms": [_format_mech(m) for m in violations],
                "instance_count": total_instances,
            },
        )

    return PropertyResult(
        name="probability_bounds",
        passed=True,
        severity="error",
        message="All error mechanism probabilities are finite and strictly positive.",
    )


def check_duplicates(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """Flag error mechanisms that share the same (detectors, observables) signature.

    The property checked is signature injectivity. On multi-round circuit-level
    DEMs this property is routinely violated by *correct* DEMs: distinct
    physical fault locations legitimately share a detector signature.
    Declare ``context={"dem_assembly": "concatenated" | "monolithic"}`` to select the
    message matching what is known about the DEM's origin.

    When entries represent the same fault path, their probabilities should be
    XOR-folded rather than treated as independent entries; the XOR-fold is
    also the correct decoder-facing quantity for a shared signature.

    Caveat: the XOR-fold assumes the entries are independent faults. If one
    coherent fault was split into entries that co-occur in reality (the
    model-class split), the correct fused rate is sin²(θ₁+θ₂) for single-axis
    rotations — about twice the XOR-fold at small angles (Takou & Brown,
    arXiv:2510.23797 §III.1). The reported p_eff is then a lower bound.


    Note on fused probabilities: the XOR-fold of probabilities that are all
    ≤ 0.5 never exceeds 0.5 (f(p,q) = p+q−2pq is maximized at (0.5, 0.5) =
    0.5, preserved under further folds by induction). A duplicate group whose
    fold exceeds 0.5 therefore always contains a probability above 0.5,
    which `probability_bounds` already flags as anomalous — no separate
    severity gate is needed here.

    Note on decomposed mechanisms: for ``^``-separated error instructions the
    signature compared here is the union over decomposition components (the
    decoder-facing view), not the raw XOR-folded target list, so that distinct
    decompositions do not collide with unrelated mechanisms.

    Property: ∀m, m' ∈ mechanisms, m ≠ m' → (det(m), obs(m)) ≠ (det(m'), obs(m'))
              i.e., the signature map m ↦ (det(m), obs(m)) is injective.
    """
    repeated = [
        mechanism
        for mechanism in _iter_declared_mechanisms(model.error_mechanisms)
        if mechanism.repeated_targets
    ]
    reduction = _cross_scope_reduction(model)
    duplicates = {
        signature: state[2]
        for signature, state in reduction.signature_states.items()
        if state[0] > 1 and state[2] is not None
    }
    if not duplicates:
        if repeated:
            return _repeated_target_failure(repeated, max_shown)
        return PropertyResult(
            name="duplicates",
            passed=True,
            severity="warning",
            message="No duplicate mechanism signatures found.",
        )
    decomps = _decompositions_per_signature(model)
    # Injectivity is violated if two distinct mechanisms share the same signature.
    # One line per duplicate group; coordinates are kept in counter_example_data.
    lines = []
    groups: list[dict[str, Any]] = []
    mixed_groups = 0
    for (dets, obs), probs in duplicates.items():
        full_targets = [f"D{d}" for d in sorted(dets)] + [f"L{o}" for o in sorted(obs)]
        coords = {
            _det_label(d, model.detector_coords)
            for d in sorted(dets)
            if d in model.detector_coords
        }
        p_fused = _xor_fold(probs)
        structures = sorted(decomps.get((dets, obs), {("plain",)}))
        is_mixed = len(structures) > 1
        if is_mixed:
            mixed_groups += 1
        groups.append(
            {
                "signature": full_targets or ["(no detectors)"],
                "detector_coordinates": sorted(coords),
                "probabilities": list(probs),
                "p_fused": p_fused,
                "decompositions": structures,
            }
        )
        shown = full_targets[:3]
        if len(full_targets) > 3:
            shown = [
                *shown,
                f"...(+{len(full_targets) - len(shown)} more)",
            ]
        sig = " ".join(shown) or "(no detectors)"
        prob_list = ", ".join(f"{p:.6g}" for p in probs)
        mixed_tag = " [mixed decomposition]" if is_mixed else ""
        lines.append(
            f"signature {sig}{mixed_tag}: p = {{{prob_list}}} -> p_eff = {p_fused:.6g}"
        )
    counter = "\n".join(lines[:max_shown])
    if len(duplicates) > max_shown:
        counter += f"\n(and {len(duplicates) - max_shown} more)"
    if repeated:
        repeated_lines = [
            f"error({mech.probability}) repeats {' '.join(mech.repeated_targets)}"
            for mech in repeated[:max_shown]
        ]
        if len(repeated) > max_shown:
            repeated_lines.append(f"(and {len(repeated) - max_shown} more)")
        counter += "\n" + "\n".join(repeated_lines)
    all_dup_mechs: list[str] = []
    for (dets, obs), probs in duplicates.items():
        tgt = " ".join([f"D{d}" for d in sorted(dets)] + [f"L{o}" for o in sorted(obs)])
        tgt_str = f" {tgt}" if tgt else ""
        for p in probs:
            all_dup_mechs.append(f"error({p}){tgt_str}")
    total_duplicate_signatures = len(duplicates) * reduction.multiplicity
    mixed_clause = ""
    if mixed_groups:
        mixed_clause = (
            f" {mixed_groups} of {len(duplicates)} group(s) are mixed "
            f"(mechanisms with different decomposition structures share only "
            f"the merged signature — distinct fault paths, not true duplicates)."
        )
    repeat_clause = ""
    if repeated:
        repeat_clause = (
            f" Additionally, {len(repeated)} mechanism(s) repeat a target "
            f"inside one instruction; the parity fold cancels the repetition, "
            f"but not every DEM reader agrees on that reading."
        )
    result = PropertyResult(
        name="duplicates",
        passed=False,
        severity="warning",
        message=(
            f"Found {total_duplicate_signatures} duplicate mechanism signature(s) "
            f"across {len(duplicates)} distinct location(s). Distinct fault "
            f"paths can legitimately share a (detector, observable) signature "
            f"on multi-round circuit-level DEMs (signature collision); if this "
            f"DEM was assembled by concatenating sub-circuit DEMs, the same "
            f"fault path may instead be double-counted. The decoder-facing "
            f"probability for a shared signature is the XOR-folded value "
            f"p_eff = p1*(1-p2) + p2*(1-p1) (iterated for 3+), shown per "
            f"group in the counter-example." + mixed_clause + repeat_clause
        ),
        counter_example=counter,
        counter_example_data={
            "mechanisms": all_dup_mechs,
            "signature_count": total_duplicate_signatures,
            "location_count": len(duplicates),
            "mixed_group_count": mixed_groups,
            "repeated_target_mechanisms": [
                f"error({mech.probability}) repeats "
                f"{' '.join(mech.repeated_targets)}"
                for mech in repeated
            ],
            "groups": groups,
        },
        hint=(
            "Hypothesis: mechanisms sharing a full signature in the same "
            "spatial boundary region suggest sub-circuit DEMs concatenated "
            "without XOR-merging; the correct probability is the XOR-fused "
            "value shown in the counter-example. On decompose_errors=True "
            "output, an undecomposed and a ^-decomposed instruction can also "
            "legitimately share a merged signature; groups marked "
            "'[mixed decomposition]' are distinct fault paths that collide "
            "only at the merged-signature granularity and are not true "
            "duplicates."
        ),
    )
    return result


_DUPLICATES_CLAIMS: dict[str | None, str] = {
    "monolithic": (
        "Signature collision on a monolithic DEM: expected on multi-round "
        "circuit-level DEMs and usually benign."
    ),
    "concatenated": (
        "The same fault path appears more than once in the DEM, which "
        "typically happens when sub-circuit DEMs are concatenated without "
        "merging coincident mechanisms."
    ),
}


def apply_duplicates_dem_assembly(
    result: PropertyResult, dem_assembly: bool | str | None
) -> None:
    """Rewrite a failed `duplicates` verdict per the dem_assembly context gate.

    For ``concatenated`` the message selects the double-counting claim and the
    XOR-fold instruction; the hint from ``check_duplicates`` (concatenation
    hypothesis) already matches and is left unchanged. For ``monolithic`` the
    message states the benign signature-collision claim *without* the XOR-fold
    imperative, and the hint is rewritten to a consistent monolithic
    hypothesis — the default hint would otherwise still assert concatenation
    next to a "usually benign" message.

    No-op for passing results, non-verdicts, or undeclared/unknown values.
    """
    if dem_assembly not in _DUPLICATES_CLAIMS or result.passed:
        return
    if result.name != "duplicates" or result.status != "verdict":
        return
    data = result.counter_example_data or {}
    total = data.get("signature_count")
    locations = data.get("location_count")
    if total is None or locations is None:
        return
    result.message = (
        f"Found {total} duplicate mechanism signature(s) across "
        f"{locations} distinct location(s). {_DUPLICATES_CLAIMS[dem_assembly]} "
    )
    if dem_assembly == "monolithic":
        result.hint = (
            "Hypothesis: distinct fault paths legitimately share this "
            "signature on a declared monolithic DEM; confirm no assembly "
            "step duplicated a mechanism, then treat this finding as "
            "informational."
        )
    else:
        result.message += (
            f"Duplicate probabilities should be XOR-folded as "
            f"p_eff = p1*(1-p2) + p2*(1-p1) (iterated for 3+), not left as "
            f"separate entries."
        )


def check_correctability(
    model: ErrorModel, max_shown: int = _MAX_SHOWN
) -> PropertyResult:
    """Verify that every detector syndrome maps to at most one observable set.

    A decoder that receives a syndrome must infer a unique logical correction.
    If two mechanisms produce the same syndrome yet flip *different* sets of
    observables, any decoder may be forced to guess between them. This is a
    warning because valid degenerate codes and decomposed DEMs can legitimately
    contain such mappings.

    Property: ∀m, m' ∈ mechanisms, det(m) = det(m') → obs(m) = obs(m')
              equivalently: the map det(m) ↦ obs(m) is well-defined (functional)
              on the image of the syndrome map.

    Relationship to check_duplicates: mechanisms that share a full
    (detectors, observables) signature — i.e. duplicates — contribute only one
    observable set to a syndrome and are therefore not flagged here. Use
    check_duplicates to detect them.

    Scope: this check examines each mechanism independently. It does not detect
    cases where two mechanisms, when they co-occur, produce a combined syndrome
    that maps to conflicting observable corrections — that is the code distance
    problem and is in general NP-hard to verify.

    Scope: this check establishes that the syndrome-to-observable map is functional
    over the mechanisms listed in the DEM. It does not establish that those
    mechanisms span the physical process. If a single physical fault has been split
    into independent DEM entries that in reality co-occur, the conflict it creates
    is absent from the DEM and from this check.

    Note on decomposed mechanisms: syndromes are compared using the union over
    ``^``-decomposition components (the decoder-facing view), not the raw
    XOR-folded target list, matching how sinter/pymatching consume components.
    """
    reduction = _cross_scope_reduction(model)
    conflicts = reduction.conflicts
    # A conflict occurs when a syndrome (detector set) maps to more than one distinct observable set,
    # i.e. there exist at least two mechanisms m and m' such that det(m) = det(m') but obs(m) ≠ obs(m').
    if conflicts:
        shown_conflicts = list(conflicts.items())[:max_shown]
        signatures = {
            (dets, obs) for dets, obs_set in shown_conflicts for obs in obs_set
        }
        origins = _origin_mechanisms(model, signatures)
        lines = []
        for dets, obs_set in shown_conflicts:
            det_str = (
                " ".join(_det_label(d, model.detector_coords) for d in sorted(dets))
                if dets
                else "(no detectors)"
            )

            obs_variants = ", ".join(
                "{" + " ".join(f"L{o}" for o in sorted(obs)) + "}"
                for obs in sorted(obs_set, key=lambda s: sorted(s))
            )
            witness_text = ", ".join(
                f"{_format_mech(mech)} (iteration {path or (0,)})"
                for obs in sorted(obs_set, key=lambda s: sorted(s))
                for mech, path in origins.get((dets, obs), [])
            )
            lines.append(
                f"syndrome {{{det_str}}} maps to observable sets {obs_variants}"
                + (f"; witnesses: {witness_text}" if witness_text else "")
            )
        counter = "; ".join(lines)
        if len(conflicts) > max_shown:
            counter += f" (and {len(conflicts) - max_shown} more)"
        conflicts_list = []
        for dets, obs_set in shown_conflicts:
            witnesses = [
                {
                    "mechanism": _format_mech(mech),
                    "iteration": list(path),
                }
                for obs in sorted(obs_set, key=lambda s: sorted(s))
                for mech, path in origins.get((dets, obs), [])
            ]
            conflicts_list.append(
                {
                    "syndrome": sorted(dets),
                    "observable_sets": [
                        sorted(obs) for obs in sorted(obs_set, key=lambda s: sorted(s))
                    ],
                    "witnesses": witnesses,
                }
            )
        total_conflicts = len(conflicts) * reduction.multiplicity
        return PropertyResult(
            name="correctability",
            passed=False,
            severity="warning",
            message=(
                f"Found {total_conflicts} syndrome(s) across {len(conflicts)} "
                f"distinct location(s) that map to more than one distinct "
                f"observable set. The decoder cannot determine which logical observable "
                f"was flipped from the measurement outcome alone."
            ),
            counter_example=counter,
            counter_example_data={
                "conflicts": conflicts_list,
                "total_conflicts": total_conflicts,
                "witnesses_truncated": len(conflicts) > max_shown,
            },
            hint=(
                "Hypothesis: spatially distant conflicting mechanisms suggest "
                "genuine code-distance collapse; co-located ones suggest a "
                "degenerate code family or a decompose_errors=True artefact. "
                "Compare the conflicting witnesses' detector coordinates (from "
                "counter_example_data) before treating this as a code bug."
            ),
        )

    return PropertyResult(
        name="correctability",
        passed=True,
        severity="warning",
        message="Every syndrome maps to at most one distinct set of logical observables.",
    )


def check_null_mechanism(
    model: ErrorModel, max_shown: int = _MAX_SHOWN
) -> PropertyResult:
    """Flag error mechanisms that trigger no detector and flip no observable.

    Such a mechanism is a provable no-op: it contributes nothing to the
    syndrome ``sigma = H * e`` and nothing to the observable flip
    ``ell = L * e`` for any error vector ``e``, so no decoder can observe it and
    no correction can depend on it. Stim's circuit-to-DEM generator never emits
    one, but stim's parser and ``.flattened()`` preserve a hand-written
    targetless ``error(p)``, and such a line passes every production check
    silently.

    **Severity boundary (binding).** The predicate is *empty support on both
    sides*, never even detector weight. A mechanism flipping detectors
    ``{d1, d2}`` does flip two syndrome bits; the claim that even detector
    support "has no effect" is a statement about a decoder family's pairing
    behaviour, not a property of the DEM. ``warning`` rather than ``error``
    because a hand-written DEM may carry an intentional no-op line.

    **Shift-invariance (why the check is template-local).** The predicate reads
    only whether a mechanism's detector and observable support are *empty*, and
    both are invariant under the detector-ID shift a repeat applies: shifting an
    empty detector set keeps it empty, and observable IDs are never shifted.
    Repetition therefore cannot create a violation that the template does not
    already carry, so the check evaluates one template per mechanism position
    and reports the instance count separately instead of expanding the repeat
    body. This is the same argument that licenses ``detectability``'s
    template-local path.

    Property: no mechanism m satisfies det(m) = ∅ and obs(m) = ∅
    """
    violating_templates = [
        template
        for template in _iter_repeat_templates(model)
        if not template.mechanism.detectors and not template.mechanism.observables
    ]

    if violating_templates:
        violations = [
            _shift_mechanism(template.mechanism, template.absolute_start)
            for template in violating_templates
        ]
        total_instances = sum(
            _template_multiplicity(template) for template in violating_templates
        )
        lines = [_format_mech(mech) for mech in violations[:max_shown]]
        counter = "; ".join(lines)
        if len(violations) > max_shown:
            counter += f" (and {len(violations) - max_shown} more)"
        return PropertyResult(
            name="null_mechanism",
            passed=False,
            severity="warning",
            message=(
                f"Found {total_instances} null error mechanism instance(s) across "
                f"{len(violations)} distinct location(s) that trigger no detector "
                "and flip no observable. These are provable no-ops: they cannot "
                "appear in any syndrome or observable flip, so no decoder can "
                "observe them."
            ),
            counter_example=counter,
            counter_example_data={
                "mechanisms": [_format_mech(mech) for mech in violations],
                "instance_count": total_instances,
            },
        )

    return PropertyResult(
        name="null_mechanism",
        passed=True,
        severity="warning",
        message="No mechanism has empty detector and observable support.",
    )


def _add_edge(graph, left, right) -> None:
    """Add an undirected unweighted edge to an adjacency-set graph."""
    graph.setdefault(left, set()).add(right)
    graph.setdefault(right, set()).add(left)


def _connected_components(graph) -> list[set]:
    """Return connected components using iterative depth-first search."""
    components = []
    unseen = set(graph)
    while unseen:
        start = unseen.pop()
        component = {start}
        stack = [start]
        while stack:
            node = stack.pop()
            for neighbour in graph[node]:
                if neighbour in unseen:
                    unseen.remove(neighbour)
                    component.add(neighbour)
                    stack.append(neighbour)
        components.append(component)
    return components


def _shortest_weighted_path(graph, start, goal) -> tuple[float, list] | None:
    """Return (length, node_path) of the shortest weighted path, or None.

    Dijkstra with predecessor tracking. The returned path is the node sequence
    from ``start`` to ``goal``; callers map consecutive node pairs back to the
    mechanisms that produced the edges.
    """
    distances = {start: 0.0}
    previous: dict = {}
    sequence = itertools.count()
    queue = [(0.0, next(sequence), start)]
    while queue:
        distance, _, node = heapq.heappop(queue)
        if distance != distances.get(node):
            continue
        if node == goal:
            path = [goal]
            while path[-1] != start:
                path.append(previous[path[-1]])
            path.reverse()
            return distance, path
        for neighbour, weight in graph.get(node, {}).items():
            candidate = distance + weight
            if candidate < distances.get(neighbour, float("inf")):
                distances[neighbour] = candidate
                previous[neighbour] = node
                heapq.heappush(queue, (candidate, next(sequence), neighbour))
    return None


def _add_weighted_edge(graph, left, right, weight: float) -> None:
    """Add an undirected weighted edge, matching NetworkX Graph semantics."""
    graph.setdefault(left, {})[right] = weight
    graph.setdefault(right, {})[left] = weight


def _observable_distances(model) -> dict[int, int | None]:
    r"""Return {obs: distance_lower_bound} for every declared observable.

    Algorithm — doubled-graph BFS (parity trick):
        For observable L, the code distance is the minimum weight set of errors
        whose syndromes cancel (form a logical operator). This equals the
        shortest path in a "doubled" Tanner graph where each detector node d
        is split into two copies (d, 0) and (d, 1) representing the two parities
        of that syndrome node w.r.t. L. An error mechanism that flips L connects
        opposite-parity copies of its detector nodes; one that does not flips L
        connects same-parity copies. The boundary injects (boundary, 0)→(boundary, 1).
        A path from (boundary, 0) to (boundary, 1) of length k corresponds to a
        weight-k logical operator, so BFS gives the distance.

    Exact for graphable DEMs (weight ≤ 2). For hyperedges (weight > 2), uses
    star expansion (an auxiliary hub node added per mechanism), giving a
    lower bound rounded to the nearest integer fault count.

    Alternative approach (not implemented): arXiv 2603.20127 uses a constrained
    polynomial optimisation kernel over the same error-path space, which could
    replace or complement BFS for hyperedge-heavy DEMs where star expansion
    introduces approximation error.  A second alternative is weighted BFS with
    edge weights $-\log p_j$, which recovers the most-probable-error distance
    (the standard generalisation when mechanisms have varying probabilities,
    defined as $\operatorname{arg\,min}_{e \in \mathcal{B}} \sum_j e_j (-\log p_j)$
    where $\mathcal{B} = \{e \in \mathbb{F}_2^m \mid e \in \ker H, e \notin \ker L\}$).
    Unweighted BFS (this implementation) is the special case $p_j = \text{const}$.
    introduces approximation error. Worth revisiting when adding exact hyperedge
    distance support.

    Returns 0 for observables with a completeness violation (0-detector mechanism
    that flips the observable). Returns None if the observable is unreachable
    in the doubled graph (observable_coverage will catch this separately).
    """
    _BOUNDARY = "__boundary__"

    # Detect completeness violations up front.
    zero_det_obs: set[int] = set()
    for mech in model.flattened():
        if len(mech.detectors) == 0 and len(mech.observables) > 0:
            zero_det_obs.update(mech.observables)

    distances: dict[int, int | None] = {}
    for obs in sorted(model.observables):
        if obs in zero_det_obs:
            distances[obs] = 0
            continue

        g: dict[object, dict[object, float]] = {}
        for d in model.detectors:
            g.setdefault((d, 0), {})
            g.setdefault((d, 1), {})
        g.setdefault((_BOUNDARY, 0), {})
        g.setdefault((_BOUNDARY, 1), {})

        for idx, mech in enumerate(model.flattened()):
            flips = obs in mech.observables
            dets = sorted(mech.detectors)

            if len(dets) == 0:
                continue

            if len(dets) == 1:
                a = dets[0]
                p0, p1 = (0, 1) if flips else (0, 0)
                _add_weighted_edge(g, (a, p0), (_BOUNDARY, p1), 1.0)
                p0, p1 = (1, 0) if flips else (1, 1)
                _add_weighted_edge(g, (a, p0), (_BOUNDARY, p1), 1.0)

            elif len(dets) == 2:
                a, b = dets[0], dets[1]
                p_b0 = 1 if flips else 0
                _add_weighted_edge(g, (a, 0), (b, p_b0), 1.0)
                _add_weighted_edge(g, (a, 1), (b, 1 - p_b0), 1.0)

            else:
                # Hyperedge: star expansion through a virtual center node.
                center0 = (f"_hub_{idx}", 0)
                center1 = (f"_hub_{idx}", 1)
                g.setdefault(center0, {})
                g.setdefault(center1, {})
                for d in dets:
                    _add_weighted_edge(g, (d, 0), center0, 0.5)
                    _add_weighted_edge(g, (d, 1), center1, 0.5)
                if flips:
                    _add_weighted_edge(g, (_BOUNDARY, 0), center1, 0.5)
                    _add_weighted_edge(g, (_BOUNDARY, 1), center0, 0.5)
                else:
                    _add_weighted_edge(g, (_BOUNDARY, 0), center0, 0.5)
                    _add_weighted_edge(g, (_BOUNDARY, 1), center1, 0.5)

        found = _shortest_weighted_path(g, (_BOUNDARY, 0), (_BOUNDARY, 1))
        distances[obs] = round(found[0]) if found is not None else None

    return distances


def check_boundary_symmetry(
    model: ErrorModel, max_imbalance: int = 0
) -> PropertyResult:
    """Check that per-observable distances are balanced (P6, Boundary Symmetry).

    In CSS codes, X- and Z-type distances can differ. A large spread (max − min > delta)
    indicates the code wastes resources protecting one error type while being exposed to
    another. For symmetric constructions (toric, bicycle), all per-observable distances
    should be equal.

    max_imbalance: maximum allowed difference between the largest and smallest
    per-observable distance lower bound. Default 0 requires exact equality. Set to 1
    when using hyperedge DEMs to absorb rounding from star expansion.

    Requires ≥ 2 logical observables; skipped (pass) otherwise.

    Property: max(per-observable distance) - min(per-observable distance) <= max_imbalance.
    """
    if len(model.observables) < 2:
        return PropertyResult(
            name="boundary_symmetry",
            passed=True,
            severity="warning",
            message=(
                "Skipped: fewer than 2 logical observables "
                "(boundary symmetry requires ≥ 2)."
            ),
        )

    obs_dists = _observable_distances(model)
    reachable = {obs: d for obs, d in obs_dists.items() if d is not None}

    if not reachable:
        return PropertyResult(
            name="boundary_symmetry",
            passed=True,
            severity="warning",
            message="Could not determine per-observable distances.",
        )

    max_d = max(reachable.values())
    min_d = min(reachable.values())
    imbalance = max_d - min_d
    dist_str = ", ".join(f"L{obs}={d}" for obs, d in sorted(reachable.items()))

    if imbalance > max_imbalance:
        worst_low = min(obs for obs, d in reachable.items() if d == min_d)
        worst_high = max(obs for obs, d in reachable.items() if d == max_d)
        return PropertyResult(
            name="boundary_symmetry",
            passed=False,
            severity="warning",
            message=(
                f"Observable distances are imbalanced ({dist_str}). "
                f"Resources are wasted protecting the long direction while the short "
                f"direction is exposed. Spread {imbalance} exceeds threshold {max_imbalance}."
            ),
            counter_example=(
                f"L{worst_high} distance {max_d} vs L{worst_low} distance {min_d}."
            ),
            counter_example_data={
                "distances": {obs: d for obs, d in sorted(reachable.items())},
                "imbalance": imbalance,
                "max_imbalance": max_imbalance,
            },
        )

    return PropertyResult(
        name="boundary_symmetry",
        passed=True,
        severity="warning",
        message=f"Observable distances are balanced: {dist_str}.",
    )


def check_connectivity(
    model: ErrorModel, single_decoding_graph: bool | None = None
) -> PropertyResult:
    """Verify the decoding graph forms a single connected component.

    Each logical observable gets its own boundary node (boundary_L0, boundary_L1, …)
    so that weight-1 mechanisms from spatially separate regions are not falsely merged
    through a single shared boundary node.  If the model declares no observables, a
    single generic boundary node is used.

    Global check (v0.3): connectivity is a global topological property of the
    assembled decoding graph.  It cannot be reduced to a per-mechanism predicate.
    Per the composition taxonomy (Theorem 4, MV-blindness), no local predicate
    certifies distance preservation for identifying compositions, so connectivity
    is verified globally rather than compositionally via a Frame Rule.

    Connectivity is only a correctness invariant when the DEM is a single decoding graph. The
    severity therefore depends on the declared context:

    - ``single_decoding_graph=True`` (a declared single-decoding-graph profile):
      a disconnected graph is a genuine defect -> ``error``.
    - ``single_decoding_graph=None`` (no assumption declared): a disconnected
      graph is a ``warning`` — the DEM may legitimately be a decomposed or
      multi-component model, so no fail can be certified.
    - ``single_decoding_graph=False`` (explicitly decomposed/multi-component):
      connectivity is not meaningful -> explicit ``skipped``, never a verdict.

    Property: the detector-mechanism Tanner graph has exactly one connected component.
    """
    g: dict[object, set] = {}
    for d in model.detectors:
        g.setdefault(d, set())

    # One boundary node per declared observable; fall back to a single node when
    # there are no observables (pure-detector DEMs used in some test contexts).
    # A separate boundary_noobs node handles weight-1 mechanisms that flip no observable,
    # preventing them from being arbitrarily merged with observable-specific boundaries.
    # Boundary nodes are added lazily (via _add_edge) only when a weight-1 mechanism
    # actually touches them, so unused/isolated boundary nodes do not create
    # spurious connected components on mechanism-free or multi-detector-only DEMs.
    if model.observables:
        boundary_nodes = {obs: f"boundary_L{obs}" for obs in model.observables}
    else:
        boundary_nodes = {}

    for mech in model.flattened():
        dets = sorted(mech.detectors)
        if len(dets) == 0:
            pass  # handled by completeness
        elif len(dets) == 1:
            # Connect to the boundary node of each declared observable this mechanism
            # touches; skip any observable not present in boundary_nodes (undeclared).
            # If it touches no declared observable, connect to the neutral noobs boundary.
            if mech.observables and boundary_nodes:
                known_obs = [obs for obs in mech.observables if obs in boundary_nodes]
                if known_obs:
                    for obs in known_obs:
                        _add_edge(g, dets[0], boundary_nodes[obs])
                else:
                    _add_edge(g, dets[0], "boundary_noobs")
            elif boundary_nodes:
                _add_edge(g, dets[0], "boundary_noobs")
            else:
                _add_edge(g, dets[0], "boundary")
        else:
            for i in range(len(dets)):
                for j in range(i + 1, len(dets)):
                    _add_edge(g, dets[i], dets[j])

    boundary_set = set(boundary_nodes.values()) | {"boundary", "boundary_noobs"}
    components = _connected_components(g)
    if len(components) > 1:
        det_components = [
            sorted(c for c in comp if c not in boundary_set) for comp in components
        ]
        parts = "; ".join(
            f"Component {i + 1}: {comp}" for i, comp in enumerate(det_components)
        )
        if single_decoding_graph is False:
            # Explicitly decomposed/multi-component model: connectivity is not
            # meaningful, so report an explicit skip rather than a verdict.
            return PropertyResult(
                name="connectivity",
                passed=False,
                severity="warning",
                status="skipped",
                message=(
                    "skipped: the DEM is explicitly decomposed/multi-component, "
                    "so single-graph connectivity is not a meaningful invariant."
                ),
            )
        severity = "error" if single_decoding_graph else "warning"
        return PropertyResult(
            name="connectivity",
            passed=False,
            severity=severity,
            message=f"Decoding graph has {len(components)} connected components.",
            counter_example=parts,
            counter_example_data={"components": det_components},
        )

    return PropertyResult(
        name="connectivity",
        passed=True,
        severity="error" if single_decoding_graph else "warning",
        message="Decoding graph is fully connected.",
    )


# Check Registry
def check_high_probability_mechanisms(
    model: ErrorModel, threshold: float = 0.3
) -> PropertyResult:
    """Verify no error mechanism has probability above the configured threshold.

    High-probability mechanisms (p > threshold, default 0.3) on a low-noise
    device are a strong signal of a probability-accumulation bug: naive addition
    instead of XOR convolution when composing sub-circuit DEMs.
    `probability_bounds` catches the extreme case (p > 0.5); this check catches
    the intermediate range that is numerically valid yet suspicious.

    A rate outlier is not always accumulation: coherent interference can
    legitimately double a mechanism's rate (e.g. boundary edges of rotated
    surface codes, sin²(2θ) vs. the independent-combination value — Takou &
    Brown arXiv:2510.23797 §III.1). The absolute threshold is far above such
    doubling at physical angles; a relative-rate variant of this check would
    false-flag coherent DEMs and is rejected (notes/NEGATIVE_RESULTS.md,
    2026-10-06).

    Adjust threshold upward (e.g. 0.4) for intentionally high-noise test DEMs.

    Property: ∀m ∈ mechanisms, p(m) ≤ threshold
    (threshold defaults to 0.3; mechanisms at or below the threshold pass)
    """
    violating_templates = [
        template
        for template in _iter_repeat_templates(model)
        if template.mechanism.probability > threshold
    ]

    if violating_templates:
        violations = [
            _shift_mechanism(template.mechanism, template.absolute_start)
            for template in violating_templates
        ]
        offenders_sorted = sorted(violations, key=lambda m: m.probability, reverse=True)
        worst = offenders_sorted[0]
        targets = " ".join(f"D{d}" for d in sorted(worst.detectors))
        obs_str = (
            (" " + " ".join(f"L{o}" for o in sorted(worst.observables)))
            if worst.observables
            else ""
        )
        counter = (
            f"error({worst.probability}) {targets}{obs_str} "
            f"— highest probability mechanism (threshold: {threshold})"
        )
        total_instances = sum(_template_multiplicity(t) for t in violating_templates)
        return PropertyResult(
            name="high_probability_mechanisms",
            passed=False,
            severity="warning",
            message=(
                f"Found {total_instances} mechanism instance(s) across "
                f"{len(violations)} distinct location(s) with probability > {threshold}. "
                f"On a low-noise device this is unexpected and may indicate that "
                f"probabilities were summed (p1 + p2) instead of correctly combined "
                f"(p1 + p2 - 2*p1*p2) when merging sub-circuit DEMs. Consider "
                f"reviewing DEM generation code or passing a higher threshold to "
                f"check_high_probability_mechanisms if high noise is intentional."
            ),
            counter_example=counter,
            counter_example_data={
                "mechanisms": [_format_mech(m) for m in violations],
                "instance_count": total_instances,
            },
        )

    return PropertyResult(
        name="high_probability_mechanisms",
        passed=True,
        severity="warning",
        message=f"All mechanism probabilities are ≤ {threshold}.",
    )


LOCAL_CHECKS: dict[str, CheckFn] = {
    "detectability": check_detectability,
    "sensitivity": check_sensitivity,
    "observable_coverage": check_observable_coverage,
    "probability_bounds": check_probability_bounds,
    "duplicates": check_duplicates,
    "correctability": check_correctability,
    "null_mechanism": check_null_mechanism,
    "high_probability_mechanisms": check_high_probability_mechanisms,
}

# Global checks: topological properties of the assembled decoding graph. These
# require the full mechanism set and cannot be reduced to per-mechanism tests.
GLOBAL_CHECKS: dict[str, CheckFn] = {
    "connectivity": check_connectivity,
    "boundary_symmetry": check_boundary_symmetry,
}

# ALL_CHECKS is the public registry used by emlint.check() and the CLI; it is
# the union of the local and global check families.
ALL_CHECKS = {**LOCAL_CHECKS, **GLOBAL_CHECKS}
