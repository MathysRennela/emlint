""" "
Property checks for detector error models.

All checks must be pure functions that take an ErrorModel and return a PropertyResult.
They should not raise exceptions.
Any internal errors should be caught and reported as failed checks with appropriate severity and messaging.
They must include counter_example and counter_example_data when passed=False.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

from emlint.model import (
    ErrorMechanism,
    ErrorModel,
    RepeatBlock,
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

    Property: ∀d ∈ D, ∃m ∈ mechanisms, d ∈ det(m)
              equivalently: D ⊆ ⋃_{m} det(m)
    """
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
                "declared on a comparison that never receives a fault."
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
    """
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
    """Verify every error mechanism has a probability in (0, 0.5].

    p = 0 is a no-op that should be pruned from the DEM.
    p < 0, p = NaN or p = ±inf indicates a genuine (compiler) error.
    p > 0.5 is anomalous: for a physical single-fault channel the lower-probability
    branch should be used instead (p → 1−p), though valid use-cases such as
    conditioned or adversarial models may legitimately exceed 0.5.

    Severity: "error" when any probability is unphysical (NaN, ±inf, ≤ 0);
              "warning" when all violations are merely p > 0.5.

    Property: ∀m ∈ mechanisms, 0 < p(m) ≤ 0.5  (and p(m) ∉ {NaN, −∞, +∞})
    """
    violating_templates = [
        template
        for template in _iter_repeat_templates(model)
        if math.isnan(template.mechanism.probability)
        or not (0.0 < template.mechanism.probability <= 0.5)
    ]
    if violating_templates:
        violations = [
            _shift_mechanism(template.mechanism, template.absolute_start)
            for template in violating_templates
        ]
        lines: list[str] = []
        tag_counts: Counter[str] = Counter()
        has_unphysical = False
        for template, mech in zip(violating_templates, violations):
            p = mech.probability
            tag, hint = _prob_label(p)
            tag_counts[tag] += _template_multiplicity(template)
            if tag in _UNPHYSICAL_TAGS:
                has_unphysical = True
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
            severity="error" if has_unphysical else "warning",
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
        message="All error mechanism probabilities are in (0, 0.5].",
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
    reduction = _cross_scope_reduction(model)
    duplicates = {
        signature: state[2]
        for signature, state in reduction.signature_states.items()
        if state[0] > 1 and state[2] is not None
    }
    if not duplicates:
        return PropertyResult(
            name="duplicates",
            passed=True,
            severity="warning",
            message="No duplicate mechanism signatures found.",
        )
    # Injectivity is violated if two distinct mechanisms share the same signature.
    lines = []
    for (dets, obs), probs in list(duplicates.items())[:max_shown]:
        targets = (
            " ".join(_det_label(d, model.detector_coords) for d in sorted(dets))
            or "(no detectors)"
        )
        obs_str = (" " + " ".join(f"L{o}" for o in sorted(obs))) if obs else ""
        p_fused = _xor_fold(probs)
        prob_list = ", ".join(str(p) for p in probs)
        lines.append(
            f"error({prob_list}) share signature {targets}{obs_str}; "
            f"XOR-fused probability is {p_fused:.6g}"
        )
    counter = "; ".join(lines)
    if len(duplicates) > max_shown:
        counter += f" (and {len(duplicates) - max_shown} more)"
    all_dup_mechs: list[str] = []
    for (dets, obs), probs in duplicates.items():
        tgt = " ".join([f"D{d}" for d in sorted(dets)] + [f"L{o}" for o in sorted(obs)])
        tgt_str = f" {tgt}" if tgt else ""
        for p in probs:
            all_dup_mechs.append(f"error({p}){tgt_str}")
    total_duplicate_signatures = len(duplicates) * reduction.multiplicity
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
            f"group in the counter-example."
        ),
        counter_example=counter,
        counter_example_data={
            "mechanisms": all_dup_mechs,
            "signature_count": total_duplicate_signatures,
            "location_count": len(duplicates),
        },
        hint=(
            "Hypothesis: mechanisms sharing a full signature in the same "
            "spatial boundary region suggest sub-circuit DEMs concatenated "
            "without XOR-merging; the correct probability is the XOR-fused "
            "value shown in the counter-example. On decompose_errors=True "
            "output, an undecomposed and a ^-decomposed instruction can also "
            "legitimately share a merged signature."
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


# Check Registry
LOCAL_CHECKS: dict[str, CheckFn] = {
    "detectability": check_detectability,
    "sensitivity": check_sensitivity,
    "observable_coverage": check_observable_coverage,
    "probability_bounds": check_probability_bounds,
    "duplicates": check_duplicates,
    "correctability": check_correctability,
}

# ALL_CHECKS is the public registry used by emlint.check() and the CLI.
ALL_CHECKS = dict(LOCAL_CHECKS)
