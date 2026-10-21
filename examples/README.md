# Examples

Hand-written and generated DEM files for demonstrating emlint.

## Hand-written

- [`buggy.dem`](buggy.dem) — a d=5 surface code with a missing detector
  connection (`D17` declared but never triggered). `emlint check` flags it with
  a `sensitivity` warning naming `D17@(1,0,2)`.
- [`fixed.dem`](fixed.dem) — the same circuit with `D17` reconnected to its
  neighbours `D9` and `D18`. Every check passes.

## Generated

[`generate_examples.py`](generate_examples.py) produces additional DEMs that
exercise specific checks. Run it from the repo root:

```bash
python examples/generate_examples.py
```

It writes:

| File | Check exercised |
|---|---|
| `surface_code_d5_good.dem` | Baseline — all checks pass |
| `surface_code_d5_undetectable.dem` | `detectability` (error) |
| `surface_code_d5_dead_detector.dem` | `sensitivity` (warning) |
| `uncovered_observable.dem` | `observable_coverage` (error) |

The generated files are not committed; regenerate them as needed.