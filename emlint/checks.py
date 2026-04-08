from __future__ import annotations

import math
from collections import Counter
from emlint.model import ErrorModel
from emlint.report import CheckFn, PropertyResult

_MAX_SHOWN = 10  # max counter-examples shown in truncated lists


def _det_label(d: int, coords: dict[int, tuple[float, ...]]) -> str:
    """Format a detector as 'D17@(1,0,2)' when coordinates are available, else 'D17'."""
    c = coords.get(d)
    if c:
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


def check_detectability(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """Verify every error mechanism that flips observables also triggers detectors.

    This check is about *detectability*: a logical error that leaves the syndrome
    trivially empty cannot be detected, and therefore not corrected, by any decoder.
    It does not verify whether the syndrome uniquely identifies which observable
    was flipped; that stronger guarantee is checked by check_correctability.

    Property: ∀m ∈ mechanisms, obs(m) ≠ ∅ → det(m) ≠ ∅
    """
    violations = [
        mech for mech in model.error_mechanisms
        if not mech.detectors and mech.observables
    ]

    if violations:
        lines = []
        for mech in violations[:max_shown]:
            obs_str = ", ".join(f"L{o}" for o in sorted(mech.observables))
            lines.append(f"error({mech.probability}) flips {obs_str} but triggers 0 detectors")
        counter = "; ".join(lines)
        if len(violations) > max_shown:
            counter += f" (and {len(violations) - max_shown} more)"
        def _mech_str(mech) -> str:
            targets = " ".join(
                [f"D{d}" for d in sorted(mech.detectors)]
                + [f"L{o}" for o in sorted(mech.observables)]
            )
            return f"error({mech.probability})" + (f" {targets}" if targets else "")

        return PropertyResult(
            name="detectability",
            passed=False,
            severity="error",
            message=f"Found {len(violations)} undetectable error mechanism(s) that flip observable(s).",
            counter_example=counter,
            counter_example_data={"mechanisms": [_mech_str(m) for m in violations]},
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
    participating: set[int] = set()
    for mech in model.error_mechanisms:
        participating.update(mech.detectors)

    dead = sorted(model.detectors - participating)

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
        )

    return PropertyResult(
        name="sensitivity",
        passed=True,
        severity="warning",
        message="All detectors are triggered by at least one error mechanism.",
    )


def check_observable_coverage(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """Verify every declared logical observable is flipped by at least one error mechanism.

    An observable that never appears in any mechanism is either perfectly protected
    (implausible) or the OBSERVABLE_INCLUDE instruction is not linked to any data qubits.
    In both cases the decoder will always predict the trivial correction for that
    observable, masking real logical errors entirely.

    Property: ∀ℓ ∈ O, ∃m ∈ mechanisms, ℓ ∈ obs(m)
              equivalently: O ⊆ ⋃_{m} obs(m)
    """
    covered: set[int] = set()
    for mech in model.error_mechanisms:
        covered.update(mech.observables)

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
    if math.isnan(p):        return "p = NaN", "NaN probability"
    if not math.isfinite(p): return "p = ±inf", "infinite probability"
    if p < 0.0:              return "p < 0",    "negative probability"
    if p == 0.0:             return "p = 0",    "zero probability"
    return                          "p > 0.5",  "use complementary probability (p → 1−p)"


# Tags that represent unphysical probabilities; p > 0.5 is merely anomalous.
_UNPHYSICAL_TAGS = {"p = NaN", "p = ±inf", "p < 0", "p = 0"}


def check_probability_bounds(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
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
    violations = [
        mech for mech in model.error_mechanisms
        if math.isnan(mech.probability) or not (0.0 < mech.probability <= 0.5)
    ]
    if violations:
        lines: list[str] = []
        tag_counts: Counter[str] = Counter()
        has_unphysical = False
        for mech in violations:
            p = mech.probability
            tag, hint = _prob_label(p)
            tag_counts[tag] += 1
            if tag in _UNPHYSICAL_TAGS:
                has_unphysical = True
            if len(lines) < max_shown:
                target_parts = [f"D{d}" for d in sorted(mech.detectors)] + [f"L{o}" for o in sorted(mech.observables)]
                targets = (" " + " ".join(target_parts)) if target_parts else ""
                lines.append(f"error({p}){targets} — {hint}")
        counter = "; ".join(lines)
        if len(violations) > max_shown:
            counter += f" (and {len(violations) - max_shown} more)"
        parts = [f"{n} with {tag}" for tag, n in tag_counts.items()]
        first_v = violations[0]
        first_targets = " ".join(
            [f"D{d}" for d in sorted(first_v.detectors)]
            + [f"L{o}" for o in sorted(first_v.observables)]
        )
        first_mech_str = f"error({first_v.probability})" + (f" {first_targets}" if first_targets else "")
        return PropertyResult(
            name="probability_bounds",
            passed=False,
            severity="error" if has_unphysical else "warning",
            message=f"Found {len(violations)} error mechanism(s) with out-of-range probability ({', '.join(parts)}).",
            counter_example=counter,
            counter_example_data={"probability": first_v.probability, "mechanism": first_mech_str},
        )

    return PropertyResult(
        name="probability_bounds",
        passed=True,
        severity="error",
        message="All error mechanism probabilities are in (0, 0.5].",
    )


def check_duplicates(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """Flag error mechanisms that share the same (detectors, observables) signature.

    When a DEM is assembled from sub-circuits or boundary conditions, the same
    fault path can be counted twice instead of being XOR-fused. Decoders that
    assume independence miscalculate likelihoods. The correct XOR-fold over n
    occurrences is iterated: p_eff = p1 ⊕ p2 ⊕ … where a ⊕ b = a(1-b) + b(1-a).

    Property: ∀m, m' ∈ mechanisms, m ≠ m' → (det(m), obs(m)) ≠ (det(m'), obs(m'))
              i.e., the signature map m ↦ (det(m), obs(m)) is injective.
    """
    seen: dict[tuple[frozenset[int], frozenset[int]], list[float]] = {}
    for mech in model.error_mechanisms:
        key = (mech.detectors, mech.observables)
        seen.setdefault(key, []).append(mech.probability)

    duplicates = {k: ps for k, ps in seen.items() if len(ps) > 1}
    # Injectivity is violated if two distinct mechanisms share the same signature.
    if duplicates:
        lines = []
        for (dets, obs), probs in list(duplicates.items())[:max_shown]:
            targets = " ".join(_det_label(d, model.detector_coords) for d in sorted(dets)) or "(no detectors)"
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
        return PropertyResult(
            name="duplicates",
            passed=False,
            severity="warning",
            message=(
                f"Found {len(duplicates)} duplicate mechanism signature(s). "
                f"The same fault path appears more than once in the DEM, which "
                f"typically happens when sub-circuit DEMs are concatenated without "
                f"merging coincident mechanisms. Duplicate probabilities should be "
                f"XOR-folded as p_eff = p1*(1-p2) + p2*(1-p1) (iterated for 3+), "
                f"not left as separate entries."
            ),
            counter_example=counter,
            counter_example_data={"mechanisms": all_dup_mechs},
        )

    return PropertyResult(
        name="duplicates",
        passed=True,
        severity="warning",
        message="No duplicate mechanism signatures found.",
    )


def check_correctability(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """Verify that every detector syndrome maps to at most one observable set.

    A decoder that receives a syndrome must infer a unique logical correction.
    If two mechanisms produce the same syndrome yet flip *different* sets of
    observables, any decoder is forced to guess between them and will fail on
    at least one of the two faults.

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

    Known false-positive sources:
      - decompose_errors=True: stim decomposes high-weight errors into pairs of
        low-weight components that share a syndrome but differ in their observable
        sets; these violations are artefacts of the decomposition, not genuine
        decoding ambiguities.
      - Intentionally degenerate codes: codes where multiple fault paths produce
        the same syndrome but map to the same net logical correction (e.g. via
        compensating observables) may still trigger this check because it operates
        on individual mechanisms rather than equivalence classes of corrections.
    """
    # Map each detector frozenset to the set of observable frozensets seen with it.
    syndrome_to_obs: dict[frozenset[int], set[frozenset[int]]] = {}
    for mech in model.error_mechanisms:
        syndrome_to_obs.setdefault(mech.detectors, set()).add(mech.observables)

    conflicts: dict[frozenset[int], set[frozenset[int]]] = {
        dets: obs_set
        for dets, obs_set in syndrome_to_obs.items()
        if len(obs_set) > 1
    }
    # A conflict occurs when a syndrome (detector set) maps to more than one distinct observable set,
    # i.e. there exist at least two mechanisms m and m' such that det(m) = det(m') but obs(m) ≠ obs(m').
    if conflicts:
        lines = []
        for dets, obs_set in list(conflicts.items())[:max_shown]:
            det_str = " ".join(_det_label(d, model.detector_coords) for d in sorted(dets)) if dets else "(no detectors)"

            obs_variants = ", ".join(
                "{" + " ".join(f"L{o}" for o in sorted(obs)) + "}"
                for obs in sorted(obs_set, key=lambda s: sorted(s))
            )
            lines.append(f"syndrome {{{det_str}}} maps to observable sets {obs_variants}")
        counter = "; ".join(lines)
        if len(conflicts) > max_shown:
            counter += f" (and {len(conflicts) - max_shown} more)"
        first_dets = next(iter(conflicts))
        first_obs_set = conflicts[first_dets]
        return PropertyResult(
            name="correctability",
            passed=False,
            severity="warning",
            message=(
                f"Found {len(conflicts)} syndrome(s) that map to more than one distinct "
                f"observable set. The decoder cannot determine which logical observable "
                f"was flipped from the measurement outcome alone. "
                f"Note: if this DEM was generated with decompose_errors=True, some "
                f"violations may be artefacts of the decomposition rather than genuine "
                f"ambiguities."
            ),
            counter_example=counter,
            counter_example_data={
                "syndrome": sorted(first_dets),
                "observable_sets": [sorted(obs) for obs in sorted(first_obs_set, key=lambda s: sorted(s))],
            },
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
