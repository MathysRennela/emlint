# CLI reference

This page describes the stable command-line behavior of emlint v0.2.

## Command

```text
emlint check SOURCE [OPTIONS]
```

`SOURCE` is either a raw Detector Error Model (DEM) string or a path to a DEM
file. In shell usage, quote raw DEM strings. Existing file paths are accepted
both by the CLI and Python API; use an explicit `pathlib.Path` in Python when
an input could be ambiguous. A source that cannot be parsed or read is an input
failure, not a lint finding.

## Options

```text
--format text|json|sarif
--check NAME[,NAME...]
--only NAME[,NAME...]
--ignore NAME[,NAME...]
--severity error|warning
--version
--help
```

- `--format text` is the default human-readable output.
- `--format json` emits a JSON report suitable for scripts. Results include the
  check name, pass/fail status, severity, message, and optional counter-example
  fields.
- `--format sarif` emits a SARIF 2.1.0 report for code-scanning tools. Failed
  checks become SARIF results; passing checks remain in the rule catalog.
- `--check` runs only the named checks. It is retained as a backward-compatible
  alias for `--only`. Available production checks are listed in [the check
  catalog](checks.md).
- `--only` runs only the named checks, and `--ignore` removes named checks from
  the selected set. Both accept comma-separated names.
- `--severity error` hides warning findings from output. It does not change the
  underlying checks or suppress error-severity failures. If the selected report
  contains warnings but no errors, the CLI exits `0` because warnings were
  explicitly excluded from the requested severity.
- `--severity warning` includes both warning and error findings.

### Project-level settings

The nearest `pyproject.toml` (starting beside a DEM file, or in the current
working directory for raw DEM input) may contain a `[tool.emlint]` table:

```toml
[tool.emlint]
only = ["detectability", "sensitivity"]
ignore = ["duplicates"]
format = "sarif"
severity = "error"
```

The keys are `only`, `ignore`, `format`, and `severity`. Command-line options
override the corresponding project setting. `--check` and `only` cannot be used
together; use `--only` for new configurations.

## Exit codes

| Code | Meaning |
|---:|---|
| `0` | All selected checks passed. |
| `1` | At least one error-severity check failed. |
| `2` | Warning findings occurred, with no error-severity failures. |
| `3` | emlint could not read or parse the input. |

Exit code `3` is intentionally distinct from warning-only exit code `2`, so a
CI job cannot mistake an input failure for a non-blocking lint warning.

## CI guidance

Use the default severity when every error or warning should affect the job:

```yaml
- name: Lint DEM
  run: emlint check circuit.dem
```

Use `--severity error` when warnings are intentionally non-blocking. This keeps
warning findings out of the output and returns `0` when no error finding exists:

```yaml
- name: Lint DEM errors
  run: emlint check circuit.dem --severity error
```

Do not treat every nonzero result as equivalent: exit code `1` identifies an
error-severity finding, exit code `2` identifies warnings only, and exit code `3`
means the input could not be read or parsed.

## Examples

Check a file:

```bash
emlint check circuit.dem
```

Check a raw DEM:

```bash
emlint check 'error(0.01) D0 L0
detector D0'
```

Run a subset of checks:

```bash
emlint check circuit.dem --check detectability,sensitivity
```

Produce machine-readable output:

```bash
emlint check circuit.dem --format json
emlint check circuit.dem --format sarif > emlint.sarif
```

Select and exclude checks:

```bash
emlint check circuit.dem --only detectability,sensitivity
emlint check circuit.dem --ignore duplicates
```

Use only hard-error findings in CI output:

```bash
emlint check circuit.dem --severity error
```

## Python input distinction

The Python API accepts raw DEM strings, `pathlib.Path` objects, and existing
string paths for backward compatibility. Use `Path("circuit.dem")` when you
want file input to be unambiguous.
