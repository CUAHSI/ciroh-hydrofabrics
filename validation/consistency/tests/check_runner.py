"""Run the Consistency Check command from a test, apart from the official recorded counts.

``counts.yaml`` holds the official products' counts. If a test ran the command with its default, the report
would show those official numbers next to a tiny fixture's results, and a test that compares exact report
lines would depend on numbers that have nothing to do with the fixture.
"""

import subprocess
import sys
import tempfile
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "consistency_check.py"


def run_consistency_check(*arguments):
    """Run the command with the given arguments and return the finished process.

    The run starts from an empty counts file in a folder that is removed afterwards. A test that
    supplies its own ``--counts`` comes later on the command line, and the command uses the last one.
    A nonzero exit status does not raise, so a test can assert on it.
    """
    with tempfile.TemporaryDirectory() as folder:
        counts = Path(folder) / "no-recorded-counts.yaml"
        counts.write_text("{}\n")
        return subprocess.run(
            [sys.executable, str(RUNNER), "--counts", str(counts), *map(str, arguments)],
            capture_output=True, text=True, check=False,
        )


def run_check(path, kind="ngen", *extra):
    """Check one fixture GeoPackage as VPU 01 of the given output kind."""
    return run_consistency_check(path, "--type", kind, "--vpu", "01", *extra)
