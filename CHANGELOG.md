# Changelog

User-visible changes to emlint. 
Versions follow [Semantic Versioning](https://semver.org/).

## [0.2.4] — 2026-10-27

Maintainer-owned experimental checks and promotion wave. Ships the promotion of
`connectivity` and `boundary_symmetry` to production, plus `high_probability_mechanisms`
(promoted in the same cycle), and the `LOCAL_CHECKS` / `GLOBAL_CHECKS` registry split.

### Added

- `duplicates` also reports mechanisms that repeat a target inside one
  instruction (`error(p) D0 D0`), preserving the target multiplicity that the
  parity fold discards. DEM readers disagree on that shape (cancel, self-loop,
  or rejection), so the finding is a portability warning.
- Experimental `coordinate_dimension_consistency` (advisory): declared detector
  coordinates that use different widths.
- Experimental `distance` reports per-observable minima in
  `counter_example_data["per_observable"]`, so a weakly protected logical is
  visible behind the model-wide minimum.
- Production check `connectivity` (global): detector-mechanism Tanner graph
  connected-component count. Profile-scoped severity: `error` for a declared
  single-decoding-graph profile (`strict-dem`), `warning` otherwise, `skipped`
  for explicitly decomposed/multi-component models.
- Production check `boundary_symmetry` (global, warning): per-observable distance
  lower-bound balance.
- Production check `high_probability_mechanisms` (warning): flags mechanisms
  whose probability exceeds a configurable threshold (default 0.3).
- `LOCAL_CHECKS` / `GLOBAL_CHECKS` dictionaries in `emlint/checks.py`;
  `ALL_CHECKS` is their union.
- Corpus applicability metadata for every clean corpus DEM.
- Repeat-aware oracle tests for the promoted global checks.
- Experimental corpus smoke test.

### Changed

- Enhanced `duplicates` reports fused probability per group; no separate
  `error` gate because `p_eff > 0.5` requires a contributing `p > 0.5`,
  already flagged by `probability_bounds`.
- Reports retain the selected profile (carried from v0.2.3).
- `emlint/checks.py` gained the graph helpers needed by the promoted global
  checks.
- Zero-count repeat bodies no longer produce repeated-target findings. Local repeat traversal now shifts decomposition-hint detector IDs with the mechanism.
- Python 3.10 installations include the `tomli` fallback dependency required by the CLI configuration loader.
- `sensitivity` and `observable_coverage` report a DEM with no error mechanisms as `skipped` instead of failing each declared detector/observable. 

### Known limitations

- `bounded_multifault_detectability` and `undetectable_combination_ambiguity`
  remain experimental (bounded search, warning severity).
- `distance` remains experimental (no sound per-mechanism hyperedge bound yet).
- Bounded checks are O(n^k); large DEMs require a small `max_weight`.

## [0.2.3] — 2026-10-21

Hardening release for existing checks and report/CLI behavior, plus the
`null_mechanism` promotion. Public check signatures and the exit-code contract
remain unchanged.

### Added

- Production check `null_mechanism` (warning): flags error mechanisms whose detector and observable support are both empty. Promoted from `experimental/` and enabled in the `strict-dem` profile.
- Repeat-aware contract table for all production checks (`docs/checks.md`).
- Vacuity disclosure in the report layer: a DEM with no error mechanisms now reports `[vacuous]` (and `is_vacuous` in the JSON and SARIF outputs) instead of reading as a clean audit. Report-layer only — no new check, no severity change, and no exit-code change.

### Changed

- `duplicates` now identifies groups whose merged signatures match while their
  `^` decomposition structures differ, and includes per-group details in
  `counter_example_data`.
- Reports retain the selected profile in text, JSON, and SARIF output.
- CLI input errors state that no static checks ran; string/path disambiguation
  now handles filesystem errors from path probing.
- Coordinate-coverage disclosure verified for experimental coordinate-consuming checks.
- `null_mechanism` evaluates repeat templates rather than expanding the repeat body, and reports `instance_count` alongside `mechanisms` in `counter_example_data`.

### Known limitations

- `duplicates` remains a warning for matching merged signatures. Mixed
  decomposition details clarify when those signatures may represent distinct
  fault paths.
- The matched shift-left simulation benchmark is deferred to v0.3 (technical
  debt item 52); no full-corpus shift-left index is claimed.

## [0.2.2] — 2026-09-03

Agent-facing output contract and validation-corpus expansion. No new production checks; no changes to the public check API, severities, or exit-code semantics.

### Added

- Stable machine-readable output contract: each production check documents the exact keys and value types of its `counter_example_data` dict (`docs/checks.md`, §"Machine-readable output contract (stable)").
- `PropertyResult.hint: str | None` (additive, default `None`): optional remediation hint on failed checks, phrased as hypotheses. Rendered in text output (with an epistemic-boundary header and 88-column counter-example wrapping) and in SARIF `properties.hint`.
- Exit code 3 (unlintable input) documented in the exit-code contract alongside 0/1/2 (README, copilot instructions, `docs/cli.md`).
- Applicability status semantics: `emlint.check`/CLI now distinguish a *declared unsupported circuit role* (plain `skipped`, exit-neutral) from *missing required context* on deterministic checks (`inconclusive`, contributes to exit 2 — anti-masking preserved). Warning-severity checks keep the exit-neutral skip in both cases. An explicit `complete_syndrome=True` context claim re-enables `detectability`.
- `duplicates` rescope: honest "signature collision" message with `location_count` in `counter_example_data`, a remediation hint (XOR-fused probability), and a `dem_assembly` context gate that selects the claim matching the declared DEM origin (monolithic vs concatenated).

### Known false positives and status

- `duplicates` (warning) reports graphlike-decomposition signature sharing on clean `decompose_errors=True` DEMs; the `dem_assembly` context gate and the `graphlike-decoder` profile context reframe the message. Unchanged verdict semantics.

## [0.2.1] — 2026-08-26

Incremental feature and hardening release: CLI/output-format features, project-level configuration, applicability profiles, and validation hardening. No new production checks; no changes to the public check API, severities, or exit-code semantics.

### Added

- `--only NAMES` / `--ignore NAMES` check selection on the CLI (`--check` retained as a backward-compatible alias for `--only`; passing both is rejected).
- `--format sarif`: SARIF 2.1.0 output. Every check becomes a rule; only failed checks become results.
- Project-level configuration: the nearest `pyproject.toml` may contain a `[tool.emlint]` table with keys `only`, `ignore`, `format`, and `severity`. Command-line options override project settings.
- Applicability profiles (`emlint/profiles.py`) via `--profile`/`--context` on the CLI, `[tool.emlint] profile`/`context` keys, and `emlint.check(..., context=..., profile=...)`. Initial profiles: `strict-dem`, `graphlike-decoder`, `surface-code-circuit`, `subsystem-code`. Opt-in: with no declared context or profile, behavior is unchanged.
- `PropertyResult.status` reports disabled, skipped, and inconclusive checks explicitly. Skipped/inconclusive results are visible in text and JSON, excluded from SARIF, and exit-code neutral (the 0/1/2 contract is preserved).
- Repeat-aware diagnostics: `detectability`, `probability_bounds`, `duplicates`, and `correctability` report expanded instance counts (with `instance_count` / `signature_count` in `counter_example_data`). Verdicts are unchanged.
- Frontend: `ErrorMechanism.decomposition_hints` preserves `^`-separated decomposition components from Stim DEMs.
- Experimental: `hook_errors` and `bulk_temporal_span` warning heuristics; stdlib-only graph helpers replacing the undeclared `networkx` dependency in `experimental/checks.py`. Distance-certificate prototypes (`experimental/boundary_signatures.py`, `experimental/css_boundary_signatures.py`) are research artifacts, not shipped checks.
- Validation corpus: stim-generated DEMs pinned by manifest hashes with a byte-reproducibility guard test (`tests/test_corpus_regenerable.py`); external-library DEMs and manifests tracked under `notes/audits/validation/raw/dems/`.

### Changed

- `duplicates` findings (structural and fused) are uniformly `warning` severity.
- CI matrix and tag-triggered release workflow added (`.github/workflows/ci.yml`, `.github/workflows/release.yml`); non-blocking lint workflow over the regression corpus.

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

[0.2.4]: https://github.com/MathysRennela/emlint/releases/tag/v0.2.4
[0.2.3]: https://github.com/MathysRennela/emlint/releases/tag/v0.2.3
[0.2.2]: https://github.com/MathysRennela/emlint/releases/tag/v0.2.2
[0.2.1]: https://github.com/MathysRennela/emlint/releases/tag/v0.2.1
[0.2.0]: https://github.com/MathysRennela/emlint/releases/tag/v0.2.0
[0.1.2]: https://github.com/MathysRennela/emlint/releases/tag/v0.1.2
[0.1.1]: https://github.com/MathysRennela/emlint/releases/tag/v0.1.1
[0.1.0]: https://github.com/MathysRennela/emlint/releases/tag/v0.1.0
