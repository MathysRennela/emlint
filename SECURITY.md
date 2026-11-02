# Security policy

emlint is a command-line linter and Python library. It parses DEM text and
Stim-derived models; it does not run a service and handles no user data.

## Reporting a vulnerability

If you find a security problem (for example, unsafe parsing of untrusted DEM
input, arbitrary code execution, or a dependency issue), please do not open a
public issue. Report it privately through GitHub's private vulnerability
reporting ("Security" tab, then "Report a vulnerability") on this repository.

Reports about the correctness of a check (a false positive or false negative)
are not security issues. Open a normal issue for those, as described in
`CONTRIBUTING.md`.
