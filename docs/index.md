# emlint

**stim simulates. sinter samples. emlint verifies.**

emlint is a static linter for [Stim](https://github.com/quantumlib/Stim)
Detector Error Models (DEMs). It finds structural problems before simulation.

## Quick start

```bash
pip install emlint
emlint check circuit.dem
```

A failing result includes a counter-example identifying the relevant mechanism,
detector, or observable. Select checks with `--only`/`--ignore`, or emit SARIF
for code-scanning tools:

```bash
emlint check circuit.dem --only detectability,sensitivity
emlint check circuit.dem --format sarif > emlint.sarif
```

## Documentation

| Guide | Use it for |
|---|---|
| [CLI reference](cli.md) | Commands, options, output, and exit codes |
| [Check catalog](checks.md) | What the six checks detect and how to interpret findings, plus the machine-readable output contract |
| [Debugging guide](debugging.md) | Check-specific causes and investigation steps |
| [Agent integration guide](agent-integration.md) | Running emlint in a coding-agent fix-loop: exit-code handling, JSON contract, context declaration |
| [Formal grounding](formal-grounding.md) | DEM vocabulary and formal properties |
| [Limitations](limitations.md) | Scope, warnings, repeat blocks, and provisional behavior |

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | All checks passed |
| `1` | At least one error-severity finding |
| `2` | Warnings only |
| `3` | Unlintable input (unreadable or unparseable) |

Treat exit code `3` as an input failure, not as findings: an agent loop that
parses the report on exit `3` would reason about a DEM that emlint never saw.

## Epistemic boundary

emlint analyzes DEMs only. Its findings establish structural properties of the
DEM itself; they do not establish that the underlying circuit is semantically
correct, nor that a decoder succeeds. Circuit-level verification (e.g. with
`stim`) remains necessary.