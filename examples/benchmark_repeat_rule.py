from __future__ import annotations

import sys
import time
from pathlib import Path

import stim

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import emlint

for rounds in (10, 100, 1000, 10_000):
    circuit = stim.Circuit.generated(
        "surface_code:rotated_memory_z",
        distance=7,
        rounds=rounds,
        after_clifford_depolarization=0.001,
    )
    dem = circuit.detector_error_model(decompose_errors=True)
    started = time.perf_counter()
    report = emlint.check(dem)
    elapsed = time.perf_counter() - started
    flat_count = len(emlint.frontends.from_stim_dem(dem).flattened())
    print(
        f"d=7 rounds={rounds:5d} "
        f"source_nodes={report.num_error_mechanisms:6d} "
        f"flattened={flat_count:7d} "
        f"seconds={elapsed:.3f}"
    )
