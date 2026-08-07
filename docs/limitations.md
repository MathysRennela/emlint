# v0.2 limitations

emlint v0.2 is a preliminary release. This page records the current limits of
its user-facing guarantees so that implementation details can change without
changing the basic expectations below.

## DEM-only analysis

emlint analyzes a Detector Error Model, not the original circuit or decoder.
A passing report does not prove that:

- the circuit generated the intended DEM;
- the decoder is configured correctly;
- the code has a desired distance;
- all combinations of physical faults are correctable.

## Warnings are contextual

`warning` findings are deliberately advisory. In particular:

- `sensitivity` can flag detectors that are intentionally unreachable;
- `duplicates` can arise from legitimate code-family structure or DEM
  composition;
- `correctability` can flag valid degeneracy or decomposition behavior.

Review the counter-example and the code family before treating a warning as a
construction bug. Use `--severity error` when CI should report only the
unconditional error-severity checks.

## Decomposition provenance

The Stim frontend preserves the combined detector and observable XOR semantics
of an `error(...)` instruction, but v0.2 does not preserve the individual
components separated by `^` targets. Consequently, emlint cannot independently
validate decomposition hints or explain every warning in terms of the original
components. This is tracked technical debt for a later version.

## Repeat blocks

v0.2 accepts DEMs containing `REPEAT` blocks. The implementation can inspect
repeat-local structure without expanding every iteration for some checks.
`duplicates` and `correctability` remain expansion-based, so their runtime and
memory use can grow with the number of expanded repeat mechanisms.

This is a documented performance limitation, not a general correctness claim.
The repeat-scaling benchmark is informational and does not promise constant
runtime in the number of repeat rounds.

## API stability

The six production check names, the basic CLI, and the report formats are the
intended v0.2 user contract. Internal classes, traversal strategy, caching, and
experimental checks may change before v1.0.
