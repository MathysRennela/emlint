# Contributing to emlint

emlint is a static linter for Detector Error Models (DEMs) — the noise format
used by [stim](https://github.com/quantumlib/Stim) in quantum error-correction.

**The correctness bar is higher than for typical software.** A check that passes
a buggy DEM (a false negative) is a correctness bug in emlint itself. The bug
may not surface until 10⁶ simulation shots (≈45 min) — or until a paper is
submitted. A silent wrong answer is worse than a crash.

Every contribution must satisfy the gates in this document before merging.

## Contents

- [Development setup](#development-setup)
- [Project architecture](#project-architecture)
- [Adding a new check](#adding-a-new-check)
- [Test requirements](#test-requirements)
- [Promoting an experimental check](#promoting-an-experimental-check)
- [Code quality gates](#code-quality-gates)
- [Exit code contract](#exit-code-contract)
- [Roadmap and versioning](#roadmap-and-versioning)

## Onboarding target

**≤30 min to first PR.** The development setup, canonical check signature, and test
helpers are designed so a new contributor can clone, run the test suite, and submit
a passing check within a single sitting.

## External contributor entry points

Well-defined, modular tasks suitable for external contributors:

- **Individual checks** — implement a check from `experimental/` with a clear spec and test cases.
- **DEM artefact generation** — generate DEMs from external compilers and run false-positive audits.
- **Documentation** — tutorial notebooks, compatibility catalogue entries, extension package templates.
- **Test infrastructure** — Hypothesis property-based tests, performance benchmarks.

Contributions are submitted via pull request and reviewed by a core developer for
alignment with the correctness standards and architectural guidelines in this document.

---

## Development setup

Create an isolated environment and install the development dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pip install ty
```

Run the core quality gates from the repository root:

```bash
.venv/bin/python -m pytest -W error
black --check .
ty check
```

Run the CLI against a DEM file or raw DEM text with the `check` subcommand:

```bash
emlint check examples/fixed.dem
emlint check 'error(0.01) D0 L0
detector D0'
```

---

## Project architecture

The pipeline is strictly layered. Each layer may only import from layers below
it. Checks never call frontends; frontends never call checks.

```
stim.DetectorErrorModel / .dem file / raw string
    └─ emlint/frontends.py    → ErrorModel
        └─ emlint/checks.py   → PropertyResult  (one per check)
            └─ emlint/report.py   → Report
                └─ emlint/__init__.py / emlint/cli.py  → user output
```

Key types:

| Type | Defined in | Role |
|---|---|---|
| `ErrorMechanism` | `model.py` | Frozen: `probability: float`, `detectors: frozenset[int]`, `observables: frozenset[int]` |
| `RepeatBlock` | `model.py` | Frozen tree node for `REPEAT N { ... }` DEM blocks |
| `ErrorModel` | `model.py` | Frontend-agnostic container; all checks operate on this |
| `PropertyResult` | `report.py` | Output of one check function |
| `Report` | `report.py` | Aggregated results + DEM statistics |
| `CheckFn` | `report.py` | `Callable[..., PropertyResult]` — the canonical check type |
| `ALL_CHECKS` | `checks.py` | Public registry `{name: fn}` consumed by CLI and `emlint.check()` |

**Repeat-aware evaluation.** `model.flattened()` recursively expands all
`RepeatBlock` trees and returns a flat `list[ErrorMechanism]` with absolute
detector indices. It remains the executable reference and exact fallback API.
`model.iter_flattened()` provides lazy exact expansion.

Built-in production checks use the narrowest sound representation:

- `detectability` and `probability_bounds` inspect repeat templates;
- `observable_coverage` unions template observable supports;
- `sensitivity` uses exact indexed arithmetic-progression support for supported
  repeat structures and falls back exactly when necessary;
- `duplicates` and `correctability` share one exact lazy flattened reduction.

Never iterate `model.error_mechanisms` as though every item were an
`ErrorMechanism`: it also contains `RepeatBlock` nodes. A new check must either
use `model.flattened()`/`model.iter_flattened()` or explicitly handle the full
repeat tree. If a symbolic optimization is proposed, it requires an exact
flattened-oracle comparison and a documented soundness argument.

---

## Adding a new check

New checks follow a two-stage path: **experimental first**, production only
after promotion criteria are met (see
[Promoting an experimental check](#promoting-an-experimental-check)).

### Stage 1 — Implement in `experimental/checks.py`

Use this exact signature:

```python
from __future__ import annotations

from emlint.model import ErrorModel
from emlint.report import PropertyResult

_MAX_SHOWN = 10  # module-level constant; never hardcode 10 inline


def check_<name>(model: ErrorModel, max_shown: int = _MAX_SHOWN) -> PropertyResult:
    """One-line summary of the property verified.

    Longer explanation of the physical/mathematical meaning and why a violation
    matters for decoding correctness.

    Property: formal statement, e.g. ∀m ∈ mechanisms, |det(m)| ≤ 2
    """
    # Use model.flattened() as the default exact oracle for a new check. A
    # repeat-aware implementation must use a sound template/summary path and
    # retain the exact fallback for unsupported shapes.
    violations = [mech for mech in model.flattened() if ...]

    if violations:
        lines = [... for mech in violations[:max_shown]]
        counter = "; ".join(lines)
        if len(violations) > max_shown:
            counter += f" (and {len(violations) - max_shown} more)"

        return PropertyResult(
            name="<name>",          # must match the key in LOCAL_CHECKS
            passed=False,
            severity="warning",     # or "error" — justify against BUG_TAXONOMY.md
            message=f"Found {len(violations)} ...",
            counter_example=counter,                  # required: non-None
            counter_example_data={"mechanisms": [...]},  # required: non-None
        )

    return PropertyResult(
        name="<name>",
        passed=True,
        severity="warning",         # use the check's documented severity policy
        message="All mechanisms ...",
        # counter_example and counter_example_data omitted (default None)
    )
```

Rules:

- **Use the exact flattened oracle by default**, and never iterate
  `model.error_mechanisms` as though it contained only mechanisms. A sound
  repeat-aware check may use templates or exact summaries, but must retain the
  flattened fallback for unsupported shapes and prove oracle equivalence.
- **`counter_example` and `counter_example_data` must both be non-None when
  `passed=False`.** A check that sets either to `None` on failure is itself a
  bug; callers and the test suite depend on both fields being populated.
- Preserve the check's documented severity policy in both branches. Most checks
  have a fixed severity; `probability_bounds` may classify unphysical values as
  `error` and values above `0.5` as `warning`, and must keep that distinction
  documented and tested.
- Truncate human-readable violation lists to `max_shown` items and append
  `(and N more)` when truncated. Structured diagnostics may use a check-specific
  bounded representation, but must retain a concrete witness for every rendered
  failure.
- The `name` field must exactly match the key used in `LOCAL_CHECKS`.
- Justify `"error"` vs `"warning"` against the taxonomy in
  [notes/design/BUG_TAXONOMY.md](notes/design/BUG_TAXONOMY.md).

`experimental/` may use `networkx`. `emlint/checks.py` must not import anything
outside the standard library and `stim`.

### Stage 2 — Write `tests/test_check_<name>.py`

See [Test requirements](#test-requirements) below.

### Stage 3 — Register during promotion

When the check graduates to production (see
[Promoting an experimental check](#promoting-an-experimental-check)), move it to
`emlint/checks.py` and add it to the registry:

```python
LOCAL_CHECKS: dict[str, CheckFn] = {
    # existing entries …
    "<name>": check_<name>,
}
# ALL_CHECKS = dict(LOCAL_CHECKS) — propagates automatically; do not touch it.
```

---

## Test requirements

Every **production** check — and every check being promoted from experimental —
must have a complete test suite in `tests/test_check_<name>.py`.

### File structure

Use these exact section comments:

```python
# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Failing cases
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Hypothesis: property-based tests
# ---------------------------------------------------------------------------
```

### Shared helpers

Import from `tests/helpers.py` (it is on `pythonpath` via `pyproject.toml`):

```python
from helpers import _mech, _model, assert_failed
```

| Helper | Purpose |
|---|---|
| `_mech(p, detectors, observables)` | Builds an `ErrorMechanism` |
| `_model(*mechs)` | Builds an `ErrorModel` with auto-derived detector/observable sets |
| `assert_failed(result)` | Asserts `passed=False` and both counter-example fields non-None; returns a narrowed `FailedResult` type |

Prefer these helpers over constructing dataclasses directly. Do not add a `stim`
import to passing-case tests — they must run without the stim integration layer.

### Passing cases

Required coverage:

- Empty model.
- A model that satisfies the property with the minimal set of mechanisms.
- Boundary conditions and edge cases.

Assertions:

```python
result = check_<name>(model)
assert result.passed
assert result.name == "<name>"
assert result.severity == "error"   # or "warning"
assert result.counter_example is None
assert result.counter_example_data is None
```

### Failing cases

Each failing test must assert **all three** of the following.
Asserting only `passed=False` is not sufficient; the counter-example must
identify the specific offending mechanism, not just report a count.

```python
result = check_<name>(model)
assert not result.passed
assert result.severity == "error"   # or "warning"
assert "<offending mechanism detail>" in result.counter_example
```

Use `assert_failed` to access `counter_example` and `counter_example_data`
without type-checker noise when inspecting their contents:

```python
r = assert_failed(check_<name>(model))
assert "D0" in r.counter_example
assert r.counter_example_data["mechanisms"] == ["error(0.1) D0 L0"]
```

### Hypothesis tests

At least one `@given` test per invariant direction:

```python
from hypothesis import given
import hypothesis.strategies as st


@given(
    dets=st.frozensets(st.integers(0, 10), min_size=1),
    obs=st.frozensets(st.integers(0, 5)),
    p=st.floats(min_value=1e-4, max_value=0.5),
)
def test_<invariant_direction>(dets, obs, p):
    ...
```

### Stim integration

Add at least one case to `tests/test_stim_integration.py` exercising the check
on `stim.Circuit.generated(...)` surface code DEMs at d=3 and d=5.

---

## Promoting an experimental check

A check in `experimental/checks.py` is not production until all of the following
are satisfied:


1. **Full test suite** (see [Test requirements](#test-requirements)) is passing, including Hypothesis tests and the stim integration case.
2. **Flattened-oracle equivalence is verified** — the check matches an independent flattened-oracle specification (an entry in `tests/test_check_oracles.py`), and any repeat-aware or symbolic path retains exact flattened fallback with a documented soundness argument.
3. **Severity is justified** — `"error"` vs `"warning"` is argued against the
   taxonomy in [notes/design/BUG_TAXONOMY.md](notes/design/BUG_TAXONOMY.md) and
   reviewed by a maintainer.
4. **Shift-invariance is documented** (for v0.2 repeat-aware checks) — the check
   docstring states whether the predicate is shift-invariant and why, per the
   criterion in [notes/DEVELOPMENT_ROADMAP.md](notes/DEVELOPMENT_ROADMAP.md).

The promotion path is:
`experimental/checks.py` → full test suite → roadmap milestone sign-off →
move to `emlint/checks.py` + register in `LOCAL_CHECKS`.

---

## Code quality gates

All of the following must pass before any merge to `main`:

```bash
pytest -W error           # zero failures, zero warnings
black --check .           # no formatting diffs
ty check                  # no type errors
```

Additional gates:

- `from __future__ import annotations` must appear at the top of every module.
- The version string in `pyproject.toml` is the single source of truth; the CLI
  reads it via `importlib.metadata.version('emlint')`.
- `emlint check examples/fixed.dem` must exit `0`.
- `emlint check examples/buggy.dem` is a warning-only example and must exit `2`.
- `emlint check 'error(0) D0'` must exit `1` for an error-severity violation.
- Invalid input that cannot be linted must exit `3`.
- `emlint check --format json ...` must produce valid JSON with all documented
  report and result fields present.

See [notes/RELEASE_CHECKLIST.md](notes/RELEASE_CHECKLIST.md) for the current
release gates. The matched shift-left simulation benchmark is deferred to v0.3
(technical debt item 52 in `notes/TECHNICAL_DEBT.md`).

---

## Exit code contract

| Code | Meaning |
|---|---|
| `0` | All checks passed |
| `1` | At least one `error`-severity failure |
| `2` | Warnings only (`error` checks all passed, ≥1 `warning` check failed) |
| `3` | Input could not be linted (parse, file, or validation failure) |

This contract is stable. Downstream CI pipelines depend on these semantics.
Do not change it.

---

## Roadmap and versioning

| Version | Status | Core deliverables |
|---|---|---|
| v0.2.1 | shipped | CLI/output-format features, project config, profiles, hardening |
| v0.2.2 | shipped | Agent-facing output contract, remediation hints, corpus expansion |
| v0.2.3 | shipped | Disclosure hardening: `null_mechanism` promotion, vacuity disclosure, repeat-aware contract table |
| v0.2.4 | shipped | Maintainer-owned checks: `connectivity`, `boundary_symmetry`, `high_probability_mechanisms`; enhanced `duplicates`; `LOCAL_CHECKS`/`GLOBAL_CHECKS` registry split |
| v0.2.5 | next | `emlint equiv` Tier S equivalence baseline |
| gate-ready → distance-certified | — | promotion wave + false-positive audit; then opt-in `check_distance`, promoted at the distance-certified level (TQEC pipeline evidence deferred — `notes/DEFERRED.md` D5) |
| v0.4.0 | — | Extension API contract (proofs deferred post-v0.5; tutorial is v0.4.1) |
| v0.5.0 | — | Community contributions open, compatibility catalogue |

Per the roadmap, a release carries no date until its predecessor has shipped.

Full details and proof obligations: [notes/DEVELOPMENT_ROADMAP.md](notes/DEVELOPMENT_ROADMAP.md).
