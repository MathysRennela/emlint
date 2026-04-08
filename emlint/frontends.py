from __future__ import annotations

import stim

from emlint.model import ErrorMechanism, ErrorModel


def from_stim_dem(dem: stim.DetectorErrorModel) -> ErrorModel:
    """Translate a stim.DetectorErrorModel into a frontend-agnostic ErrorModel."""
    # detectors is populated from both 'detector' instructions (declared detectors)
    # and 'error' instructions (detectors referenced by error mechanisms). A
    # well-formed DEM declares every detector explicitly, but we accept both to
    # handle partially-specified models without silent data loss.
    # observables is derived from dem.num_observables so that observables declared
    # in the circuit but never referenced in any error mechanism are still tracked.
    detectors: set[int] = set()
    error_mechanisms: list[ErrorMechanism] = []
    detector_coords: dict[int, tuple[float, ...]] = {}

    for instruction in dem.flattened():
        if not isinstance(instruction, stim.DemInstruction):
            continue
        if instruction.type == "error":
            prob = instruction.args_copy()[0]
            det_targets: list[int] = []
            obs_targets: list[int] = []
            for t in instruction.targets_copy():
                if not isinstance(t, stim.DemTarget):
                    continue
                if t.is_relative_detector_id():
                    det_targets.append(t.val)
                    detectors.add(t.val)
                elif t.is_logical_observable_id():
                    obs_targets.append(t.val)
            error_mechanisms.append(
                ErrorMechanism(
                    probability=prob,
                    detectors=frozenset(det_targets),
                    observables=frozenset(obs_targets),
                )
            )
        elif instruction.type == "detector":
            coords = tuple(float(v) for v in instruction.args_copy())
            for t in instruction.targets_copy():
                if not isinstance(t, stim.DemTarget):
                    continue
                if t.is_relative_detector_id():
                    detectors.add(t.val)
                    if coords:
                        detector_coords[t.val] = coords

    return ErrorModel(
        detectors=detectors,
        observables=set(range(dem.num_observables)),
        error_mechanisms=error_mechanisms,
        detector_coords=detector_coords,
    )
