#!/usr/bin/env bash
# Runs the repo's pytest suites. Requires the pixi environment (`pixi install`).
#
# Usage:
#   ./run_tests.sh                                 # run all tests
#   ./run_tests.sh validation/consistency/tests    # consistency checks only
#   ./run_tests.sh -k schema                       # pass extra args to pytest

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "$#" -eq 0 ]; then
    set -- tests/ validation/consistency/tests
fi

pixi run pytest -v "$@"
