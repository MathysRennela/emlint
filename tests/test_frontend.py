"""Tests for emlint.frontends.from_stim_dem().

These tests exercise the translation layer directly, independent of any check.
A silent parsing bug here corrupts every downstream result.
"""
from __future__ import annotations

import stim
import pytest

from emlint.frontends import from_stim_dem


# ---------------------------------------------------------------------------
# Error instruction → ErrorMechanism
# ---------------------------------------------------------------------------

def test_single_error_probability():
    dem = stim.DetectorErrorModel("error(0.25) D0")
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 1
    assert model.error_mechanisms[0].probability == pytest.approx(0.25)


def test_single_error_detector():
    dem = stim.DetectorErrorModel("error(0.1) D3")
    model = from_stim_dem(dem)
    assert model.error_mechanisms[0].detectors == frozenset({3})


def test_single_error_observable():
    dem = stim.DetectorErrorModel("error(0.1) L2")
    model = from_stim_dem(dem)
    assert model.error_mechanisms[0].observables == frozenset({2})


def test_error_multiple_detectors():
    dem = stim.DetectorErrorModel("error(0.1) D0 D1 D2")
    model = from_stim_dem(dem)
    assert model.error_mechanisms[0].detectors == frozenset({0, 1, 2})
    assert model.error_mechanisms[0].observables == frozenset()


def test_error_detectors_and_observables():
    dem = stim.DetectorErrorModel("error(0.1) D0 D1 L0")
    model = from_stim_dem(dem)
    m = model.error_mechanisms[0]
    assert m.detectors == frozenset({0, 1})
    assert m.observables == frozenset({0})


def test_multiple_error_instructions():
    dem = stim.DetectorErrorModel("error(0.1) D0\nerror(0.2) D1 L0")
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 2


def test_no_error_instructions():
    dem = stim.DetectorErrorModel()
    model = from_stim_dem(dem)
    assert model.error_mechanisms == []


# ---------------------------------------------------------------------------
# Detectors set
# ---------------------------------------------------------------------------

def test_detector_instruction_populates_detectors():
    # explicit detector declaration, no error mechanism references it
    dem = stim.DetectorErrorModel("detector D0\ndetector D1")
    model = from_stim_dem(dem)
    assert 0 in model.detectors
    assert 1 in model.detectors


def test_error_instruction_also_populates_detectors():
    dem = stim.DetectorErrorModel("error(0.1) D5")
    model = from_stim_dem(dem)
    assert 5 in model.detectors


# ---------------------------------------------------------------------------
# Observables set — derived from dem.num_observables
# ---------------------------------------------------------------------------

def test_observables_from_num_observables():
    """Observables are derived from dem.num_observables, not only from error instructions."""
    dem = stim.DetectorErrorModel("error(0.1) D0 L0\ndetector D0")
    model = from_stim_dem(dem)
    # stim infers num_observables = 1 (L0 is referenced)
    assert model.observables == {0}


def test_observable_declared_but_not_in_any_mechanism():
    """If a mechanism references L1 (forcing num_observables=2), L0 must still
    appear in model.observables even though no mechanism flips it, so that
    observable_coverage can catch the gap."""
    # L1 is referenced so num_observables=2; L0 is never flipped by any mechanism.
    dem = stim.DetectorErrorModel("error(0.1) D0 L1\ndetector D0")
    model = from_stim_dem(dem)
    assert 0 in model.observables
    assert 1 in model.observables


# ---------------------------------------------------------------------------
# Repeat blocks are flattened
# ---------------------------------------------------------------------------

def test_repeat_block_mechanisms_are_flattened():
    dem = stim.DetectorErrorModel("""
        repeat 3 {
            error(0.1) D0
        }
    """)
    model = from_stim_dem(dem)
    assert len(model.error_mechanisms) == 3


def test_repeat_block_detectors_are_flattened():
    dem = stim.DetectorErrorModel("""
        repeat 2 {
            error(0.1) D0 D1
        }
    """)
    model = from_stim_dem(dem)
    assert model.error_mechanisms[0].detectors == frozenset({0, 1})


# ---------------------------------------------------------------------------
# Empty DEM
# ---------------------------------------------------------------------------

def test_empty_dem_gives_empty_model():
    model = from_stim_dem(stim.DetectorErrorModel())
    assert model.detectors == set()
    assert model.observables == set()
    assert model.error_mechanisms == []
