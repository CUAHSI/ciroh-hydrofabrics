#!/usr/bin/env bash
# Runs the repo's pytest suite (schema/structure tests for the hydrofabric
# pipeline outputs). Requires the pixi environment to be installed
# (`pixi install`), since pytest is managed as a pixi dependency.
#
# Usage:
#   ./run_tests.sh                  # run all tests
#   ./run_tests.sh tests/v2.2       # run only the v2.2 suite
#   ./run_tests.sh -k id_naming     # pass extra args through to pytest

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

if [ "$#" -eq 0 ]; then
    set -- tests/
fi

pixi run pytest -v "$@"
