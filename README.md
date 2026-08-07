# emlint

<div align="center">
  <img src="docs/images/emlint_logo_with_name.png" alt="emlint logo" width="350">
</div>

[![PyPI](https://img.shields.io/pypi/v/emlint)](https://pypi.org/project/emlint/)

**stim simulates. sinter samples. emlint verifies.**

emlint is a static linter for [Stim](https://github.com/quantumlib/Stim)
Detector Error Models (DEMs). It finds structural problems before simulation.

> **v0.2 is preliminary.** The user-facing behavior is usable, but internal APIs
> and implementation details may change before v1.0.

## Quick start

Install emlint:

```bash
pip install emlint
```

Lint a DEM file or raw DEM text:

```bash
emlint check circuit.dem
emlint check 'error(0.01) D0 L0
detector D0'
```

A failing result includes a counter-example identifying the relevant mechanism,
detector, or observable. For command options and exit codes, see the [CLI
reference](docs/cli.md).

## Python

```python
import emlint
import stim

circuit = stim.Circuit.generated(
    "surface_code:rotated_memory_z",
    distance=3,
    rounds=3,
    after_clifford_depolarization=0.001,
)
report = emlint.check(circuit.detector_error_model())
print(emlint.format_text(report))
```

`emlint.check()` also accepts a raw DEM string or an explicit `pathlib.Path`.

## Documentation

| Guide | Use it for |
|---|---|
| [CLI reference](docs/cli.md) | Commands, options, output, and exit codes |
| [Check catalog](docs/checks.md) | What the six checks detect and how to interpret findings |
| [Debugging guide](docs/debugging.md) | Check-specific causes and investigation steps |
| [Formal grounding](docs/formal-grounding.md) | DEM vocabulary and formal properties |
| [v0.2 limitations](docs/limitations.md) | Scope, warnings, repeat blocks, and provisional behavior |

## CI

For a minimal GitHub Actions setup, install emlint and run it on changed DEM
files:

```yaml
- name: Install emlint
  run: pip install emlint
- name: Lint DEM files
  run: find . -name "*.dem" -print0 | xargs -0 -r -n1 emlint check
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, how to add a
check, test requirements, and quality gates.

## License

Apache 2.0
