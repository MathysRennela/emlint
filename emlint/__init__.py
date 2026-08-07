from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import cast

import stim

from emlint import frontends
from emlint.checks import (
    ALL_CHECKS,
    check_correctability,
    check_detectability,
    check_duplicates,
    check_observable_coverage,
    check_probability_bounds,
    check_sensitivity,
)
from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock
from emlint.report import CheckFn, Report, format_json, format_text

_SCOPE_LOCAL_CHECKS = {
    check_detectability,
    check_probability_bounds,
    check_observable_coverage,
    check_sensitivity,
}

_CROSS_SCOPE_CHECKS = {
    check_duplicates,
    check_correctability,
}


def _is_optimized_builtin(name: str, fn: CheckFn) -> bool:
    """Return whether *fn* is an unwrapped built-in eligible for fast routing."""
    return (
        name in ALL_CHECKS
        and fn is ALL_CHECKS[name]
        and fn in (_SCOPE_LOCAL_CHECKS | _CROSS_SCOPE_CHECKS)
    )


class _FlattenCache:
    """Own one lazy immutable flattened result for a dispatcher invocation."""

    def __init__(
        self,
        model: ErrorModel,
        flat: tuple[ErrorMechanism, ...] | None = None,
    ) -> None:
        """Bind the cache to the source model without flattening it yet."""
        self._model = model
        self._flat = flat

    def get(self) -> tuple[ErrorMechanism, ...]:
        """Compute the flat tuple once and return the shared immutable result."""
        if self._flat is None:
            self._flat = tuple(self._model._flatten_unchecked())
        return self._flat


class _ReadOnlyModelView:
    """Immutable check view with optional shared flattened storage.

    Built-ins share this view because repeat expansion is expensive and the
    production checks are read-only. Custom checks continue to receive
    defensive copies because arbitrary user code cannot be trusted with shared
    dispatcher state.
    """

    detectors: frozenset[int]
    observables: frozenset[int]
    error_mechanisms: tuple[ErrorMechanism | RepeatBlock, ...]
    detector_coords: Mapping[int, tuple[float, ...]]
    _source: ErrorModel
    _cache: _FlattenCache | None
    _validated: bool
    _repeat_templates: tuple | None
    _cross_scope_reduction: object | None

    _READ_ONLY_FIELDS = frozenset(
        {"detectors", "observables", "error_mechanisms", "detector_coords"}
    )

    def __init__(
        self,
        model: ErrorModel,
        mechanisms: tuple[ErrorMechanism | RepeatBlock, ...],
        cache: _FlattenCache | None = None,
        validated: bool = False,
    ) -> None:
        object.__setattr__(self, "detectors", frozenset(model.detectors))
        object.__setattr__(self, "observables", frozenset(model.observables))
        object.__setattr__(self, "error_mechanisms", mechanisms)
        object.__setattr__(
            self, "detector_coords", MappingProxyType(dict(model.detector_coords))
        )
        object.__setattr__(self, "_source", model)
        object.__setattr__(self, "_cache", cache)
        object.__setattr__(self, "_validated", validated)
        object.__setattr__(self, "_repeat_templates", None)
        object.__setattr__(self, "_cross_scope_reduction", None)

    def __setattr__(self, name: str, value: object) -> None:
        if name in self._READ_ONLY_FIELDS and hasattr(self, name):
            raise AttributeError(f"{name} is read-only")
        object.__setattr__(self, name, value)

    def _validate_tree(self) -> None:
        """Validate the source tree unless dispatch already validated it."""
        if not self._validated:
            self._source._validate_tree()
            object.__setattr__(self, "_validated", True)

    def iter_flattened(self):
        """Lazily yield absolute mechanisms from the source model."""
        return self._source.iter_flattened()

    def flattened(self) -> tuple[ErrorMechanism, ...]:
        """Return cached expanded mechanisms or the already-flat mechanisms."""
        if self._cache is not None:
            return self._cache.get()
        return cast(tuple[ErrorMechanism, ...], self.error_mechanisms)


def _defensive_model(
    model: ErrorModel, mechanisms: list[ErrorMechanism | RepeatBlock]
) -> ErrorModel:
    return dataclasses.replace(
        model,
        detectors=set(model.detectors),
        observables=set(model.observables),
        error_mechanisms=list(mechanisms),
        detector_coords=dict(model.detector_coords),
    )


__all__ = [
    "ALL_CHECKS",
    "CheckFn",
    "ErrorModel",
    "Report",
    "check",
    "format_json",
    "format_text",
]


def check(
    source: stim.DetectorErrorModel | str | Path,
    checks: dict[str, CheckFn] | None = None,
) -> Report:
    """Run checks against *source* and return a Report.

    Parameters
    ----------
    source:
        A ``stim.DetectorErrorModel``, a ``pathlib.Path`` or string path to a
        ``.dem`` file, or a raw DEM string. Existing string paths are retained
        for backward compatibility; use an explicit ``Path`` when the input
        could be ambiguous.
    checks:
        Dict of ``{name: check_fn}`` to run.  Defaults to ``ALL_CHECKS``.

    Raises
    ------
    FileNotFoundError
        If *source* is a ``Path`` or string path that does not exist on the
        filesystem.
    OSError
        If a *Path* or string path cannot be read, including directory input.
    ValueError
        If the DEM text (from a file or a raw string) cannot be parsed by
        ``stim``.
    TypeError
        If *source* is not a ``stim.DetectorErrorModel``, ``pathlib.Path``, or
        ``str``.

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
        # Preserve the established string-path API while allowing raw DEM text.
        # Explicit Path objects remain preferable when a string could be either
        # a valid DEM or an existing filename.
        path = Path(source)
        if path.exists():
            text = path.read_text()  # OSError propagates to the caller
        else:
            text = source
        try:
            dem = stim.DetectorErrorModel(text)
        except Exception as exc:
            raise ValueError(f"Failed to parse DEM: {exc}") from exc
    else:
        raise TypeError(
            f"Unsupported source type {type(source).__name__}. "
            "Pass a stim.DetectorErrorModel, a path to a .dem file, "
            "or a raw DEM string."
        )

    model = frontends.from_stim_dem(dem)
    has_repeats = any(isinstance(item, RepeatBlock) for item in model.error_mechanisms)
    model._validate_tree()
    use_flattened_path = not has_repeats

    needs_cross_scope_cache = has_repeats or any(
        _is_optimized_builtin(name, fn) and fn in _CROSS_SCOPE_CHECKS
        for name, fn in checks.items()
    )
    cache = _FlattenCache(model) if needs_cross_scope_cache else None
    proxy = None
    flat_model = None
    if use_flattened_path:
        mechanisms = (
            cache.get()
            if cache is not None
            else cast(tuple[ErrorMechanism, ...], tuple(model.error_mechanisms))
        )
        flat_model = _ReadOnlyModelView(model, mechanisms, cache, validated=True)
    elif cache is not None:
        proxy = _ReadOnlyModelView(
            model, tuple(model.error_mechanisms), cache, validated=True
        )
    results = []
    for name, fn in checks.items():
        is_exact_builtin = _is_optimized_builtin(name, fn)
        if is_exact_builtin:
            if use_flattened_path:
                assert flat_model is not None
                results.append(fn(flat_model))
            else:
                assert proxy is not None
                results.append(fn(proxy))
        elif use_flattened_path:
            assert flat_model is not None
            results.append(
                fn(_defensive_model(model, list(flat_model.error_mechanisms)))
            )
        else:
            assert cache is not None
            results.append(fn(_defensive_model(model, list(cache.get()))))
    return Report(
        results=results,
        num_detectors=len(model.detectors),
        num_observables=len(model.observables),
        num_error_mechanisms=len(model.error_mechanisms),
    )
