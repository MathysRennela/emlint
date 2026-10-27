"""Smoke tests for the experimental v0.2.4 candidate checks on the corpus.

These are *not* the deep-corpus analysis (which lives in
``notes/audits/FINDINGS_LEDGER.md``). They are a fast regression guard:

- the candidate checks must not raise on real corpus DEMs, and
- their repeat-aware path must agree with the explicitly flattened oracle
  (the same contract ``test_corpus_oracle.py`` enforces for production checks).

Only small corpus DEMs (<= 500 mechanisms) are exercised so the suite stays
fast; the bounded checks are O(C(n, k)) and would dominate runtime on the
large surface-code DEMs.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import stim

from emlint.frontends import from_stim_dem
from emlint.model import ErrorModel
from emlint.checks import check_connectivity
from experimental.checks import (
    check_bounded_multifault_detectability,
    check_undetectable_combination_ambiguity,
)

CORPUS_DIR = (
    Path(__file__).parent.parent / "notes" / "audits" / "validation" / "raw" / "dems"
)

_MAX_MECHANISMS = 500
_MAX_WEIGHT = 2


def _small_corpus_dems() -> list[Path]:
    if not CORPUS_DIR.is_dir():
        return []
    result: list[Path] = []
    for path in sorted(CORPUS_DIR.glob("*.dem")):
        try:
            dem = stim.DetectorErrorModel(path.read_text())
            model = from_stim_dem(dem)
        except Exception:  # noqa: BLE001
            continue
        if len(model.flattened()) <= _MAX_MECHANISMS:
            result.append(path)
    return result


def _flattened_model(source: ErrorModel) -> ErrorModel:
    return ErrorModel(
        detectors=set(source.detectors),
        observables=set(source.observables),
        error_mechanisms=list(source.flattened()),
        detector_coords=dict(source.detector_coords),
    )


_SMALL_DEMS = _small_corpus_dems()


@pytest.mark.parametrize("dem_path", _SMALL_DEMS, ids=lambda p: p.stem)
def test_experimental_checks_do_not_raise_on_small_corpus(dem_path: Path) -> None:
    dem = stim.DetectorErrorModel(dem_path.read_text())
    model = from_stim_dem(dem)
    # Must complete without raising; bounded checks use a small max_weight.
    check_connectivity(model)
    check_bounded_multifault_detectability(model, max_weight=_MAX_WEIGHT)
    check_undetectable_combination_ambiguity(model, max_weight=_MAX_WEIGHT)


@pytest.mark.parametrize("dem_path", _SMALL_DEMS, ids=lambda p: p.stem)
def test_experimental_repeat_aware_matches_flattened_on_small_corpus(
    dem_path: Path,
) -> None:
    dem = stim.DetectorErrorModel(dem_path.read_text())
    source = from_stim_dem(dem)
    flat = _flattened_model(source)

    checks = (
        lambda m: check_connectivity(m),
        lambda m: check_bounded_multifault_detectability(m, max_weight=_MAX_WEIGHT),
        lambda m: check_undetectable_combination_ambiguity(m, max_weight=_MAX_WEIGHT),
    )
    for check in checks:
        r_source = check(source)
        r_flat = check(flat)
        assert r_source.passed == r_flat.passed
        assert r_source.severity == r_flat.severity
        assert r_source.status == r_flat.status


def test_small_corpus_subset_is_nonempty() -> None:
    assert _SMALL_DEMS, f"no small corpus DEMs found under {CORPUS_DIR}"
