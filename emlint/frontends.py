from __future__ import annotations

from typing import Any

import stim

from emlint.model import ErrorMechanism, ErrorModel, RepeatBlock


def _walk_dem_instructions(
    dem: Any,
) -> tuple[list[ErrorMechanism | RepeatBlock], int, list[str]]:
    """Recursively walk a DEM, emitting ErrorMechanism and RepeatBlock nodes.

    Tracks the running detector offset from shift_detectors so that detector IDs
    inside each node are correct for its scope (absolute at the top level,
    iteration-relative inside a RepeatBlock body).

    Returns (items, total_shift) where total_shift is the sum of all
    shift_detectors increments, used by the caller to advance its own offset.
    """
    result: list[ErrorMechanism | RepeatBlock] = []
    current_offset = 0
    unknown_types: list[str] = []

    for instruction in dem:
        if isinstance(instruction, stim.DemRepeatBlock):
            # Walk the body with a fresh offset (body IDs are iteration-relative,
            # starting from 0 at the beginning of each iteration).
            body_items, body_shift, body_unknown = _walk_dem_instructions(
                instruction.body_copy()
            )
            unknown_types.extend(body_unknown)
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
                args = instruction.args_copy()
                if not args:
                    # Malformed error instruction (no probability argument):
                    # record as unrepresentable instead of crashing with a
                    # bare IndexError, consistent with partial-parse handling.
                    unknown_types.append("error(missing_probability_argument)")
                    continue
                prob = args[0]
                det_targets: set[int] = set()
                obs_targets: set[int] = set()
                decomposition_hints: list[tuple[frozenset[int], frozenset[int]]] = []
                comp_dets: set[int] = set()
                comp_obs: set[int] = set()
                for t in instruction.targets_copy():
                    if isinstance(t, stim.DemTarget) and t.is_relative_detector_id():
                        det_targets ^= {t.val + current_offset}
                        comp_dets ^= {t.val + current_offset}
                    elif isinstance(t, stim.DemTarget) and t.is_logical_observable_id():
                        obs_targets ^= {t.val}
                        comp_obs ^= {t.val}
                    elif isinstance(t, stim.DemTarget) and t.is_separator():
                        # ^ marks a component boundary: record the completed
                        # component and start a new one. The merged signature
                        # above is kept independently of these hints.
                        decomposition_hints.append(
                            (frozenset(comp_dets), frozenset(comp_obs))
                        )
                        comp_dets = set()
                        comp_obs = set()
                    # integer targets are silently dropped.
                if decomposition_hints:
                    decomposition_hints.append(
                        (frozenset(comp_dets), frozenset(comp_obs))
                    )
                result.append(
                    ErrorMechanism(
                        probability=prob,
                        detectors=frozenset(det_targets),
                        observables=frozenset(obs_targets),
                        decomposition_hints=tuple(decomposition_hints),
                    )
                )

            elif instr_type == "shift_detectors":
                # targets_copy() returns the shift as a raw integer (not a DemTarget).
                shift = instruction.targets_copy()[0]
                assert isinstance(shift, int)
                current_offset += shift

            else:
                # detector / logical_observable metadata is obtained via stim's
                # API in from_stim_dem (num_detectors, num_observables,
                # get_detector_coordinates). Any other instruction type is not
                # representable in ErrorModel; record it so the caller can flag
                # partial parsing rather than silently passing.
                if instr_type not in ("detector", "logical_observable"):
                    unknown_types.append(instr_type)

    return result, current_offset, sorted(set(unknown_types))


def from_stim_dem(dem: stim.DetectorErrorModel) -> ErrorModel:
    """Translate a stim.DetectorErrorModel into a frontend-agnostic ErrorModel.

    Walks the tree structure of the DEM (including repeat blocks) to preserve
    hierarchical information needed for the Repeat Rule (v0.2).

    Instruction types that ErrorModel cannot represent (anything other than
    ``error``, ``shift_detectors``, ``detector``, and ``logical_observable``)
    are recorded on the returned model's ``unknown_instructions`` field so that
    callers can surface partial parsing instead of reporting a vacuous pass.
    """
    error_mechanisms, _, unknown = _walk_dem_instructions(dem)
    raw_coords = dem.get_detector_coordinates()
    return ErrorModel(
        detectors=set(range(dem.num_detectors)),
        observables=set(range(dem.num_observables)),
        error_mechanisms=error_mechanisms,
        detector_coords={k: tuple(vs) for k, vs in raw_coords.items() if vs},
        unknown_instructions=unknown,
    )
