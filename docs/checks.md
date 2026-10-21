# Check catalog

This page describes the seven production checks in emlint v0.2. Each check
returns a `PropertyResult` with a pass/fail status, severity, message, and (on
failure) a counter-example.

## Production checks

| Check | Scope | Detects | Severity | Repeat behavior |
|---|---|---|---|---|
| `detectability` | Per mechanism | An observable flip with no detector syndrome | error | Template-local; detector shifts preserve emptiness |
| `sensitivity` | Global detector union | A declared detector never triggered by a mechanism | warning | Exact symbolic support for supported repeat shapes; exact fallback otherwise |
| `observable_coverage` | Global observable union | A declared observable never flipped by a mechanism | error | Template-local union because observable IDs are not shifted |
| `probability_bounds` | Per mechanism | Invalid or suspicious mechanism probabilities | error or warning | Template-local because probabilities are not shifted |
| `duplicates` | Cross-mechanism relation | Repeated detector/observable signatures | warning | Exact shared flattening; repetition can create collisions |
| `correctability` | Cross-mechanism relation | Syndrome-to-observable ambiguity | warning | Exact shared flattening; repetition can create conflicts |
| `null_mechanism` | Per mechanism | Error mechanism with empty detector and observable support | warning | Template-local; repetition preserves emptiness |

## Report disclosures

A passing battery is not by itself a statement that a DEM was audited. The
report layer discloses the two cases where it was not, and neither disclosure
carries a severity or changes an exit code:

| Disclosure | Meaning |
|---|---|
| `[partial-parse]` | The DEM contains instructions emlint cannot represent; the checks ran on a partial view. |
| `[vacuous]` | The DEM has no error mechanisms, so every mechanism-level check had nothing to examine. |
| `[partial]` | Some selected checks emitted no verdict (`skipped` or `inconclusive`). |

`[vacuous]` is reported as `is_vacuous` in the JSON and SARIF outputs. See
[limitations.md](limitations.md) § "An empty audit is not a clean audit".

## What each result means

### `detectability`

Flags an error mechanism that flips one or more logical observables but triggers
no detectors. The decoder has no syndrome signal for that mechanism.

Example:

```text
error(0.01) L0
```

This is an error-severity finding.

### `sensitivity`

Flags declared detectors that no mechanism ever triggers. This can indicate a
missing fault model or a detector wiring problem. It is warning-level because a
model may intentionally omit some physically impossible fault paths.

### `observable_coverage`

Flags declared observables that never appear in any mechanism. This commonly
indicates a missing or miswired logical observable. It is an error-severity
finding.

### `probability_bounds`

Checks mechanism probabilities in two categories.

- `NaN`, infinities, zero, and negative values violate probability validity and
  are error-severity findings.
- Values above `0.5` are warning-level anomalies because conditioned or
  adversarial models may intentionally use them.

A warning-only result from this check has warning severity; a result containing
any unphysical value has error severity.

### `duplicates`

Flags multiple mechanisms with the same detector and observable signature.
When the entries represent the same fault path, their probabilities should be
XOR-folded rather than treated as independent entries. Valid code families and
DEM composition can also produce duplicate signatures, so this check is a
warning.

### `correctability`

Flags a detector syndrome that maps to multiple distinct observable sets. Such
a mapping can make the logical correction ambiguous, but it can also be valid
for degenerate code families or decomposed DEMs. It is therefore a warning in
v0.2, not an unconditional correctness error.

The check is mechanism-local: it does not prove or disprove the general code
distance, and it does not analyze combinations of co-occurring mechanisms.

### `null_mechanism`

Flags error mechanisms whose detector support and observable support are both
empty. Such a mechanism cannot appear in any syndrome or observable flip, so
it is a provable no-op. It is a warning because a hand-written DEM may carry
an intentional no-op line.

The predicate reads only whether both supports are empty, so it is
shift-invariant: repeating a mechanism never creates a violation the template
does not already carry. The check is therefore template-local, and a repeat
body is reported as one witness per template plus an `instance_count` rather
than as one entry per expanded iteration.

## Repeat-aware evaluation boundaries

The production checks do not all admit the same repeat optimization:

- `detectability`, `probability_bounds`, `observable_coverage`, and
  `null_mechanism` can evaluate repeat templates or scope-local unions without
  expanding every iteration.
- `sensitivity` uses exact symbolic arithmetic-progression support for supported
  repeat shapes and retains exact fallback behavior for unsupported shapes.
- `duplicates` and `correctability` remain cross-scope checks. Their relations
  can be created by repetition, so they use the shared exact flattening boundary.
- A repeat-aware fast path is valid only when its pass/fail result agrees with
  the fully flattened model. A benchmark result alone does not establish that
  equivalence.

## Repeat-aware contract (v0.2.3)

| Check | Quantifier structure | Repetition creates new violation? | Shifts preserve predicate? | Preferred evaluation strategy | Proof/evidence status | Flattened-oracle coverage |
|---|---|---|---|---|---|---|
| `detectability` | per mechanism | no (repeats an existing undetectable mechanism) | yes (emptiness is shift-invariant) | template-local | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |
| `observable_coverage` | global observable union | no (a missing observable stays missing) | yes (observable IDs are not shifted) | template-local union | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |
| `probability_bounds` | per mechanism | no (probabilities are not shifted) | yes | template-local | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |
| `sensitivity` | global detector union | no (repetition can only add triggered detectors) | yes for supported shapes | exact symbolic support; exact fallback otherwise | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |
| `duplicates` | cross-mechanism relation | yes (repetition can create signature collisions) | n/a (cross-scope) | exact shared flattening | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |
| `correctability` | cross-mechanism relation | yes (repetition can create syndrome conflicts) | n/a (cross-scope) | exact shared flattening | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |
| `null_mechanism` | per mechanism | no (empty support is shift-invariant) | yes | template-local | PROVEN from definitions | `tests/test_check_oracles.py`, `tests/test_repeat_optimization.py` |

**Benchmark result** (a repeat-aware contract field per
`notes/design/THEORY_VS_FEATURE_PRIORITIES.md` §3): none is recorded per check
as of v0.2.3 — no per-check benchmark run exists, and this table claims no
repeat-count complexity. The evaluation-strategy claims are pinned behaviorally
instead: verdict equivalence against the flattened oracle in
`tests/test_check_oracles.py` and `tests/test_repeat_optimization.py`, and no
repeat-body expansion for the template-local checks
(`tests/test_check_null_mechanism.py` runs a 100,000-iteration repeat).

## Reading counter-examples

Counter-examples identify the relevant detector, observable, or mechanism. For
large repeated DEMs, counts may refer to mechanism templates or signatures
rather than every expanded repeat iteration. In `correctability`, structured
JSON contains the rendered conflicts and reports `total_conflicts` plus
`witnesses_truncated` when output is bounded. Use the JSON format when a script
needs the structured `counter_example_data` field.

## Machine-readable output contract (stable)

Each failing verdict carries `counter_example_data` with the exact keys and
value types below, plus an optional `hint` string. This schema is contractual
for machine consumers (coding-agent loops, CI tooling): additive changes only.
List fields are complete — `mechanisms` names every violating template even
when the text witness is truncated — except where a truncation flag
(`correctability.witnesses_truncated`) discloses a bound. Only the
human-readable `counter_example` string is capped with `(and N more)`.
The `hint` field is `str | None` (default `None`), populated only on failure,
and phrased as a hypothesis — a check states a concrete remediation
possibility, never a verdict about the root cause.

| Check | `counter_example_data` keys | Types |
|---|---|---|
| `detectability` | `mechanisms`, `instance_count` | `list[str]`, `int` |
| `sensitivity` | `detectors` | `list[int]` |
| `observable_coverage` | `observables` | `list[int]` |
| `probability_bounds` | `mechanisms`, `instance_count` | `list[str]`, `int` |
| `duplicates` | `mechanisms`, `signature_count`, `location_count` | `list[str]`, `int`, `int` |
| `correctability` | `conflicts`, `total_conflicts`, `witnesses_truncated` | `list[object]`, `int`, `bool` |
| `null_mechanism` | `mechanisms`, `instance_count` | `list[str]`, `int` |

`mechanisms` entries are rendered instruction strings of the form
`error(p) D<i>… L<j>…`, with the target list empty when the mechanism has none
(a `null_mechanism` entry is the bare instruction `error(p)`). Each
`correctability` entry in `conflicts` is an object
with `syndrome` (`list[int]`), `observable_sets` (`list[list[int]]`), and
`witnesses` (`list[object]` with `mechanism: str` and `iteration: list[int]`).

The `duplicates` failure message is context-sensitive: declare
`--context dem_assembly=concatenated` (or `monolithic`) to replace the default
both-hypotheses wording with the claim matching the DEM's known origin.

Checks that can state a concrete remediation populate `hint` on failure:
`detectability`, `sensitivity`, `duplicates`, and `correctability`. Hints are
heuristic interpretations with warning-grade epistemics; do not treat them as
root-cause verdicts.
