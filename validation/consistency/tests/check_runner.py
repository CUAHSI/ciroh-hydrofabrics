"""Run the Consistency Check command on a test fixture."""

import subprocess
import sys
from pathlib import Path

RUNNER = Path(__file__).resolve().parents[1] / "consistency_check.py"


def run_check(path, kind="ngen", *extra):
    """Run the command on one fixture as VPU 01 and return the finished process.

    Unless the test supplies its own ``--counts``, the run uses an empty counts file. Otherwise the
    report would show the official VPU 01 counts recorded in ``counts.yaml`` next to a tiny fixture's
    results, and tests that compare exact report lines would depend on those official numbers.

    A nonzero exit status does not raise, so a test can assert on it.
    """
    arguments = [str(argument) for argument in extra]
    if not any(argument == "--counts" or argument.startswith("--counts=") for argument in arguments):
        arguments += ["--counts", str(empty_counts_file(Path(path).parent))]
    return subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01", *arguments],
        capture_output=True, text=True, check=False,
    )


def empty_counts_file(folder):
    """Write a counts file that records nothing, beside the fixture so each test has its own."""
    counts = folder / "no-recorded-counts.yaml"
    counts.write_text("{}\n")
    return counts
