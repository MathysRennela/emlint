# emlint

[![CI](https://github.com/MathysRennela/dem-linter/actions/workflows/emlint.yml/badge.svg)](https://github.com/MathysRennela/dem-linter/actions/workflows/emlint.yml)
[![PyPI](https://img.shields.io/pypi/v/emlint)](https://pypi.org/project/emlint/)

**stim simulates. sinter samples. emlint verifies.**

emlint is a static linter for Detector Error Models (DEMs). A DEM describes
a circuit's noise as a list of *error mechanisms* — independent faults, each
with a probability and a syndrome footprint: which detectors it fires and which
logical observables it flips. It catches structural bugs in milliseconds — before
you run a single shot.

## The problem

A `DETECTOR` instruction omitted in round 2 of a circuit leaves detector D1
wired to nothing. The decoder silently miscorrects. The logical error rate
rises. The bug is invisible until ~10⁶ Sinter shots (≈45 minutes on a
standard laptop).

```
$ emlint check 'error(0.001) D0 L0
detector(0,0,0) D0
detector(1,0,2) D1'

Detectors: 2  Observables: 1  Error mechanisms: 1

  ✓ detectability: All error mechanisms that flip observables also trigger detectors.
  ✗ sensitivity: 1 detector(s) are never triggered by any error mechanism.
      Counter-example: Detector(s) not triggered by any error mechanism: D1@(1,0,2)
  ✓ observable_coverage: All declared observables are flipped by at least one error mechanism.
  ✓ probability_bounds: All error mechanism probabilities are in (0, 0.5].
  ✓ duplicates: No duplicate mechanism signatures found.
  ✓ correctability: Every syndrome maps to at most one distinct set of logical observables.
```

2ms. One line. No simulation. D1 carries coordinates `(1, 0, 2)` — round 2,
position (1, 0) — so you know exactly where in the circuit to look.

```
$ emlint check 'error(0.001) D0 L0
error(0.001) D1
detector(0,0,0) D0
detector(1,0,2) D1'

  ✓ detectability  ✓ sensitivity  ✓ observable_coverage
  ✓ probability_bounds  ✓ duplicates  ✓ correctability
```

## Installation

```
pip install emlint
```

## Usage

### CLI

```
emlint check path/to/circuit.dem
emlint check path/to/circuit.dem --format json
emlint check path/to/circuit.dem --check detectability,sensitivity
emlint check path/to/circuit.dem --severity error
```

Exit code `0` when all checks pass. Exit code `1` when any `error`-severity
check fails. Exit code `2` when there are warnings but no errors (usable in CI
to optionally escalate warnings without breaking the build).

`--severity error` suppresses `warning`-severity findings entirely — only
`error`-severity violations appear in output and affect the exit code. Useful
in CI pipelines where warnings are acknowledged but should not break the build.

### Python API

```python
import stim
import emlint

circuit = stim.Circuit.generated(
    "surface_code:rotated_memory_z",
    rounds=3,
    distance=5,
    after_clifford_depolarization=0.001,
)
report = emlint.check(circuit.detector_error_model(decompose_errors=True))
print(emlint.format_text(report))
```

`emlint.check()` also accepts a `pathlib.Path` or a raw DEM string.

### CI integration

Add to `.github/workflows/emlint.yml`:

```yaml
name: emlint
on:
  push:
    paths: ['**.dem']
  pull_request:
    paths: ['**.dem']

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install emlint
        run: pip install emlint
      - name: Run emlint on all DEM files
        run: find . -name "*.dem" | xargs -I{} emlint check {}
```

## Checks

| Check | What it catches | Severity |
|---|---|---|
| `detectability` | Errors that flip observables but trigger no detectors (undetectable) | error |
| `sensitivity` | Detectors never triggered by any error mechanism (dead detectors) | warning |
| `observable_coverage` | Logical observables never flipped by any error mechanism | error |
| `probability_bounds` | Error probabilities outside `(0, 0.5]` | error |
| `duplicates` | Error mechanisms with identical (detector, observable) signatures | warning |
| `correctability` | Syndromes mapping to multiple distinct observable sets | warning |

All checks operate on the standalone `.dem` file — no original circuit required.
Each failing check produces a counter-example pointing to the specific mechanism
or detector at fault.

## Formal grounding

The checks are grounded in the linear-algebra framework for detector error models
developed in arXiv:2407.13826. The central object is the **detector error matrix**
H ∈ 𝔽₂^{d×e}:

> **Definition** (Detector error matrix). H is a binary matrix with d rows
> (one per detector) and e columns (one per error mechanism). H_{i,j} = 1 if
> detector i is violated by error j.

The six checks are properties of H and the accompanying observable map L ∈ 𝔽₂^{k×e}:

| Check | Formal condition |
|---|---|
| `detectability` | ∃j : obs(j) ≠ ∅ ∧ H[:,j] = **0** |
| `sensitivity` | ∃i : H[i,:] = **0** |
| `correctability` | ∃j≠k : H[:,j] = H[:,k] ∧ obs(j) ≠ obs(k) |
| `duplicates` | ∃j≠k : H[:,j] = H[:,k] ∧ obs(j) = obs(k) |
| `observable_coverage` | ∃l : L[l,:] = **0** |
| `probability_bounds` | ∃j : p_j ∉ (0, 0.5] |

The paper also establishes that a DEM contains all information necessary to
verify fault-tolerance properties at the gadget, schedule, and circuit levels —
the theoretical basis for emlint's "no original circuit required" promise.

## Connecting a failed check to the circuit bug

When a check fails, the counter-example tells you *where* in the DEM the problem
is. The table below tells you *what* circuit-level mistake most likely produced it
and where to look in your circuit source.

### `detectability` fails

> `error(0.001) L0 — flips observable but triggers 0 detectors`

The listed mechanism flips a logical observable but no detector fires — the
decoder has no syndrome signal to correct it.

**What went wrong in the circuit:**
- A `DETECTOR` instruction was omitted from a syndrome measurement round. The
  round still runs and produces data, but no detector was wired to it.
- `OBSERVABLE_INCLUDE` targets a qubit that is outside the fault support of every
  modelled error (wrong qubit index, wrong basis).

**Where to look:** search your circuit for the round that *should* cover the data
qubits referenced in the failing mechanism's observable. Check that every syndrome
extraction round ends with a `DETECTOR` pointing at the right ancilla measurement.

---

### `sensitivity` fails

> `D17@(1,0,2) not triggered by any error mechanism`

The listed detector is declared but no error mechanism ever fires it.

**What went wrong in the circuit:**
- The ancilla qubit for this detector is measuring in the wrong Pauli basis
  (`X` vs `Z` mismatch), so the errors that *should* flip it pass through silently.
- The detector's coordinates point to the wrong spatial position — the qubit index
  in `DETECTOR rec[…]` is off by one.
- A syndrome round was accidentally removed from the circuit, leaving its detector
  declaration orphaned.

**Where to look:** the detector's coordinates (shown as `D17@(col,row,round)`)
identify the syndrome round and stabilizer position. Verify that the corresponding
ancilla qubit is connected to data qubits via the expected CNOT schedule, and that
the noise model includes errors on those CNOTs.

---

### `observable_coverage` fails

> `L1 not flipped by any error mechanism`

The listed logical observable is declared but no physical error can flip it.

**What went wrong in the circuit:**
- `OBSERVABLE_INCLUDE` on the wrong qubit or at the wrong point in the circuit
  (e.g. applied to an ancilla instead of a data qubit, or after a reset that
  erases the correlation).
- Observable index off-by-one in a multi-observable code.

**Where to look:** the counter-example gives you the observable index (e.g.
`L1`). Search your circuit source for every `OBSERVABLE_INCLUDE` with that
index. Verify that the qubit it references is part of the logical operator's
support and that errors on that qubit survive to the measurement record.
(`emlint check --format json` outputs counter-examples as structured data,
making it easy to script a targeted search when the circuit is auto-generated.)

---

### `probability_bounds` fails

> `error(0.0) D0 D1 — zero probability`  
> `error(nan) D3 — NaN probability`

An error mechanism has a probability of exactly 0 (a no-op), is negative, or is
NaN — all of which indicate a fault in DEM generation, not a physical noise model.

**What went wrong in the circuit / DEM generation script:**
- Numerical underflow: a product of small probabilities rounded to 0 instead of
  being pruned or clamped.
- Naive addition of two complementary probabilities exceeded 1, producing a
  negative remainder.
- A copy-paste error in a manual DEM left a placeholder (`nan`, `-1`, `0`)
  instead of a real probability.

**Where to look:** the mechanism's detector and observable targets identify which
fault path the DEM compiler was trying to express. Trace that fault path back to
the noise model parameters in your DEM generation script.

---

### `duplicates` fails

> `error(0.001, 0.001) share signature D3 D7; XOR-fused probability is 0.001998`

Two or more mechanisms share the same `(detectors, observables)` signature — the
same physical fault path is counted more than once.

**What went wrong in the circuit / DEM assembly:**
- Sub-circuit DEMs were concatenated (e.g. bulk + boundary + initialisation)
  without merging mechanisms that touch the same fault path. The correct operation
  is XOR-fusion: `p_eff = p1(1−p2) + p2(1−p1)`.
- An X error and a Y error on the same data qubit at a repetition code boundary
  each trigger the same detector set and flip the same observable (legitimate
  physics; use `--severity error` in CI to suppress this warning for known-correct
  code families).

**Where to look:** if the duplicate arises from concatenation, find the boundary
between the sub-circuits where the mechanism originates. If you are manually
composing DEMs with Python, apply XOR-fusion instead of list concatenation.

---

### `correctability` fails

> `syndrome {D3 D7} maps to observable sets {L0}, {L1}`

The same detector syndrome is produced by mechanisms that flip *different*
observables — the decoder cannot determine the correct logical correction.

**What went wrong in the circuit:**
- Two physically distinct errors (e.g. an X error on qubit A and a Z error on
  qubit B) produce the same syndrome but flip different logical observables. This
  is a genuine code distance problem: the code cannot distinguish them.
- The DEM was generated with `decompose_errors=True`, which breaks hyperedge
  mechanisms into sub-mechanisms that can create artificial syndrome collisions
  (use `--severity error` to suppress this known artefact in CI).
- A degenerate code family (colour codes) has syndromes that legitimately map to
  multiple valid logical corrections — this is an expected property, not a bug.

**Where to look:** the counter-example gives you the exact syndrome (e.g.
`{D3 D7}`) and the conflicting observable sets. Search your `.dem` file for
every `error(…)` line whose detector targets match that set — those are the two
colliding mechanisms. In the original circuit, find the gate locations
corresponding to each mechanism's targets (the detector coordinates annotate
the round and spatial position). If both locations are in the *same* Pauli
basis and the same round, this is likely a genuine distance-1 path. If they
are in different bases or rounds, look for a missing stabilizer measurement
or a mis-wired CNOT that merges two logically distinct fault paths.

**Scope note:** this check examines each mechanism *individually*. It does not
detect cases where two *co-occurring* faults combine to produce a syndrome that
maps to conflicting corrections — that is the code distance problem and is not
checked here. A future version will address multi-fault correctability via
compositional reasoning (pre/post-conditions on circuit segments).

## Known false positives

**`correctability` with `decompose_errors=True`**

When a DEM is generated with `stim`'s `decompose_errors=True`, the hyperedge
decomposition can create sub-mechanism pairs that share the same detector set
but differ in observables — a syndrome collision that does not exist in the
original hyperedge model. The check fires at `warning` severity.

*Mitigation:* use `--severity error` in CI, or pass `decompose_errors=False`
to get a clean `correctability` result with no artefacts.

**`duplicates` at boundaries in degenerate code families**

Degenerate fault paths (e.g. X and Y errors at a repetition code boundary that
produce the same syndrome and flip the same observable) are correctly flagged as
duplicates. The warning is accurate — the XOR-fused probability is shown — but
may not require user action in degenerate code families.

*Mitigation:* use `--severity error` in CI to suppress.

## References

- [arXiv:2407.13826](https://arxiv.org/abs/2407.13826) — formal linear-algebra framework for detector error models;
  source of the detector, noise model, detector error matrix, and circuit
  distance definitions that ground the emlint checks.
- [arXiv:2603.20127](https://arxiv.org/abs/2603.20127) — formal decoder evaluation; operates at the circuit + decoder
  layer and assumes a structurally sound DEM (the precondition emlint establishes).

## License

Apache 2.0
