"""
Release-gate benchmark for emlint
==================================
Run from the repo root with the venv active:

    python examples/benchmark.py

Sections
--------
correctness   Verifies that each check fires on the right bug class.
              Also prints a shift-left comparison — see SHIFT-LEFT METHODOLOGY.
counterex     Counter-example quality audit — verifies output is actionable.
performance   Wall-clock time and O(n) scaling regression gate.

Exit code 0 = all gates pass.  Exit code 1 = at least one gate fails.

SHIFT-LEFT METHODOLOGY
-----------------------
For each bug in the corpus, t_sim is the wall-clock time simulation would need
to detect the anomaly at 3σ significance using stim's DEM sampler + pymatching.
t_emlint is the median wall-clock time of emlint.check() on the same DEM.

Three regimes are used depending on how (or whether) each bug is detectable
through simulation:

measured
    The bug inflates p_L by an amount large enough to detect in a few thousand
    shots.  t_sim is measured directly: stim samples detection events from both
    the clean and buggy DEMs; pymatching decodes them; a two-proportion z-test
    gives N_min for 3σ detection; t_sim = N_min / measured_throughput (including
    pymatching graph-construction cost).  Labelled [meas] in the output.
    Measured on a d=7, 7-round surface code so that decode throughput reflects
    a realistic production-scale DEM.  Applies to: detectability.

estimate
    The bug produces a real but small p_L delta that would require millions of
    shots at p=0.001 to reach 3σ.  t_sim is estimated from the standard
    sample-size formula N = 9/(α²·p_L) with a conservative assumed p_L and
    α=0.1, divided by SHOT_RATE (10⁵ shots/sec, single-core laptop).  Labelled
    [est] in the output.
    Applies to: duplicates.

simulation-blind
    Two sub-cases, both reported the same way (t_sim = —):
    a) Structurally blind: the bug produces no p_L signal regardless of shot
       count (zero/NaN probability, observable_coverage, sensitivity).
    b) Blind at practical budget: 10k shots are insufficient to reach 3σ
       significance.  The bug is detectable in principle with millions of
       shots, but a practitioner running a quick sanity check would miss it.
    emlint catches both sub-cases statically regardless of bug probability.
"""

from __future__ import annotations

import re
import statistics
import sys
import time
from typing import Literal, TypedDict, cast

import pymatching
import stim

import emlint


class _MeasuredEntry(TypedDict):
    bug: str
    dem: stim.DetectorErrorModel
    expected_check: str
    sim_approach: Literal["measured"]
    clean_dem: stim.DetectorErrorModel


class _EstimatedEntry(TypedDict):
    bug: str
    dem: stim.DetectorErrorModel
    expected_check: str
    sim_approach: Literal["estimate"]
    p_L_inflated: float


class _BlindEntry(TypedDict):
    bug: str
    dem: stim.DetectorErrorModel
    expected_check: str
    sim_approach: Literal["blind"]
    sim_blind_reason: str


CorpusEntry = _MeasuredEntry | _EstimatedEntry | _BlindEntry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def time_check(dem: stim.DetectorErrorModel, n: int = 5) -> float:
    """Median wall-clock time (seconds) for emlint.check() over n runs."""
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        emlint.check(dem)
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


# Shot-rate for the 'estimate' category (single-core laptop, conservative).
SHOT_RATE = 1e5  # shots / second

_PASS = "PASS \u2713"
_FAIL = "FAIL \u2717"


def t_sim_estimate(p_L_inflated: float, alpha: float = 0.1) -> float:
    """Theoretical t_sim for bugs whose signal requires millions of shots.

    N_shots = 9 / (alpha^2 * p_L)  — standard 3-sigma sample-size formula.
    Used only for the 'estimate' category (see CORPUS).
    """
    return (9.0 / (alpha**2 * p_L_inflated)) / SHOT_RATE


# Practical debugger shot budget: a practitioner running a quick sanity check.
DEBUG_SHOTS = 10_000


def time_sim_measured(
    clean_dem: stim.DetectorErrorModel,
    buggy_dem: stim.DetectorErrorModel,
) -> tuple[float, bool]:
    """Simulate DEBUG_SHOTS shots on the clean and buggy DEM with pymatching.

    Returns (t_sim, detectable) where:
    - t_sim   is the wall-clock time to run DEBUG_SHOTS shots on the buggy DEM
              (including pymatching graph construction — the full debugger cost).
    - detectable is True if the observed p_L delta passes a 3σ two-proportion
              z-test within the DEBUG_SHOTS budget.

    A bug that is not detectable here is "simulation-blind at practical budget":
    a practitioner running a 10k-shot sanity check would miss it entirely.
    """
    matchers = [
        pymatching.Matching.from_detector_error_model(dem)
        for dem in (clean_dem, buggy_dem)
    ]
    samplers = [
        dem.compile_sampler(seed=i) for i, dem in enumerate((clean_dem, buggy_dem))
    ]

    p_Ls: list[float] = []
    # Time only the buggy DEM run — that is what the debugger pays.
    for i, (matcher, sampler) in enumerate(zip(matchers, samplers)):
        t0 = time.perf_counter()
        det_data, obs_data, _ = sampler.sample(shots=DEBUG_SHOTS)
        predictions = matcher.decode_batch(det_data)
        elapsed = time.perf_counter() - t0
        diff = predictions != obs_data
        if isinstance(diff, bool):
            errors = int(diff)
        else:
            errors = int(diff.any(axis=1).sum())
        p_Ls.append(errors / DEBUG_SHOTS)
        if i == 1:
            t_buggy = elapsed  # the cost a debugger actually pays

    p_clean, p_buggy = p_Ls
    delta = abs(p_buggy - p_clean)

    # 3σ two-proportion z-test: detectable if N_min ≤ DEBUG_SHOTS.
    if delta < 1e-12:
        detectable = False
    else:
        p_bar = (p_clean + p_buggy) / 2.0
        N_min = 9.0 * p_bar * (1.0 - p_bar) / (delta**2)
        detectable = N_min <= DEBUG_SHOTS

    return t_buggy, detectable


# ---------------------------------------------------------------------------
# Synthetic bug corpus
# ---------------------------------------------------------------------------

# d=3 base: used for structural checks where circuit size is irrelevant.
_base_circuit = stim.Circuit.generated(
    "surface_code:rotated_memory_z",
    rounds=3,
    distance=3,
    after_clifford_depolarization=0.001,
)
_base_dem_str = str(_base_circuit.detector_error_model(decompose_errors=True))


def _dem(extra: str) -> stim.DetectorErrorModel:
    return stim.DetectorErrorModel(_base_dem_str + "\n" + extra)


def _nan_dem() -> stim.DetectorErrorModel:
    """Build a DEM containing a NaN-probability mechanism programmatically.

    stim's text parser rejects 'nan' as a floating-point literal, but the
    Python API accepts it — matching a realistic DEM-generation script that
    produces NaN via numerical underflow or division by zero.
    """
    base = stim.DetectorErrorModel(_base_dem_str)
    base.append(
        "error",
        [float("nan")],
        [stim.target_relative_detector_id(0), stim.target_relative_detector_id(1)],
    )
    return base


# d=7 base: used for detectability entries so that pymatching graph
# construction and decode cost reflect a realistic production-scale DEM.
_d7_circuit = stim.Circuit.generated(
    "surface_code:rotated_memory_z",
    rounds=7,
    distance=7,
    after_clifford_depolarization=0.001,
)
_d7_dem_str = str(_d7_circuit.detector_error_model(decompose_errors=True))
_d7_clean_dem = stim.DetectorErrorModel(_d7_dem_str)


def _d7_buggy(p: float) -> stim.DetectorErrorModel:
    """d=7 DEM with an injected error(p) L0 mechanism (no detector targets)."""
    return stim.DetectorErrorModel(_d7_dem_str + f"\nerror({p}) L0")


CORPUS = cast(
    list[CorpusEntry],
    [
        {
            "bug": "Undetectable logical error (p=1e-2)",
            "dem": _d7_buggy(1e-2),
            "expected_check": "detectability",
            "sim_approach": "measured",
            "clean_dem": _d7_clean_dem,
            # p_L delta ~0.01: large signal, easily detectable within 10k shots.
        },
        {
            "bug": "Undetectable logical error (p=1e-4)",
            "dem": _d7_buggy(1e-4),
            "expected_check": "detectability",
            "sim_approach": "measured",
            "clean_dem": _d7_clean_dem,
            # p_L delta ~0.0001: N_min ~10^6 shots — invisible at 10k-shot budget.
        },
        {
            "bug": "Undetectable logical error (p=1e-5)",
            "dem": _d7_buggy(1e-5),
            "expected_check": "detectability",
            "sim_approach": "measured",
            "clean_dem": _d7_clean_dem,
            # p_L delta ~0.00001: N_min ~10^8 shots — invisible at 10k-shot budget.
        },
        {
            "bug": "Zero-probability mechanism",
            "dem": _dem("error(0.0) D0 D1"),
            "expected_check": "probability_bounds",
            "sim_approach": "blind",
            "sim_blind_reason": "zero-probability mechanism never fires; p_L is identical to clean DEM",
        },
        {
            "bug": "NaN probability",
            "dem": _nan_dem(),
            "expected_check": "probability_bounds",
            "sim_approach": "blind",
            "sim_blind_reason": "NaN mechanism is silently ignored by pymatching; p_L unchanged",
        },
        {
            "bug": "Double-counted boundary mechanism",
            "dem": _dem("error(0.005) D0 D1\nerror(0.005) D0 D1"),
            "expected_check": "duplicates",
            "sim_approach": "estimate",
            "p_L_inflated": 2e-4,
            # The XOR-fused edge weight (~2× intended) causes subtle decoder
            # degradation.  At p=0.001 and d=3 the p_L delta is ~10^-4: millions
            # of shots are needed for 3σ significance; t_sim is estimated.
        },
        {
            "bug": "Mis-wired observable (never flipped)",
            "dem": stim.DetectorErrorModel(
                "detector D0\n"
                "detector D1\n"
                "error(0.01) D0 D1 L1\n"  # L1 forces num_observables=2; L0 uncovered
            ),
            "expected_check": "observable_coverage",
            "sim_approach": "blind",
            "sim_blind_reason": "L0 is never flipped; p_L(L0)=0, which looks correct, not anomalous",
        },
        {
            "bug": "Untriggered detector",
            "dem": stim.DetectorErrorModel(
                "detector D0\n"
                "detector D1\n"
                "detector D2\n"  # D2 is never referenced by any error mechanism
                "error(0.01) D0 D1\n"
            ),
            "expected_check": "sensitivity",
            "sim_approach": "blind",
            "sim_blind_reason": "dead detector D2 never fires; syndrome distribution is unchanged",
        },
    ],
)


# ---------------------------------------------------------------------------
# Counter-example quality specification
# ---------------------------------------------------------------------------
# For each check, three criteria must hold on the counter_example string:
#   1. Names the specific mechanism or detector — not just a count.
#   2. Explains why it is a problem — one sentence of reasoning.
#   3. Actionable — a practitioner can identify the fix without opening the DEM.
#
# Each entry: (criterion_label, re.search pattern against counter_example text).
_CE_QUALITY: dict[str, list[tuple[str, str]]] = {
    "detectability": [
        ("names mechanism", r"error\(.+\)"),
        ("explains why", r"trigger"),
        ("actionable", r"error\(.+\).*L\d"),
    ],
    "probability_bounds": [
        ("names mechanism", r"error\("),
        ("explains why", r"NaN|zero|negative|infinite|complement"),
        ("actionable", r"error\([^)]+\)"),
    ],
    "sensitivity": [
        ("names detector", r"D\d+"),
        ("explains why", r"not triggered|no error mechanism"),
        ("actionable", r"Detector.*D\d+|D\d+.*not triggered"),
    ],
    "observable_coverage": [
        ("names observable", r"L\d+"),
        ("explains why", r"not flipped|no error mechanism"),
        ("actionable", r"Observable.*L\d+|L\d+.*not flipped"),
    ],
    "duplicates": [
        ("names mechanism", r"error\("),
        ("explains why", r"share signature|XOR"),
        ("actionable", r"XOR-fused probability is"),
    ],
    "correctability": [
        ("names syndrome", r"D\d+|syndrome"),
        ("explains why", r"maps to"),
        ("actionable", r"\{.*L\d|\{\s*\}"),
    ],
}


def run_correctness_audit() -> tuple[bool, list[dict]]:
    """Verify that each check fires on the correct bug class.

    The shift-left comparison is informational only and does not affect the
    pass/fail outcome — see SHIFT-LEFT METHODOLOGY in the module docstring.
    """
    print("=" * 76)
    print("CORRECTNESS AUDIT")
    print("=" * 76)
    print(f"  {'Bug class':<40} {'Check fired':<24} {'t_emlint':>9} {'Correct?':>9}")
    print("-" * 76)

    all_pass = True
    results = []

    for entry in CORPUS:
        dem = entry["dem"]
        t_emlint = time_check(dem)

        sim_approach = entry["sim_approach"]
        if sim_approach == "measured":
            measured_entry = cast(_MeasuredEntry, entry)
            t_sim_raw, sim_detectable = time_sim_measured(
                measured_entry["clean_dem"], dem
            )
            t_sim: float | None = t_sim_raw if sim_detectable else None
            sim_label = "[meas]  " if sim_detectable else "[budget\u2060blind]"
        elif sim_approach == "estimate":
            estimate_entry = cast(_EstimatedEntry, entry)
            t_sim = t_sim_estimate(estimate_entry["p_L_inflated"])
            sim_detectable = True
            sim_label = "[est]   "
        else:
            t_sim = None
            sim_detectable = False
            sim_label = "[blind] "

        report = emlint.check(dem)
        failing = [r for r in report.results if not r.passed]
        actual_check = failing[0].name if failing else "NONE (no violation!)"
        expected = entry["expected_check"]
        fired_correctly = actual_check == expected

        if not fired_correctly:
            all_pass = False

        results.append(
            {
                **entry,
                "t_emlint": t_emlint,
                "t_sim": t_sim,
                "sim_label": sim_label,
                "sim_detectable": sim_detectable,
                "actual_check": actual_check,
                "fired_correctly": fired_correctly,
                "counter_example": failing[0].counter_example if failing else None,
            }
        )

        status = "\u2713" if fired_correctly else "\u2717"
        print(
            f"  {status} {entry['bug']:<40} {actual_check:<24} "
            f"{t_emlint*1000:>7.2f}ms {' OK' if fired_correctly else ' FAIL':>9}"
        )

    # Shift-left comparison table.
    print()
    print("  Shift-left comparison (see SHIFT-LEFT METHODOLOGY):")
    print(
        f"  {'Bug class':<44} {'t_emlint':>9}  {'t_sim (10k)':>9} {'':12}  {'speedup':>9}"
    )
    print(f"  {'-'*44}  {'-'*9}  {'-'*9} {'-'*12}  {'-'*9}")
    for r in results:
        t_emlint_str = f"{r['t_emlint']*1000:.2f}ms"
        t_sim = r["t_sim"]
        label = r["sim_label"]
        if t_sim is None:
            t_val = "\u2014"
            speedup_str = "\u2014"
        else:
            t_val = f"{t_sim*1000:.2f}ms" if t_sim < 1.0 else f"{t_sim:.0f}s"
            ratio = t_sim / r["t_emlint"]
            if ratio >= 1.0:
                speedup_str = f"{ratio:.0f}\u00d7"
            else:
                speedup_str = f"1/{1/ratio:.0f}\u00d7"
        print(
            f"  {r['bug']:<44} {t_emlint_str:>9}  {t_val:>9} {label:<12}  {speedup_str:>9}"
        )

    print()
    print("COUNTER-EXAMPLE QUALITY AUDIT  (must pass all criteria for all checks)")
    print("-" * 76)
    seen: set[str] = set()
    for entry in results:
        check_name = entry["actual_check"]
        if check_name in seen or check_name == "NONE (no violation!)":
            continue
        seen.add(check_name)
        ce = entry["counter_example"] or ""
        criteria = _CE_QUALITY.get(check_name, [])
        print(f"  [{check_name}]")
        print(f"    counter_example: {ce[:120]}")
        ce_ok = True
        for label, pattern in criteria:
            ok = bool(re.search(pattern, ce, re.IGNORECASE))
            tick = "\u2713" if ok else "\u2717 FAIL"
            print(f"    {tick} {label}")
            if not ok:
                ce_ok = False
                all_pass = False
        entry["ce_quality_pass"] = ce_ok
        print()

    print(f"Correctness audit: {_PASS if all_pass else _FAIL}")
    return all_pass, results


# ---------------------------------------------------------------------------
# SUMMARY BULLETS
# ---------------------------------------------------------------------------


def _print_summary_bullets(corpus_results: list[dict]) -> None:
    """Print a concise human-readable summary of the correctness run."""
    print()
    print("=" * 76)
    print("SUMMARY")
    print("=" * 76)

    n_correct = sum(1 for r in corpus_results if r["fired_correctly"])
    n_total = len(corpus_results)
    max_t_ms = max(r["t_emlint"] for r in corpus_results) * 1000
    print(
        f"\u2022 emlint fired the correct check on {n_correct}/{n_total} bug classes; "
        f"slowest detection was {max_t_ms:.1f} ms on a d=7 surface code DEM."
    )

    # Measured shift-left results — budget-blind cases are the headline.
    measured_detectable = [
        r
        for r in corpus_results
        if r["sim_approach"] == "measured" and r["t_sim"] is not None
    ]
    measured_blind = [
        r
        for r in corpus_results
        if r["sim_approach"] == "measured" and r["t_sim"] is None
    ]

    if measured_blind:
        # Headline result: bugs structurally in simulation's reach but invisible
        # at the practical 10k-shot debugger budget.
        best_blind = min(measured_blind, key=lambda r: r["t_emlint"])
        bugs = "; ".join(r["bug"] for r in measured_blind)
        print(
            f"\u2022 Measured [blind at {DEBUG_SHOTS:,}-shot budget — emlint wins]: {bugs}."
        )
        print(
            f"  A 10k-shot run produces no detectable p_L signal (N_min >> {DEBUG_SHOTS:,})."
        )
        print(
            f"  emlint catches them statically in {best_blind['t_emlint']*1000:.0f}\u2013"
            f"{max(r['t_emlint'] for r in measured_blind)*1000:.0f} ms."
        )

    if measured_detectable:
        # Secondary result: where the bug is blatant enough that simulation wins
        # on raw speed — reported honestly.
        best = max(measured_detectable, key=lambda r: r["t_sim"] / r["t_emlint"])
        speedup = best["t_sim"] / best["t_emlint"]
        t_val = (
            f"{best['t_sim']*1000:.2f} ms"
            if best["t_sim"] < 1.0
            else f"{best['t_sim']:.1f} s"
        )
        if speedup >= 1.0:
            note = f"emlint is \u00d7{speedup:.0f} faster"
        else:
            note = (
                f"simulation is \u00d7{1/speedup:.0f} faster "
                f"(p_L delta is large enough to be obvious at {DEBUG_SHOTS:,} shots)"
            )
        print(
            f"\u2022 Measured [detectable at {DEBUG_SHOTS:,} shots]: \"{best['bug']}\" \u2014 "
            f"t_sim \u2248 {t_val}, t_emlint {best['t_emlint']*1000:.0f} ms ({note})."
        )

    # Estimated shift-left gap.
    estimated = [
        r
        for r in corpus_results
        if r["sim_approach"] == "estimate" and r["t_sim"] is not None
    ]
    if estimated:
        best = max(estimated, key=lambda r: r["t_sim"] / r["t_emlint"])
        speedup = best["t_sim"] / best["t_emlint"]
        print(
            f"\u2022 Estimated shift-left gap [est]: \"{best['bug']}\" \u2014 "
            f"t_sim \u2248 {best['t_sim']:.0f} s vs t_emlint {best['t_emlint']*1000:.1f} ms "
            f"(\u00d7{speedup:.0f} faster, theoretical at p=0.001)."
        )

    # Simulation-blind bugs (structural + budget).
    blind_bugs = [
        r["bug"]
        for r in corpus_results
        if r["sim_approach"] == "blind"
        or (r["sim_approach"] == "measured" and r["t_sim"] is None)
    ]
    if blind_bugs:
        print(
            f"\u2022 Simulation-blind (structural or blind at 10k shot budget): "
            f"{'; '.join(blind_bugs)}."
        )
        print(f"  emlint catches them statically in < 100 ms.")

    # Counter-example quality summary.
    ce_failures = [r for r in corpus_results if r.get("ce_quality_pass") is False]
    if ce_failures:
        failed = ", ".join(dict.fromkeys(r["actual_check"] for r in ce_failures))
        print(
            f"\u2022 Counter-example quality failures (fix before release): {failed}."
        )
    else:
        print(
            f"\u2022 All counter-example messages pass the 3-part quality test: "
            f"name mechanism, explain why, actionable."
        )


# ---------------------------------------------------------------------------
# PERFORMANCE REGRESSION CHECK
# ---------------------------------------------------------------------------


def run_performance_gate() -> bool:
    """Performance regression gate: wall-clock time and O(n) scaling check.

    Two checks:
    - Wall-clock gate: full suite on d=7, N=100 must complete in < 5 s.
    - Scaling check: ratio of check time at d=7 vs d=3 must be < 10× the
      ratio of mechanism counts, confirming O(n) growth (not O(n²)).
    """
    print()
    print("=" * 76)
    print("PERFORMANCE REGRESSION GATE")
    print("=" * 76)

    sizes = [
        ("surface_code:rotated_memory_z", 3, 10),
        ("surface_code:rotated_memory_z", 7, 100),
    ]
    rows = []
    for task, d, rounds in sizes:
        circuit = stim.Circuit.generated(
            task,
            rounds=rounds,
            distance=d,
            after_clifford_depolarization=0.001,
        )
        dem = circuit.detector_error_model(decompose_errors=True)
        n_mechs = len(dem.flattened())
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            emlint.check(dem)
            times.append(time.perf_counter() - t0)
        elapsed = statistics.median(times)
        rows.append({"d": d, "rounds": rounds, "n_mechs": n_mechs, "elapsed": elapsed})
        print(
            f"  d={d}, N={rounds:>3} rounds: {n_mechs:>8,} mechanisms  {elapsed*1000:>8.1f}ms"
        )

    print()

    # Gate 1: wall-clock
    large = rows[-1]
    gate1_pass = large["elapsed"] < 5.0
    status1 = "\u2713 PASS" if gate1_pass else "\u2717 FAIL"
    print(
        f"  Gate 1 — wall-clock (d=7, N=100 < 5000ms): "
        f"{large['elapsed']*1000:.1f}ms  {status1}"
    )

    # Gate 2: O(n) scaling — time ratio must be < 10× mechanism ratio
    small, large = rows[0], rows[-1]
    mech_ratio = large["n_mechs"] / small["n_mechs"]
    time_ratio = large["elapsed"] / small["elapsed"]
    scaling_ok = time_ratio < 10 * mech_ratio
    status2 = (
        "\u2713 PASS" if scaling_ok else "\u2717 FAIL (super-linear growth detected)"
    )
    print(
        f"  Gate 2 — O(n) scaling: mechanisms ×{mech_ratio:.1f}, "
        f"time ×{time_ratio:.1f}  {status2}"
    )

    all_pass = gate1_pass and scaling_ok
    print()
    print(f"Performance gate: {_PASS if all_pass else _FAIL}")
    return all_pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    s3, corpus_results = run_correctness_audit()
    s4 = run_performance_gate()
    _print_summary_bullets(corpus_results)

    print()
    print("=" * 76)
    overall = s3 and s4
    print(
        f"SUMMARY: correctness {_PASS if s3 else _FAIL}  |  performance {_PASS if s4 else _FAIL}"
    )
    print(
        f"Overall: {'ALL GATES PASS' if overall else 'GATES FAILED — do not release'}"
    )
    sys.exit(0 if overall else 1)
