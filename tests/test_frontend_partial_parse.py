"""Frontend partial-parse surfacing: unknown DEM instruction types.

Guards against the silent-incompleteness risk that motivated the Deltakit-Stim
frontend compatibility audit: a DEM carrying instruction types ErrorModel
cannot represent (e.g. adaptive-DEM leakage metadata) must never produce a
clean-looking pass. The frontend records them; `emlint.check` surfaces them on
the Report; all output formats expose them.
"""

from __future__ import annotations

import json

import pytest
import stim

import emlint
from emlint import frontends

# ---------------------------------------------------------------------------
# Passing cases
# ---------------------------------------------------------------------------


def test_standard_dem_has_no_unknown_instructions() -> None:
    dem = stim.Circuit.generated(
        "surface_code:rotated_memory_z", rounds=2, distance=2
    ).detector_error_model(decompose_errors=True)
    model = frontends.from_stim_dem(dem)
    assert model.unknown_instructions == []


def test_report_standard_dem_no_partial_parse_flag() -> None:
    report = emlint.check(
        stim.Circuit.generated(
            "surface_code:rotated_memory_z", rounds=2, distance=2
        ).detector_error_model(decompose_errors=True)
    )
    assert report.unknown_instructions == []


# ---------------------------------------------------------------------------
# Failing cases (partial-parse detection)
# ---------------------------------------------------------------------------


def _dem_with_unknown_instruction() -> stim.DetectorErrorModel:
    """Build a DEM containing an instruction type emlint cannot represent.

    Uses a bare `detector` instruction with coordinates plus a hand-written
    `shift_detectors`-style extension: we inject a custom instruction by
    parsing DEM text that includes an instruction Stim accepts but emlint's
    ErrorModel does not model. `detector` and `logical_observable` are known;
    anything else (e.g. `rerun`, or Deltakit-Stim metadata instructions) lands
    in unknown_instructions. We use text-level construction because Stim's
    Python API cannot attach arbitrary instructions to a DetectorErrorModel.
    """
    text = "\n".join(
        [
            "error(0.1) D0 D1 L0",
            "error(0.1) D0",
            "repeat 2 {",
            "    error(0.1) D0 D1",
            "}",
        ]
    )
    return stim.DetectorErrorModel(text)


def test_repeat_block_unknown_not_falsely_reported() -> None:
    """A REPEAT-bearing but otherwise standard DEM has no unknown types."""
    model = frontends.from_stim_dem(_dem_with_unknown_instruction())
    assert model.unknown_instructions == []
    # sanity: repeat block preserved
    from emlint.model import RepeatBlock

    assert any(isinstance(i, RepeatBlock) for i in model.error_mechanisms)


def test_unknown_instruction_detected_via_manual_walk() -> None:
    """Inject an unrepresentable instruction by monkey-parsing raw text.

    Stim's DetectorErrorModel parser rejects truly arbitrary instructions, so
    to exercise the unknown-type path deterministically we call the internal
    walker on stub objects. This pins the walker contract: non-error/shift/
    detector/observable instruction types must be collected, deduped, and
    sorted; detector/logical_observable are known metadata types and excluded.
    """

    class _FakeInstruction:
        def __init__(self, type_name: str):
            self.type = type_name

    class _FakeDem:
        def __init__(self, instructions: list):
            self._instructions = instructions

        def __iter__(self):
            return iter(self._instructions)

    dem = _FakeDem(
        [
            _FakeInstruction("heralded_leakage_event"),
            _FakeInstruction("detector"),  # known metadata type — excluded
            _FakeInstruction("logical_observable"),  # known — excluded
            _FakeInstruction("adaptive_metadata"),
        ]
    )
    items, shift, unknown = frontends._walk_dem_instructions(dem)
    assert items == []
    assert shift == 0
    assert unknown == [
        "adaptive_metadata",
        "heralded_leakage_event",
    ]  # sorted, deduped; detector/logical_observable excluded


def test_unknown_instruction_types_deduped_and_sorted() -> None:
    class _FakeInstruction:
        def __init__(self, type_name: str):
            self.type = type_name

    class _FakeDem:
        def __init__(self, instructions: list):
            self._instructions = instructions

        def __iter__(self):
            return iter(self._instructions)

    dem = _FakeDem(
        [
            _FakeInstruction("zeta_meta"),
            _FakeInstruction("alpha_meta"),
            _FakeInstruction("zeta_meta"),
        ]
    )
    _, _, unknown = frontends._walk_dem_instructions(dem)
    assert unknown == ["alpha_meta", "zeta_meta"]


# ---------------------------------------------------------------------------
# Report integration
# ---------------------------------------------------------------------------


def test_report_surfaces_unknown_instructions(monkeypatch: pytest.MonkeyPatch) -> None:
    """emlint.check propagates unknown_instructions onto the Report."""
    real_from_stim_dem = frontends.from_stim_dem
    dem = stim.DetectorErrorModel("error(0.1) D0 L0")

    def patched(d):
        model = real_from_stim_dem(d)
        model.unknown_instructions.append("heralded_leakage_event")
        return model

    monkeypatch.setattr(frontends, "from_stim_dem", patched)
    report = emlint.check(dem)
    assert report.unknown_instructions == ["heralded_leakage_event"]


def test_partial_parse_is_never_a_clean_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    """A partial parse must produce an explicit inconclusive result so that the
    report is not clean and exit codes reflect the incompleteness."""
    real_from_stim_dem = frontends.from_stim_dem
    dem = stim.DetectorErrorModel("error(0.1) D0 L0")

    def patched(d):
        model = real_from_stim_dem(d)
        model.unknown_instructions.append("adaptive_metadata")
        return model

    monkeypatch.setattr(frontends, "from_stim_dem", patched)
    report = emlint.check(dem)
    partial = next(r for r in report.results if r.name == "partial_parse")
    assert partial.status == "inconclusive"
    assert not partial.passed
    assert partial.counter_example is not None
    assert partial.counter_example_data is not None
    assert "adaptive_metadata" in partial.message
    # The report is no longer clean.
    assert not report.all_passed()
    assert report.any_skipped
    assert report.has_warnings()


def test_clean_parse_has_no_partial_parse_result() -> None:
    dem = stim.Circuit.generated(
        "surface_code:rotated_memory_z", rounds=2, distance=2
    ).detector_error_model(decompose_errors=True)
    report = emlint.check(dem)
    assert all(r.name != "partial_parse" for r in report.results)


def test_text_format_shows_partial_parse(monkeypatch: pytest.MonkeyPatch) -> None:
    from emlint.report import format_text

    real_from_stim_dem = frontends.from_stim_dem
    dem = stim.DetectorErrorModel("error(0.1) D0 L0")

    def patched(d):
        model = real_from_stim_dem(d)
        model.unknown_instructions.extend(["adaptive_metadata"])
        return model

    monkeypatch.setattr(frontends, "from_stim_dem", patched)
    text = format_text(emlint.check(dem))
    assert "[partial-parse]" in text
    assert "adaptive_metadata" in text


def test_json_format_includes_unknown_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emlint.report import format_json

    real_from_stim_dem = frontends.from_stim_dem
    dem = stim.DetectorErrorModel("error(0.1) D0 L0")

    def patched(d):
        model = real_from_stim_dem(d)
        model.unknown_instructions.append("adaptive_metadata")
        return model

    monkeypatch.setattr(frontends, "from_stim_dem", patched)
    data = json.loads(format_json(emlint.check(dem)))
    assert data["unknown_instructions"] == ["adaptive_metadata"]


def test_sarif_format_includes_unknown_instructions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from emlint.report import format_sarif

    real_from_stim_dem = frontends.from_stim_dem
    dem = stim.DetectorErrorModel("error(0.1) D0 L0")

    def patched(d):
        model = real_from_stim_dem(d)
        model.unknown_instructions.append("adaptive_metadata")
        return model

    monkeypatch.setattr(frontends, "from_stim_dem", patched)
    data = json.loads(format_sarif(emlint.check(dem)))
    props = data["runs"][0]["properties"]
    assert props["unknown_instructions"] == ["adaptive_metadata"]
