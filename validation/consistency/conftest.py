"""Pytest setup shared by every Consistency Check test folder."""

import sys
from pathlib import Path

# The network, geometry and attributes test folders import shared helpers (such as
# check_runner) from tests/, which pytest would otherwise put on the path only when
# a test in that folder is collected.
sys.path.insert(0, str(Path(__file__).resolve().parent / "tests"))
