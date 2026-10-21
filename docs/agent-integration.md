# Agent integration guide

How to run emlint inside a coding agent loop: an agent authors or edits a DEM,
emlint reports, the agent fixes, and the loop repeats. This page is written for
machine consumers; the human-facing interpretation of findings lives in the
[check catalog](checks.md) and the [debugging guide](debugging.md).

## The loop

```
author/edit DEM  →  emlint check file.dem --format json  →  parse exit code
      ↑                                                        ↓
      └────────────── fix targeted mechanisms ←── findings + hints
```

A minimal loop:

```bash
emlint check candidate.dem --format json
```

Branch on the exit code:

| Exit | Meaning | Agent action |
|---|---|---|
| `0` | All checks passed (skips allowed, surfaced via `any_skipped`) | Proceed; optionally record `any_skipped` context |
| `1` | At least one `error`-severity finding | Fix before proceeding — this is a correctness bug in the DEM |
| `2` | Warnings only (or `inconclusive` results) | Review; warnings may be intentional (e.g. conditioned probabilities) |
| `3` | Unlintable input (unreadable, unparseable, invalid configuration) | Fix the input/format — this is **not** a findings result |

Exit `3` is the one agents most often misclassify: it means emlint could not
evaluate the input at all, so "no findings" carries no evidence. Treat it like
a parse failure in your own tooling, not like a clean report.

## Reading the JSON report

`--format json` emits a stable top-level shape:

```json
{
  "num_detectors": 0,
  "num_observables": 1,
  "num_error_mechanisms": 1,
  "disabled_checks": [],
  "applied_overrides": {},
  "unknown_instructions": [],
  "all_passed": false,
  "any_skipped": false,
  "is_vacuous": false,
  "has_errors": true,
  "has_warnings": false,
  "results": [ ... ]
}
```

`is_vacuous` is `true` when the DEM carries no error mechanisms. Every
mechanism-level check then had nothing to examine, so an all-green report
describes an *empty audit* rather than a clean DEM. Treat a vacuous report the
way you treat exit `3`: "no findings" carries no evidence. It carries no
severity, so the exit code is unchanged.

Each entry in `results` is one check verdict:

```json
{
  "name": "detectability",
  "passed": false,
  "severity": "error",
  "message": "Found 1 undetectable error mechanism instance(s) ...",
  "counter_example": "error(0.01) flips L0 but triggers 0 detectors",
  "counter_example_data": {
    "mechanisms": ["error(0.01) L0"],
    "instance_count": 1
  },
  "status": "verdict",
  "hint": "Hypothesis: an observable flip with no detector syndrome often ..."
}
```

Fields an agent should consume, in order:

1. **`status`** — `"verdict"`, `"skipped"`, or `"inconclusive"`. Only
   `"verdict"` results carry a pass/fail decision. `skipped` means the check
   was declared outside its applicability domain (e.g. `detectability` on a
   state-preparation DEM with `circuit_role=state_preparation`); `inconclusive`
   means required context was missing, so the check could not evaluate. Neither
   is a pass: a run that needed context and did not get it reports
   `inconclusive` (which contributes to exit `2` for error-severity checks) —
   never silently exit `0`.
2. **`severity`** — `error` findings are DEM bugs; `warning` findings are
   heuristic or intentional-pattern candidates.
3. **`counter_example_data`** — the structured finding. The per-check schema
   (exact keys and types) is contractual and documented in
   [checks.md §Machine-readable output contract](checks.md#machine-readable-output-contract-stable);
   additive changes only. Parse these keys, not the prose `message`.
4. **`hint`** — a remediation hypothesis, present only on failure and only for
   `detectability`, `sensitivity`, `duplicates`, and `correctability`. Hints are
   heuristic interpretations, **not root-cause verdicts**: use them to pick
   where to inspect, never as the fix itself.

## Prompt-ready contract examples

Findings an agent can act on directly (mechanism strings are the canonical
fix targets):

```json
{"name": "detectability", "passed": false, "severity": "error",
 "counter_example_data": {"mechanisms": ["error(0.01) L0"], "instance_count": 1}}
```
→ the mechanism `error(0.01) L0` flips observable `L0` with no detector
support; give it detector targets or remove the fault path.

```json
{"name": "probability_bounds", "passed": false, "severity": "error",
 "counter_example_data": {"mechanisms": ["error(nan) D0 D1"], "instance_count": 1}}
```
→ an unphysical probability; `error(0.0)` and `error(nan)` are always bugs.

```json
{"name": "duplicates", "passed": false, "severity": "warning",
 "counter_example_data": {"mechanisms": ["error(0.01) D3 D7", "error(0.02) D3 D7"],
                          "signature_count": 1, "location_count": 1}}
```
→ same signature twice; if both entries are the same fault path, XOR-fold the
probabilities (`p_eff = p1*(1-p2) + p2*(1-p1)`); if they are distinct fault
paths sharing a merged signature (common on `decompose_errors=True` output),
the finding is expected structure. Declare
`--context dem_assembly=concatenated` (or `monolithic`) when you know the DEM's
origin and the message will state the matching claim.

## Declaring context

If the agent knows what kind of DEM it is checking, declare it — undeclared
context is the main source of noise on non-memory DEMs:

```bash
emlint check prep.dem --context circuit_role=state_preparation
emlint check sub.dem --context circuit_role=state_preparation --context complete_syndrome=true
emlint check composed.dem --profile surface-code-circuit
```

- A declared role outside a check's applicability domain produces an explicit
  `skipped` result (exit-neutral), not a false error.
- `complete_syndrome=true` re-enables `detectability` on roles that would
  otherwise skip it.
- Profiles (`strict-dem`, `graphlike-decoder`, `surface-code-circuit`,
  `subsystem-code`) bundle check selection and context demands; see the
  [CLI reference](cli.md).

## Loop discipline

- **Bound iterations.** Cap fix→check cycles (e.g. 5). If exit `1` persists,
  escalate to a human rather than churning; a recurring error-severity finding
  usually indicates a wrong circuit invariant, not a wrong patch.
- **Re-run the full battery after each fix.** Do not accumulate deltas from
  partial runs; `--only`/`--ignore` are for triage, the final gate is the full
  check set.
- **Fix mechanisms, not messages.** Edit the DEM instruction named in
  `counter_example_data.mechanisms` (or the `conflicts` witnesses for
  `correctability`). Never edit a DEM to silence a warning you have not
  classified.
- **Exit `2` is a decision, not a failure.** Warnings (e.g. `p > 0.5`
  conditioned mechanisms, structural duplicates on `decompose_errors=True`
  output) may be correct for the model at hand. Record the classification in
  the loop transcript so the decision is auditable.
- **DEM findings are not circuit correctness.** emlint verifies properties of
  the DEM as written; it cannot certify that the DEM matches the circuit's
  intended semantics. See [limitations.md](limitations.md).

## Programmatic use

For in-process loops, `emlint.check()` accepts the same knobs and returns a
`Report` of `PropertyResult` objects with the same fields as the JSON output:

```python
import emlint

report = emlint.check(
    dem_string_or_path, context={"circuit_role": "memory", "complete_syndrome": True}
)
if report.has_errors():
    for r in report.results:
        if r.status == "verdict" and not r.passed and r.severity == "error":
            print(r.name, r.counter_example_data, r.hint)
```

The `PropertyResult`/`Report` contract is stable: additive changes only.
Breaking changes require a major version bump.

### `all_passed()` is not a coverage claim

`Report.all_passed()` returns `True` when checks were **skipped** — a skipped
check is not a failed check. This is consistent with the exit-code contract,
where a plain skip is exit-neutral, but it is a trap for an embedding caller:

```python
report = emlint.check(dem, context={"circuit_role": "state_preparation"})
report.all_passed()   # True
report.any_skipped    # True — detectability never ran
```

If your gate must know whether the battery actually ran, combine the two:

```python
if report.all_passed() and not report.any_skipped:
    ...  # every enabled check emitted a verdict
```

`inconclusive` results also leave `all_passed()` `True` while forcing exit `2`, so
a caller reading only `all_passed()` will treat a DEM that no deterministic check
could evaluate as a clean run.