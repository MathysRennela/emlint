# Check catalog

This page describes the six production checks in emlint v0.2. Each check
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

## Repeat-aware evaluation boundaries

The production checks do not all admit the same repeat optimization:

- `detectability`, `probability_bounds`, and `observable_coverage` can evaluate
  repeat templates or scope-local unions without expanding every iteration.
- `sensitivity` uses exact symbolic arithmetic-progression support for supported
  repeat shapes and retains exact fallback behavior for unsupported shapes.
- `duplicates` and `correctability` remain cross-scope checks. Their relations
  can be created by repetition, so they use the shared exact flattening boundary.
- A repeat-aware fast path is valid only when its pass/fail result agrees with
  the fully flattened model. A benchmark result alone does not establish that
  equivalence.

## Reading counter-examples

Counter-examples identify the relevant detector, observable, or mechanism. For
large repeated DEMs, counts may refer to mechanism templates or signatures
rather than every expanded repeat iteration. In `correctability`, structured
JSON contains the rendered conflicts and reports `total_conflicts` plus
`witnesses_truncated` when output is bounded. Use the JSON format when a script
needs the structured `counter_example_data` field.
