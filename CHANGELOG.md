# Changelog

All notable changes to emlint are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

---

## [0.1.1] — 2026-04-08

### Changed

- Quality of life improvements to the presentation of counter-examples.
- Minor optimizations to the checks implemented in v0.1.1.

---

## [0.1.0] — 2026-03-26

### Added

**Production checks** (all in `emlint/checks.py`, registered in `ALL_CHECKS`):

| Check | What it catches | Severity |
|---|---|---|
| `detectability` | Error mechanisms that flip observables but trigger no detectors (undetectable logical errors) | error |
| `sensitivity` | Detectors never triggered by any error mechanism (dead / orphaned detectors) | warning |
| `observable_coverage` | Logical observables never flipped by any error mechanism (masked logical qubits) | error |
| `probability_bounds` | Error probabilities outside `(0, 0.5]` — zero, negative, NaN, or `> 0.5` | error |
| `duplicates` | Error mechanisms sharing the same `(detectors, observables)` signature (double-counted fault paths) | warning |
| `correctability` | Syndromes mapping to more than one distinct observable set (decoder ambiguity) | warning |

**CLI** (`emlint check`):
- `emlint check <path|string>` — run all checks, exit 0/1/2
- `--format text|json` — machine-readable JSON output supported
- `--check <names>` — comma-separated subset of checks
- `--severity error|warning` — filter reported findings by minimum severity
- Exit codes: `0` all pass, `1` any `error`-severity failure, `2` warnings only

**Python API**:
- `emlint.check(source)` — accepts `stim.DetectorErrorModel`, `pathlib.Path`, or raw DEM string
- `emlint.format_text(report)` / `emlint.format_json(report)` — formatting helpers
- `ErrorModel`, `Report`, `CheckFn`, `PropertyResult` — public data model

**Stim frontend** (`emlint/frontends.py`):
- `from_stim_dem(dem)` — converts `stim.DetectorErrorModel` to `ErrorModel`
- `from_dem(source)` — accepts path or string, parses via stim

**Test suite**:
- Unit tests for all 6 production checks: passing and failing cases, counter-example content
- Integration tests on `stim.Circuit.generated` surface codes (d=3, 5, 7) and repetition codes
- Stim integration tests with `decompose_errors=False` and `decompose_errors=True`

### Known false positives

**`correctability` with `decompose_errors=True`**

When a DEM is generated with `stim`'s `decompose_errors=True`, hyperedge error
mechanisms are decomposed into weight-2 sub-mechanisms. This decomposition can
create pairs of sub-mechanisms that share the same detector set but differ in
which observables they flip — a syndrome collision that does not exist in the
original hyperedge model.

*Mitigation*: suppress with `--severity error` in CI (correctability is
`warning`-severity and will not break the build). Use `decompose_errors=False`
when running emlint if you want a clean `correctability` result with no artefacts.
The check message includes a note about this artefact when it fires.

**`duplicates` at code boundaries in some CSS code families**

An X error and a Y error on the same data qubit at a repetition code boundary
can each produce the same detector set and flip the same observable. This is
legitimate physics (they are degenerate fault paths), not a DEM assembly bug.
The `duplicates` check fires at `warning` severity and correctly reports the
XOR-fused probability — the warning is accurate but may not require user action
in degenerate code families.

*Mitigation*: suppress with `--severity error` in CI.

### Breaking changes

None. This is the initial release.

### Dependencies

- Python ≥ 3.10
- stim ≥ 1.14

---

[0.1.1]: https://github.com/MathysRennela/dem-linter/releases/tag/v0.1.1
[0.1.0]: https://github.com/MathysRennela/dem-linter/releases/tag/v0.1.0
