from __future__ import annotations

import stim

from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock


def _walk_dem_instructions(
    dem: stim.DetectorErrorModel,
) -> tuple[list[ErrorMechanism | RepeatBlock], int]:
    """Recursively walk a DEM, emitting ErrorMechanism and RepeatBlock nodes.

    Tracks the running detector offset from shift_detectors so that detector IDs
    inside each node are correct for its scope (absolute at the top level,
    iteration-relative inside a RepeatBlock body).

    Returns (items, total_shift) where total_shift is the sum of all
    shift_detectors increments, used by the caller to advance its own offset.
    """
    result: list[ErrorMechanism | RepeatBlock] = []
    current_offset = 0

    for instruction in dem:
        if isinstance(instruction, stim.DemRepeatBlock):
            # Walk the body with a fresh offset (body IDs are iteration-relative,
            # starting from 0 at the beginning of each iteration).
            body_items, body_shift = _walk_dem_instructions(instruction.body_copy())
            result.append(
                RepeatBlock(
                    body=tuple(body_items),
                    count=instruction.repeat_count,
                    detector_offset_per_iteration=body_shift,
                    absolute_start_offset=current_offset,
                )
            )
            current_offset += instruction.repeat_count * body_shift
        else:
            instr_type = instruction.type

            if instr_type == "error":
                prob = instruction.args_copy()[0]
                det_targets: set[int] = set()
                obs_targets: set[int] = set()
                for t in instruction.targets_copy():
                    if isinstance(t, stim.DemTarget) and t.is_relative_detector_id():
                        det_targets ^= {t.val + current_offset}
                    elif isinstance(t, stim.DemTarget) and t.is_logical_observable_id():
                        obs_targets ^= {t.val}
                    # ^ (separator) and integer targets are silently dropped.
                result.append(
                    ErrorMechanism(
                        probability=prob,
                        detectors=frozenset(det_targets),
                        observables=frozenset(obs_targets),
                    )
                )

            elif instr_type == "shift_detectors":
                # targets_copy() returns the shift as a raw integer (not a DemTarget).
                shift = instruction.targets_copy()[0]
                assert isinstance(shift, int)
                current_offset += shift

            # detector, logical_observable, and unknown instruction types are silently
            # skipped; detector/observable metadata is obtained via stim's API in
            # from_stim_dem (num_detectors, num_observables, get_detector_coordinates).

    return result, current_offset


def from_stim_dem(dem: stim.DetectorErrorModel) -> ErrorModel:
    """Translate a stim.DetectorErrorModel into a frontend-agnostic ErrorModel.

    Walks the tree structure of the DEM (including repeat blocks) to preserve
    hierarchical information needed for the Repeat Rule (v0.2).
    """
    error_mechanisms, _ = _walk_dem_instructions(dem)
    raw_coords = dem.get_detector_coordinates()
    return ErrorModel(
        detectors=set(range(dem.num_detectors)),
        observables=set(range(dem.num_observables)),
        error_mechanisms=error_mechanisms,
        detector_coords={k: tuple(vs) for k, vs in raw_coords.items() if vs},
    )
