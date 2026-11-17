"""The v2.2 report must not change when checks become Data Model driven.

The golden files hold the complete CLI report for the fixtures in
``golden_fixtures``. Regenerate them deliberately with
``UPDATE_GOLDEN=1 pytest tests/test_golden.py`` after reviewing the diff.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from golden_fixtures import write_ngen, write_reference

HERE = Path(__file__).resolve().parent
RUNNER = HERE.parent / "consistency_check.py"
WRITERS = {"ngen": write_ngen, "reference": write_reference}


def report(tmp_path, kind):
    gpkg = tmp_path / f"{kind}.gpkg"
    WRITERS[kind](gpkg)
    # An empty counts file keeps the report independent of recorded limits.
    counts = tmp_path / "counts.yaml"
    counts.write_text("{}\n")
    result = subprocess.run(
        [sys.executable, str(RUNNER), str(gpkg), "--type", kind, "--vpu", "01", "--counts", str(counts)],
        capture_output=True, text=True, check=False,
    )
    text = f"exit {result.returncode}\n--- stdout\n{result.stdout}--- stderr\n{result.stderr}"
    return text.replace(str(tmp_path), "<tmp>").replace(str(RUNNER.parent), "<consistency>")


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_v22_report_is_unchanged(tmp_path, kind):
    actual = report(tmp_path, kind)
    golden = HERE / "golden" / f"v2.2-{kind}.txt"
    if os.environ.get("UPDATE_GOLDEN"):
        golden.parent.mkdir(exist_ok=True)
        golden.write_text(actual)
    assert actual == golden.read_text()
