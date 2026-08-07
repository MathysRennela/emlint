# Debugging with emlint

When a check fails, its counter-example identifies where to start. This guide
connects each production check to common circuit or DEM-construction mistakes.

## `detectability` fails

> `error(0.001) flips L0 but triggers 0 detectors`

The mechanism flips a logical observable but no detector fires. The decoder has
no syndrome signal to correct it.

**Possible causes:**

- A `DETECTOR` instruction was omitted from a syndrome measurement round.
- `OBSERVABLE_INCLUDE` targets the wrong qubit or basis.

**Where to look:** inspect the round that should cover the data qubits referenced
by the failing mechanism. Check that the syndrome extraction round ends with a
`DETECTOR` pointing at the intended measurement record.

## `sensitivity` fails

> `Detector(s) not triggered by any error mechanism: D17@(1,0,2)`

The detector is declared but no modelled fault ever triggers it.

**Possible causes:**

- The ancilla is measured in the wrong Pauli basis.
- Detector coordinates or `rec[...]` indices are off by one.
- A syndrome round was removed while its detector declaration remained.
- The fault model omits errors that should participate in this detector.

**Where to look:** use the detector coordinates to identify the syndrome round
and spatial position. Verify the corresponding ancilla schedule and noise model.
This is a warning because some detectors may intentionally be outside the
represented fault support.

## `observable_coverage` fails

> `Observable(s) not flipped by any error mechanism: L1`

The observable is declared but no mechanism flips it.

**Possible causes:**

- `OBSERVABLE_INCLUDE` refers to the wrong qubit or circuit location.
- An observable index is off by one.
- A reset or basis change removed the intended correlation.

**Where to look:** search the circuit for every `OBSERVABLE_INCLUDE` with the
reported index and verify that the referenced qubit belongs to the logical
operator support.

## `probability_bounds` fails

> `error(0.0) D0 D1 — zero probability`  
> `error(nan) D3 — NaN probability`

The mechanism has a zero, negative, non-finite, or otherwise suspicious
probability.

**Possible causes:**

- Numerical underflow produced a zero instead of pruning the mechanism.
- Probability composition used ordinary addition instead of the appropriate
  XOR/channel composition.
- A generated DEM contains a placeholder such as `nan`, `-1`, or `0`.
- A conditioned or adversarial model intentionally uses a probability above
  `0.5`; this is reported as a warning rather than an unconditional error.

Trace the mechanism's detector and observable targets back to the DEM-generation
code and its noise parameters.

## `duplicates` fails

> `error(0.001, 0.001) share signature D3 D7; XOR-fused probability is 0.001998`

Multiple mechanisms share the same detector and observable signature.

**Possible causes:**

- Sub-circuit DEMs were concatenated without merging coincident mechanisms.
- A legitimate code-family boundary or decomposition produced equivalent
  signatures.

If the mechanisms represent the same fault path, combine their probabilities
using XOR fusion rather than treating them as independent entries:

```text
p_eff = p1(1 − p2) + p2(1 − p1)
```

Use `--severity error` in CI when warnings from a known-correct code family are
not actionable.

## `correctability` fails

> `syndrome {D3 D7} maps to observable sets {L0}, {L1}`

The same detector syndrome is associated with mechanisms that flip different
observables. This can make the logical correction ambiguous.

**Possible causes:**

- Two physically distinct faults produce the same syndrome but different
  logical effects.
- A missing stabilizer measurement or miswired gate merged distinct fault paths.
- A degenerate code family legitimately admits multiple logical mappings.
- DEM decomposition produced multiple component mechanisms with this signature.

This check is warning-level in v0.2. Inspect the reported syndrome and
observable sets before deciding whether the result is a circuit bug or an
expected property of the code family.

**Scope:** the check examines mechanisms individually. It does not analyze
combinations of co-occurring faults or prove the general code distance.

## General workflow

1. Re-run with the default text output and read the counter-example.
2. Use detector coordinates when available to locate the relevant round.
3. Use `--format json` when a script needs `counter_example_data`.
4. Check whether the finding is an error or a contextual warning.
5. Compare against the [formal properties](formal-grounding.md) and the
   [v0.2 limitations](limitations.md) before changing the circuit.
