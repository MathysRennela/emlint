"""Shared test helpers for the dem-linter test suite.

Import these directly in test files:
    from helpers import _mech, _model
"""
from __future__ import annotations

from emlint.model import ErrorMechanism, ErrorModel


def _mech(
    p: float,
    detectors: frozenset[int] = frozenset(),
    observables: frozenset[int] = frozenset(),
) -> ErrorMechanism:
    return ErrorMechanism(probability=p, detectors=detectors, observables=observables)


def _model(*mechs: ErrorMechanism) -> ErrorModel:
    return ErrorModel(
        detectors={d for m in mechs for d in m.detectors},
        observables={o for m in mechs for o in m.observables},
        error_mechanisms=list(mechs),
    )
