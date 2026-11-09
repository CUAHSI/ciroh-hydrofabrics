"""Behavioral tests for network Consistency Checks through the CLI."""

import subprocess
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point


RUNNER = Path(__file__).resolve().parents[2] / "consistency_check.py"


def run_check(path, kind="ngen", *extra):
    return subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01", *map(str, extra)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_reports_extra_duplicate_primary_ids_but_not_network_ids(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["nex-1", "nex-1", "nex-1", "nex-2"]},
        geometry=[Point(0, 0), Point(1, 0), Point(2, 0), Point(3, 0)], crs="EPSG:5070",
    ).to_file(path, layer="nexus", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_primary_ids.nexus | 2 | 0 | FAIL | advisory" in result.stdout
    assert "duplicate_primary_ids.network" not in result.stdout


def test_reports_duplicate_poi_ids_without_treating_flowpath_ids_as_unique(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"poi_id": [1, 1, 2], "id": ["wb-1", "wb-2", "wb-2"]},
        geometry=[Point(0, 0), Point(1, 0), Point(2, 0)], crs="EPSG:5070",
    ).to_file(path, layer="pois", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_primary_ids.pois | 1 | 0 | FAIL | advisory" in result.stdout


def test_network_metrics_use_recorded_limits_and_blocking_configuration(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["nex-1", "nex-1", "nex-1"]},
        geometry=[Point(0, 0), Point(1, 0), Point(2, 0)], crs="EPSG:5070",
    ).to_file(path, layer="nexus", engine="pyogrio")
    config = tmp_path / "checks.yaml"
    config.write_text("geopackage_layers:\n  blocking: false\nschema:\n  blocking: false\nnetwork:\n  blocking: true\n")
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  ngen:\n    "01":\n      network:\n        duplicate_primary_ids.nexus: 1\n')

    result = run_check(path, "ngen", "--config", config, "--counts", counts)

    assert result.returncode == 1, result.stderr
    assert "network | duplicate_primary_ids.nexus | 2 | 1 | FAIL | blocking" in result.stdout
    counts.write_text('v2.2:\n  ngen:\n    "01":\n      network:\n        duplicate_primary_ids.nexus: 2\n')
    result = run_check(path, "ngen", "--config", config, "--counts", counts)
    assert result.returncode == 0, result.stderr
    assert "network | duplicate_primary_ids.nexus | 2 | 2 | PASS | blocking" in result.stdout
