"""Behavioral tests for the v2.2 schema check through its CLI."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point


RUNNER = Path(__file__).resolve().parents[1] / "consistency_check.py"


def run_check(path, kind="ngen", *extra):
    return subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01", *map(str, extra)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_missing_required_layers_are_reported_without_downloading_a_reference(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | missing_layer.divides | 1 | 0 | FAIL | advisory" in result.stdout
    assert "schema | missing_layer.nexus | 0 | 0 | PASS | advisory" in result.stdout


def test_reports_layers_missing_geopackage_registration(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM gpkg_contents WHERE table_name = 'nexus'")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | missing_registration.nexus | 1 | 0 | FAIL | advisory" in result.stdout


def test_reports_missing_and_extra_columns(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"], "unexpected": [1]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | missing_columns.nexus | 4 | 0 | FAIL | advisory" in result.stdout
    assert "schema | extra_columns.nexus | 1 | 0 | FAIL | advisory" in result.stdout


def test_reports_column_order_and_declared_types(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": [1], "type": ["terminal"], "toid": ["wb-0"], "vpuid": ["01"], "poi_id": [1]},
        geometry=[Point(0, 0)], crs="EPSG:5070",
    ).to_file(path, layer="nexus", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | column_order.nexus | 1 | 0 | FAIL | advisory" in result.stdout
    assert "schema | column_types.nexus | 2 | 0 | FAIL | advisory" in result.stdout


def test_reports_wrong_geopackage_layer_type(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_contents SET data_type = 'attributes' WHERE table_name = 'nexus'")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | layer_type.nexus | 1 | 0 | FAIL | advisory" in result.stdout


def test_reports_geometry_type_and_crs_for_nonempty_layers(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:4326").to_file(
        path, layer="nexus", engine="pyogrio"
    )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | geometry_type.nexus | 1 | 0 | FAIL | advisory" in result.stdout
    assert "schema | geometry_crs.nexus | 1 | 0 | FAIL | advisory" in result.stdout


def test_reports_missing_geometry_registration(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM gpkg_geometry_columns WHERE table_name = 'nexus'")

    result = run_check(path)

    # GDAL cannot open this incomplete GeoPackage for the separate layer check.
    assert result.returncode == 2
    assert "geopackage_layers could not run" in result.stderr
    assert "schema | missing_geometry_registration.nexus | 1 | 0 | FAIL | advisory" in result.stdout


def test_reports_unexpected_identifier_prefixes(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["nex-1", "wrong-2"], "toid": ["wb-1", "wb-0"]},
        geometry=[Point(0, 0), Point(1, 1)], crs="EPSG:5070",
    ).to_file(path, layer="nexus", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | id_prefixes.nexus.id | 1 | 0 | FAIL | advisory" in result.stdout
    assert "schema | id_prefixes.nexus.toid | 0 | 0 | PASS | advisory" in result.stdout


def test_unsupported_model_reports_incomplete_check(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )

    result = run_check(path, "ngen", "--data-model", "other")

    assert result.returncode == 2
    assert "no schema specification" in result.stderr
    assert "geopackage_layers" in result.stdout


def test_reference_build_uses_reference_layers(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"divide_id": [1.0]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="divides", engine="pyogrio"
    )

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert "schema | missing_layer.flowpaths | 1 | 0 | FAIL | advisory" in result.stdout
    assert "schema | missing_layer.hydrolocations | 1 | 0 | FAIL | advisory" in result.stdout
    assert "schema | missing_layer.nexus" not in result.stdout


def test_generic_geometry_in_spec_accepts_specific_type(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["wb-1"]}, geometry=[LineString([(0, 0), (1, 1)])], crs="EPSG:5070").to_file(
        path, layer="flowpaths", engine="pyogrio"
    )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | geometry_type.flowpaths | 0 | 0 | PASS | advisory" in result.stdout


def test_empty_layer_skips_geometry_comparison(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326").to_file(
        path, layer="nexus", engine="pyogrio"
    )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | geometry_crs.nexus" not in result.stdout
    assert "schema | geometry_type.nexus" not in result.stdout
    assert "schema | id_prefixes.nexus.id" not in result.stdout


def test_schema_counts_respect_blocking_configuration(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )
    config = tmp_path / "checks.yaml"
    config.write_text("geopackage_layers:\n  blocking: false\nschema:\n  blocking: true\n")
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  ngen:\n    "01":\n      schema:\n        missing_layer.divides: 1\n')

    result = run_check(path, "ngen", "--config", config, "--counts", counts)

    assert result.returncode == 1, result.stderr
    assert "schema | missing_layer.divides | 1 | 1 | PASS | blocking" in result.stdout
    assert "schema | missing_layer.flowpaths | 1 | 0 | FAIL | blocking" in result.stdout
