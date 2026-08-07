# Changelog

User-visible changes to emlint. 
Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.0] — 2026-08-06

This version includes optimization to the existing checks, affecting performance relative to v0.1.2. A conscious choice was made to favour speeding up large DEMs at the cost of some overhead for small DEMs.

### Added

- Repeat-aware DEM processing: scope-local checks can inspect repeated mechanisms without expanding every iteration.
- Strict validation of repeat counts, offsets, detector/observable IDs, and tree node types. Invalid internal trees now raise instead of changing a verdict.
- Shared flatten caching for the cross-scope `duplicates` and `correctability` checks.
- Repeat-origin witnesses in `correctability` diagnostics.
- A validated no-repeat dispatcher path that reduces small-model overhead while preserving the existing check behavior.

### Changed

- Scope-local-only selections perform no flatten operation on repeat-free input.
- Cross-scope selections use one shared flatten operation.
- Built-in checks receive isolated read-only views; custom checks receive
  independent defensive views.
- Repeated violations are reported by mechanism template/signature count rather
  than expanded repeat-iteration count.
- `correctability` structured diagnostics include rendered conflicts, a total
  conflict count, and an explicit witness-truncation flag.
- Input failures that prevent linting now use exit code `3`.
- `correctability` is now `warning` severity, to account that some codes violate it by design.
- Existing string file paths remain accepted by the Python API for backward
  compatibility; explicit `Path` objects remain available for unambiguous file input.

### Known limitations

The checks `duplicates` and `correctability` remain flatten-based. Their runtime grows with the expanded mechanism count in repeated DEMs. As a result, the time complexity of a full round of checks is still a function of the number of repeat block rounds.

The Stim frontend still discards `^` separator targets instead of preserving per-component decomposition provenance. The six production checks therefore
validate the combined `ErrorMechanism` representation and do not independently
validate the original decomposition.

### Compatibility

- Python >= 3.10
- Stim >= 1.14
- No breaking changes to the public Python API or check-result exit-code meanings.
  CLI input failures now use exit code `3` so that `2` remains exclusively for
  warning-only lint results. With `--severity error`, warning-only reports are
  intentionally displayed as zero-error results and exit `0`.

## [0.1.2] — 2026-05-22

### Added

- `RepeatBlock` and `ErrorModel.flattened()` for structured DEM repeat blocks.
- Decomposition-aware provenance for `correctability`.

### Changed

- `correctability` severity was promoted from `warning` to `error`.
- The Stim frontend preserves repeat blocks instead of eagerly flattening them.
- CLI error handling and Stim integration coverage were expanded.

## [0.1.1] — 2026-04-08

### Changed

- Improved counter-example presentation.
- Minor check-performance improvements.

## [0.1.0] — 2026-03-26

Initial release with six production checks:

- `detectability` — observable flips without detector triggers (`error`)
- `sensitivity` — declared detectors never triggered (`warning`)
- `observable_coverage` — declared observables never flipped (`error`)
- `probability_bounds` — probabilities outside `(0, 0.5]` (`error`)
- `duplicates` — repeated mechanism signatures (`warning`)
- `correctability` — one syndrome mapping to multiple observable sets (`error`)

The CLI supports text/JSON output, check selection, severity filtering, and
exit codes `0` (pass), `1` (error), and `2` (warnings only).

[0.2.0]: https://github.com/MathysRennela/emlint/releases/tag/v0.2.0
[0.1.2]: https://github.com/MathysRennela/emlint/releases/tag/v0.1.2
[0.1.1]: https://github.com/MathysRennela/emlint/releases/tag/v0.1.1
[0.1.0]: https://github.com/MathysRennela/emlint/releases/tag/v0.1.0
