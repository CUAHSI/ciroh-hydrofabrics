"""Pytest setup shared by every Consistency Check test folder."""

import sys
from pathlib import Path

import pytest

# The network, geometry and attributes test folders import shared helpers (such as
# check_runner) from tests/, which pytest would otherwise put on the path only when
# a test in that folder is collected.
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))


@pytest.fixture
def no_recorded_counts(tmp_path_factory):
    """A counts file that records nothing, for tests that call the command's ``main`` directly.

    Without it ``main`` reads the official counts in ``counts.yaml``, which the fixture under test is
    not meant to be compared with.
    """
    counts = tmp_path_factory.mktemp("counts") / "no-recorded-counts.yaml"
    counts.write_text("{}\n")
    return counts
