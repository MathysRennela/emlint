# Formal grounding

This page records the mathematical properties checked by emlint v0.2. It is
separate from the getting-started documentation because the definitions are
more stable and precise than the current implementation strategy.

## DEM vocabulary

A detector error model is treated as a collection of error mechanisms.

- **Error mechanism:** an independent fault with a probability and a signature.
- **Detector:** an index in the detector list. A mechanism may trigger zero or
  more detectors.
- **Observable:** an index identifying a logical observable. A mechanism may
  flip zero or more observables.
- **Syndrome:** the set of detectors triggered by a mechanism.

For a mechanism `m`, write:

- `p(m)` for its probability;
- `det(m)` for its detector set;
- `obs(m)` for its observable set.

Let `D` be the declared detector set and `O` the declared observable set.

## Checked properties

### Detectability

```text
∀m, obs(m) ≠ ∅ → det(m) ≠ ∅
```

Every mechanism that flips a logical observable must produce a non-empty
syndrome. Otherwise the decoder receives no detector information about that
logical fault.

### Sensitivity

```text
D ⊆ ⋃ₘ det(m)
```

Every declared detector must be triggered by at least one mechanism. This is a
structural participation property and is reported as a warning because some
models may intentionally contain detectors outside the represented fault
support.

### Observable coverage

```text
O ⊆ ⋃ₘ obs(m)
```

Every declared observable must be flipped by at least one mechanism. An
observable absent from all mechanisms may indicate a missing or miswired
logical observable.

### Probability bounds

```text
∀m, 0 < p(m) ≤ 0.5
```

The implementation also rejects NaN and infinite probabilities. Nonphysical
values (`NaN`, infinities, zero, or negative values) are error-severity
findings. Values above `0.5` are warning-level anomalies because some
conditioned or adversarial models may intentionally use them.

### Duplicate signatures

```text
∀m ≠ m′, (det(m), obs(m)) ≠ (det(m′), obs(m′))
```

The detector/observable signature map is required to be injective. Duplicate
signatures can indicate that a fault path was counted more than once and should
be XOR-folded. The check is warning-level because valid code families and DEM
composition can also produce duplicate signatures.

### Correctability

```text
∀m, m′, det(m) = det(m′) → obs(m) = obs(m′)
```

A detector syndrome should map to at most one observable set at the individual
mechanism level. The check is warning-level because valid degenerate code
families and decomposed DEMs can legitimately contain multiple observable
mappings for a syndrome.

This is not a general code-distance theorem. It does not analyze combinations
of co-occurring mechanisms or prove that a decoder succeeds on every physical
fault pattern.

## Scope of the properties

These are properties of the DEM representation supplied to emlint. They do not
prove that:

- the original circuit generated the intended DEM;
- a decoder is configured correctly;
- a code has a particular distance;
- all multi-fault combinations are correctable.

See [the v0.2 limitations](limitations.md) for current representation and
repeat-block caveats.
