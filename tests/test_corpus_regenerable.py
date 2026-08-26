"""The stim-generated corpus is byte-reproducible from its manifests.

Guards the decision that only external-library DEMs are committed: every
stim-generated parent and mutation in CORPUS_MANIFEST.jsonl /
MUTATION_MANIFEST.jsonl must (a) regenerate to exactly its recorded
input_sha256 under the current stim version, and (b) match the on-disk
file. If this test fails after a stim upgrade, the manifests — not the
files — are stale; re-pin them with notes/audits/validation/run_campaign.py.

The test regenerates the corpus before checking, so a fresh checkout
(e.g. CI, where stim-generated DEMs are gitignored) passes without any
prior local generation step.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
VALIDATION_DIR = ROOT / "notes" / "audits" / "validation"
REGENERATE_SCRIPT = VALIDATION_DIR / "regenerate_corpus.py"


@pytest.mark.skipif(
    not REGENERATE_SCRIPT.is_file(), reason="regenerate_corpus.py missing"
)
def test_stim_generated_corpus_matches_manifests() -> None:
    # Regenerate first: writes the gitignored stim-generated DEMs so that
    # the subsequent --check pass has files to compare against on a fresh
    # checkout. Hash mismatches still fail here, before any disk compare.
    regenerate = subprocess.run(
        [sys.executable, str(REGENERATE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert regenerate.returncode == 0, (
        "stim-generated corpus failed to regenerate from manifests:\n"
        f"{regenerate.stderr}"
    )

    result = subprocess.run(
        [sys.executable, str(REGENERATE_SCRIPT), "--check"],
        capture_output=True,
        text=True,
        timeout=600,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
    )
    assert result.returncode == 0, (
        "stim-generated corpus drifted from its manifests:\n" f"{result.stderr}"
    )
