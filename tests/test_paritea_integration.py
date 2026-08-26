"""Optional integration tests for Paritea's direct Stim DEM export."""

from __future__ import annotations

import pytest

pytest.importorskip("paritea")
import stim

import emlint
from paritea.glue.stim import (
    export_to_stim_dem,
    from_stim,
    push_out_for_measurement_detectors,
)

# ---------------------------------------------------------------------------
# Paritea → emlint
# ---------------------------------------------------------------------------


def test_paritea_export_has_no_error_severity_findings():
    """The pinned integration recipe produces a structurally valid DEM."""
    probability = 1e-3
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        rounds=2,
        distance=3,
        after_clifford_depolarization=probability,
        after_reset_flip_probability=probability,
        before_measure_flip_probability=probability,
        before_round_data_depolarization=probability,
    ).flattened()

    _, noise_model, measurement_nodes, observables, detectors = from_stim(circuit)
    exported_model, logical_regions, detector_regions = (
        push_out_for_measurement_detectors(
            noise_model,
            measurement_nodes=measurement_nodes,
            logicals=list(observables.values()),
            detectors=detectors,
        )
    )
    # Paritea's XOR compression must happen before emlint audits duplicate
    # detector/observable signatures in the exported DEM.
    exported_model.compress(lambda left, right: left * (1 - right) + (1 - left) * right)
    dem = export_to_stim_dem(
        exported_model,
        logical_regions=logical_regions,
        detector_regions=detector_regions,
    )

    report = emlint.check(dem)

    assert report.num_detectors == dem.num_detectors
    assert report.num_observables == dem.num_observables
    assert not report.has_errors()
