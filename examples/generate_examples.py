"""
Generate example .dem files for emlint demonstrations.

Usage: python examples/generate_examples.py
Outputs files into examples/.
"""

from __future__ import annotations

from pathlib import Path

import stim

HERE = Path(__file__).parent


def save(name: str, dem: stim.DetectorErrorModel) -> Path:
    path = HERE / name
    path.write_text(str(dem))
    print(f"  wrote {path}")
    return path


def main() -> None:
    HERE.mkdir(exist_ok=True)

    # --- Good baseline: d=5 rotated surface code, 10 rounds ---
    circuit_good = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        rounds=10,
        distance=5,
        after_clifford_depolarization=0.001,
    )
    dem_good = circuit_good.detector_error_model()
    save("surface_code_d5_good.dem", dem_good)

    # --- Example 1: Undetectable error (Detectability violation) ---
    # Inject an error that flips the logical observable but triggers no detector.
    # This cannot be caught by Stim alone on a standalone .dem file.
    dem_text = str(dem_good) + "\nerror(0.001) L0\n"
    save(
        "surface_code_d5_undetectable.dem",
        stim.DetectorErrorModel(dem_text),
    )

    # --- Example 2: Dead detector (Sensitivity violation) ---
    # Add an extra detector declaration that no error mechanism references.
    # We do this by parsing the DEM, finding the max detector index, and appending
    # a detector instruction with the next index.
    max_det = max(
        t.val
        for instr in dem_good.flattened()
        if isinstance(instr, stim.DemInstruction) and instr.type == "error"
        for t in instr.targets_copy()
        if isinstance(t, stim.DemTarget) and t.is_relative_detector_id()
    )
    ghost_det = max_det + 1
    dem_text = str(dem_good) + f"\ndetector(0, 0, 999) D{ghost_det}\n"
    save(
        "surface_code_d5_dead_detector.dem",
        stim.DetectorErrorModel(dem_text),
    )

    # --- Example 3: Uncovered observable (Observable-coverage violation) ---
    # L1 (observable index 1) forces num_observables=2. L0 (index 0) is never
    # flipped by any mechanism — observable_coverage catches the gap.
    # This demonstrates a mis-wired OBSERVABLE_INCLUDE in the original circuit:
    # the gate targets the wrong qubit, so no physical error can flip L0.
    save(
        "uncovered_observable.dem",
        stim.DetectorErrorModel(
            "detector D0\n" "detector D1\n" "error(0.001) D0 D1 L1\n"
        ),
    )

    print("Done.")


if __name__ == "__main__":
    main()
