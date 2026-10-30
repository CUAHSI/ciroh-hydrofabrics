"""
Shared fixtures for the v2.2 NextGen hydrofabric schema tests.

These tests compare the output of ngen-workflow/R/reconcile.Rmd (the last
pipeline stage) against the official v2.2 NextGen hydrofabric geopackage, to
catch structural regressions (missing layers, renamed/reordered/mistyped
columns, wrong geometry types, or inconsistent id-naming conventions) without
requiring the exact data values to match.

The pipeline output is a large, locally-produced artifact (not checked into
git), so these tests are skipped automatically if it is not present on disk.
The reference geopackage is also large and not checked into git, but rather
than skipping, it is downloaded automatically from HydroShare into
tests/v2.2/assets/ the first time the suite runs (and reused on subsequent
runs).
"""

import urllib.request
from pathlib import Path

import pytest

ASSETS_DIR = Path(__file__).parent / "assets"

# A single VPU's worth of pipeline output, produced by reconcile.Rmd.
PIPELINE_GPKG = Path(
    "/Users/castro/Documents/work/hydrofabric/ciroh-hydrofabrics/"
    "ngen-workflow/output/v2.2/ngen/16/ngen_hydrofabric_final.gpkg"
)

# The official NextGen v2.2 hydrofabric geopackage used as the structural
# "ground truth" for these tests: a single, fully-populated VPU (03S) from
# the official HydroShare resource, small enough to download on demand.
REFERENCE_GPKG_NAME = "ngen-hydrofabric-vpu-03S.gpkg"
REFERENCE_GPKG = ASSETS_DIR / REFERENCE_GPKG_NAME
REFERENCE_GPKG_URL = (
    "https://www.hydroshare.org/resource/bbbabc296b65401ca1f4f3985e4b2b00/"
    f"data/contents/{REFERENCE_GPKG_NAME}"
)


def _require_file(path: Path) -> None:
    if not path.exists():
        pytest.skip(f"required geopackage not found on disk: {path}")


def _download_reference_gpkg(path: Path, url: str) -> None:
    """Download the reference geopackage to `path`, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".part")
    try:
        urllib.request.urlretrieve(url, tmp_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        pytest.skip(f"could not download reference geopackage from {url}: {exc}")
    tmp_path.rename(path)


@pytest.fixture(scope="session")
def pipeline_gpkg() -> Path:
    _require_file(PIPELINE_GPKG)
    return PIPELINE_GPKG


@pytest.fixture(scope="session")
def reference_gpkg() -> Path:
    if not REFERENCE_GPKG.exists():
        _download_reference_gpkg(REFERENCE_GPKG, REFERENCE_GPKG_URL)
    return REFERENCE_GPKG
