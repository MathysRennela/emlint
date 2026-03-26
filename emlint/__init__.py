from __future__ import annotations

from pathlib import Path

import stim

from emlint import frontends
from emlint.checks import ALL_CHECKS
from emlint.model import ErrorModel
from emlint.report import CheckFn, Report, format_json, format_text

__all__ = ["check", "ErrorModel", "Report", "CheckFn", "ALL_CHECKS", "format_text", "format_json"]


def check(
    source: stim.DetectorErrorModel | str | Path,
    checks: dict[str, CheckFn] | None = None,
) -> Report:
    """Run checks against *source* and return a Report.

    Parameters
    ----------
    source:
        A ``stim.DetectorErrorModel``, a ``pathlib.Path`` to a ``.dem`` file,
        a string path to a ``.dem`` file, or a raw DEM string.
    checks:
        Dict of ``{name: check_fn}`` to run.  Defaults to ``ALL_CHECKS``.

    Examples
    --------
    ::

        report = emlint.check(stim.Circuit.generated(...).detector_error_model())
        print(report.all_passed())
    """
    if checks is None:
        checks = ALL_CHECKS

    if isinstance(source, stim.DetectorErrorModel):
        dem = source
    elif isinstance(source, Path):
        text = source.read_text()  # FileNotFoundError / PermissionError propagate
        try:
            dem = stim.DetectorErrorModel(text)
        except Exception as exc:
            raise ValueError(f"Failed to parse DEM: {exc}") from exc
    elif isinstance(source, str):
        path = Path(source)
        if path.exists():
            text = path.read_text()  # PermissionError propagates
            try:
                dem = stim.DetectorErrorModel(text)
            except Exception as exc:
                raise ValueError(f"Failed to parse DEM: {exc}") from exc
        else:
            try:
                dem = stim.DetectorErrorModel(source)
            except Exception as exc:
                raise ValueError(f"Failed to parse DEM: {exc}") from exc
    else:
        raise TypeError(
            f"Unsupported source type {type(source).__name__}. "
            "Pass a stim.DetectorErrorModel, a path to a .dem file, "
            "or a raw DEM string."
        )

    model = frontends.from_stim_dem(dem)
    results = [fn(model) for fn in checks.values()]
    return Report(
        results=results,
        num_detectors=len(model.detectors),
        num_observables=len(model.observables),
        num_error_mechanisms=len(model.error_mechanisms),
    )
