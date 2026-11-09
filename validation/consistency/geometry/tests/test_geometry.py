"""Geometry Consistency Checks exercised through the real CLI."""

import hashlib
import sqlite3
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import Point, Polygon, box


RUNNER = Path(__file__).resolve().parents[2] / "consistency_check.py"


def write_layer(path, layer, geometries, crs="EPSG:5070"):
    gpd.GeoDataFrame(
        {"id": [f"feature-{i}" for i in range(len(geometries))]},
        geometry=geometries,
        crs=crs,
    ).to_file(path, layer=layer, engine="pyogrio")


def run_check(path, kind="ngen", *extra):
    return subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01", *map(str, extra)],
        capture_output=True,
        text=True,
        check=False,
    )


def geometry_value(result, metric):
    matches = [line.split(" | ") for line in result.stdout.splitlines()
               if line.startswith(f"geometry | {metric} | ")]
    assert len(matches) == 1, (metric, result.stdout, result.stderr)
    return float(matches[0][2])


def assert_no_topology(result):
    assert "geometry | divide_overlaps." not in result.stdout
    assert "geometry | divide_gaps." not in result.stdout
    assert "geometry | divide_union_area_m2 |" not in result.stdout


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_clean_divides_report_complete_topology(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [box(0, 0, 10, 10), box(10, 0, 20, 10)])

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert "geometry | invalid_geometries.divides | 0 | 0 | PASS | advisory" in result.stdout
    assert "geometry | divide_overlaps.count | 0 | 0 | PASS | advisory" in result.stdout
    assert "geometry | divide_gaps.count | 0 | 0 | PASS | advisory" in result.stdout
    assert "geometry | divide_union_area_m2 | 200.0 | - | INFO | advisory" in result.stdout


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_topological_duplicates_count_extra_rows_in_every_spatial_layer(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    reversed_square = Polygon([(0, 0), (0, 10), (10, 10), (10, 0), (0, 0)])
    densified_square = Polygon([(0, 0), (5, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    write_layer(path, "divides", [square, reversed_square, densified_square])
    write_layer(path, "other_features", [Point(1, 1), Point(1, 1), Point(2, 2)])
    pyogrio.write_dataframe(pd.DataFrame({"value": [1, 1]}), path, layer="attributes")

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "duplicate_geometries.divides") == 2
    assert geometry_value(result, "duplicate_geometries.other_features") == 1
    assert not any(line.startswith("geometry | ") and ".attributes |" in line
                   for line in result.stdout.splitlines())
    # Equal areas of exactly 100 m² are below the strict overlap cutoff.
    assert geometry_value(result, "divide_overlaps.count") == 0


def test_reversed_invalid_geometries_and_nan_points_are_detected_as_duplicates(tmp_path):
    path = tmp_path / "build.gpkg"
    invalid = Polygon([(1, 2), (3, 0), (1, 4), (3, 0), (0, 0), (1, 2)])
    reversed_invalid = Polygon(list(invalid.exterior.coords)[::-1])
    write_layer(path, "other_features", [invalid, reversed_invalid])
    rotated = Polygon([(2, 1), (2, 3), (0, 4), (3, 4), (0, 3), (4, 4), (0, 3), (2, 1)])
    same_rotated = Polygon([(0, 3), (4, 4), (0, 3), (2, 1), (2, 3), (0, 4), (3, 4), (0, 3)])
    write_layer(path, "rotated", [rotated, same_rotated])
    write_layer(path, "nan_points", [Point(float("nan"), 1), Point(float("nan"), 1)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "invalid_geometries.other_features") == 2
    assert geometry_value(result, "duplicate_geometries.other_features") == 1
    assert geometry_value(result, "invalid_geometries.rotated") == 2
    assert geometry_value(result, "duplicate_geometries.rotated") == 1
    assert geometry_value(result, "invalid_geometries.nan_points") == 2
    assert geometry_value(result, "duplicate_geometries.nan_points") == 1


def test_empty_geometries_are_duplicates_but_nulls_are_not(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "other_features", [Point(), Point(), None, None, Point(0, 0)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "empty_geometries.other_features") == 2
    assert geometry_value(result, "null_geometries.other_features") == 2
    assert geometry_value(result, "duplicate_geometries.other_features") == 1


def test_overlap_counts_unordered_pairs_including_containment_and_equality(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [
        box(0, 0, 20, 20), box(10, 0, 30, 10),  # exactly 100
        box(100, 0, 130, 20), box(110, 0, 130, 20), box(110, 0, 130, 20),
        box(200, 0, 220, 20), box(210, 0, 230, 20),
    ])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "divide_overlaps.count") == 4
    assert geometry_value(result, "divide_overlaps.total_area_m2") == 1400
    assert geometry_value(result, "divide_overlaps.largest_area_m2") == 400


def test_overlap_threshold_is_configurable_and_strict(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [box(0, 0, 20, 20), box(10, 0, 30, 20)])
    config = tmp_path / "checks.yaml"
    config.write_text(
        "geopackage_layers:\n  blocking: false\nschema:\n  blocking: false\n"
        "network:\n  blocking: false\ngeometry:\n  blocking: false\n  overlap_min_area_m2: 200\n"
        "attributes:\n  blocking: false\n"
    )

    result = run_check(path, "ngen", "--config", config)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "divide_overlaps.count") == 0
    assert geometry_value(result, "divide_overlaps.total_area_m2") == 0
    assert "geometry | overlap_min_area_m2 | 200.0 | - | INFO | advisory" in result.stdout


@pytest.mark.parametrize("metric", [
    "divide_overlaps.count", "divide_overlaps.total_area_m2", "divide_overlaps.largest_area_m2",
    "divide_gaps.count", "divide_gaps.total_area_m2", "divide_gaps.largest_area_m2",
])
def test_each_topology_metric_has_an_independent_limit(tmp_path, metric):
    path = tmp_path / "build.gpkg"
    hole = Polygon(
        [(100, 0), (140, 0), (140, 40), (100, 40), (100, 0)],
        holes=[[(110, 10), (130, 10), (130, 30), (110, 30), (110, 10)]],
    )
    write_layer(path, "divides", [box(0, 0, 20, 20), box(10, 0, 30, 20), hole])
    config = tmp_path / "checks.yaml"
    config.write_text(
        "geopackage_layers:\n  blocking: false\nschema:\n  blocking: false\n"
        "network:\n  blocking: false\ngeometry:\n  blocking: true\n"
        "attributes:\n  blocking: false\n"
    )
    limits = {
        "divide_overlaps.count": 1, "divide_overlaps.total_area_m2": 200,
        "divide_overlaps.largest_area_m2": 200, "divide_gaps.count": 1,
        "divide_gaps.total_area_m2": 400, "divide_gaps.largest_area_m2": 400,
    }
    limits[metric] = 0
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  ngen:\n    "01":\n      geometry:\n' +
                      ''.join(f'        {name}: {limit}\n' for name, limit in limits.items()))

    result = run_check(path, "ngen", "--config", config, "--counts", counts)

    assert result.returncode == 1, result.stderr
    for name in limits:
        line = next(line for line in result.stdout.splitlines() if line.startswith(f"geometry | {name} | "))
        assert (" | FAIL | " if name == metric else " | PASS | ") in line


def test_geometry_metrics_use_recorded_limits_and_blocking_but_area_info_does_not_gate(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [box(0, 0, 20, 20), box(10, 0, 30, 20)])
    config = tmp_path / "checks.yaml"
    config.write_text(
        "geopackage_layers:\n  blocking: false\nschema:\n  blocking: false\n"
        "network:\n  blocking: false\ngeometry:\n  blocking: true\n"
        "attributes:\n  blocking: false\n"
    )
    counts = tmp_path / "counts.yaml"
    counts.write_text(
        'v2.2:\n  ngen:\n    "01":\n      geometry:\n'
        '        divide_overlaps.count: 1\n'
        '        divide_overlaps.total_area_m2: 200\n'
        '        divide_overlaps.largest_area_m2: 200\n'
    )

    result = run_check(path, "ngen", "--config", config, "--counts", counts)

    assert result.returncode == 0, result.stderr
    assert "geometry | divide_overlaps.count | 1 | 1 | PASS | blocking" in result.stdout
    assert "geometry | divide_union_area_m2 | 600.0 | - | INFO | blocking" in result.stdout
    counts.write_text(counts.read_text().replace("divide_overlaps.count: 1", "divide_overlaps.count: 0"))
    result = run_check(path, "ngen", "--config", config, "--counts", counts)
    assert result.returncode == 1, result.stderr
    assert "geometry | divide_overlaps.count | 1 | 0 | FAIL | blocking" in result.stdout
    assert "geometry | divide_union_area_m2 | 600.0 | - | INFO | blocking" in result.stdout


def test_gaps_exclude_islands_and_exactly_100_square_metres(tmp_path):
    path = tmp_path / "build.gpkg"
    outer = Polygon(
        [(0, 0), (50, 0), (50, 50), (0, 50), (0, 0)],
        holes=[[(5, 5), (15, 5), (15, 15), (5, 15), (5, 5)],
               [(20, 20), (40, 20), (40, 40), (20, 40), (20, 20)]],
    )
    write_layer(path, "divides", [outer, box(25, 25, 35, 35)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "divide_gaps.count") == 1
    assert geometry_value(result, "divide_gaps.total_area_m2") == 300
    assert geometry_value(result, "divide_gaps.largest_area_m2") == 300
    assert geometry_value(result, "divide_union_area_m2") == 2100


def test_nested_island_holes_are_counted_once(tmp_path):
    path = tmp_path / "build.gpkg"
    outer = Polygon(
        [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)],
        holes=[[(10, 10), (90, 10), (90, 90), (10, 90), (10, 10)]],
    )
    island = Polygon(
        [(20, 20), (80, 20), (80, 80), (20, 80), (20, 20)],
        holes=[[(30, 30), (70, 30), (70, 70), (30, 70), (30, 30)]],
    )
    write_layer(path, "divides", [outer, island, box(40, 40, 60, 60)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "divide_gaps.count") == 2
    assert geometry_value(result, "divide_gaps.total_area_m2") == 4000
    assert geometry_value(result, "divide_gaps.largest_area_m2") == 2800
    assert geometry_value(result, "divide_union_area_m2") == 6000


def test_invalid_divides_are_repaired_in_memory_without_changing_the_geopackage(tmp_path):
    path = tmp_path / "build.gpkg"
    bowtie = Polygon([(0, 0), (20, 20), (0, 20), (20, 0), (0, 0)])
    write_layer(path, "divides", [bowtie])
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 1
    assert geometry_value(result, "divide_overlaps.count") == 0
    assert geometry_value(result, "divide_union_area_m2") == 200
    assert hashlib.sha256(path.read_bytes()).hexdigest() == original_hash


def test_invalid_divide_with_collapsed_edge_retains_its_polygonal_area(tmp_path):
    path = tmp_path / "build.gpkg"
    with_spur = Polygon([(0, 0), (20, 0), (20, 20), (0, 20), (0, 0), (-5, 0), (0, 0)])
    write_layer(path, "divides", [with_spur])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 1
    assert geometry_value(result, "divide_union_area_m2") == 400


def test_divide_collapsing_to_a_line_after_repair_is_unusable(tmp_path):
    path = tmp_path / "build.gpkg"
    collapsed = Polygon([(0, 0), (10, 0), (20, 0), (0, 0)])
    write_layer(path, "divides", [collapsed])

    result = run_check(path)

    assert result.returncode == 2
    assert "unusable divide" in result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 1
    assert_no_topology(result)


@pytest.mark.parametrize("bad", [None, Polygon()])
def test_null_or_empty_divide_keeps_quality_counts_but_suppresses_partial_topology(tmp_path, bad):
    path = tmp_path / "build.gpkg"
    bowtie = Polygon([(0, 0), (20, 20), (0, 20), (20, 0), (0, 0)])
    write_layer(path, "divides", [box(30, 0, 40, 10), bowtie, bad])
    write_layer(path, "other_features", [Point(0, 0), None, Point()])

    result = run_check(path)

    assert result.returncode == 2
    assert "divides topology incomplete" in result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 1
    assert geometry_value(result, "null_geometries.divides") == int(bad is None)
    assert geometry_value(result, "empty_geometries.divides") == int(bad is not None)
    assert geometry_value(result, "null_geometries.other_features") == 1
    assert geometry_value(result, "empty_geometries.other_features") == 1
    assert_no_topology(result)


@pytest.mark.parametrize("crs", [None, "EPSG:4326", "EPSG:3857"])
def test_wrong_or_missing_divide_crs_suppresses_area_results(tmp_path, crs):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [box(0, 0, 20, 20)], crs=crs)

    result = run_check(path)

    assert result.returncode == 2
    assert "EPSG:5070" in result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 0
    assert_no_topology(result)


def test_wrong_crs_authority_suppresses_area_results_even_with_5070_srs_id(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [box(0, 0, 20, 20)])
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE gpkg_spatial_ref_sys SET organization = 'CUSTOM' WHERE srs_id = 5070")

    result = run_check(path)

    assert result.returncode == 2
    assert "EPSG:5070" in result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 0
    assert_no_topology(result)


def test_wrong_crs_definition_suppresses_area_results_even_with_5070_authority(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [box(0, 0, 20, 20)])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE gpkg_spatial_ref_sys SET definition = "
            "(SELECT definition FROM gpkg_spatial_ref_sys WHERE srs_id = 4326) WHERE srs_id = 5070"
        )

    result = run_check(path)

    assert result.returncode == 2
    assert "EPSG:5070" in result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 0
    assert_no_topology(result)


def test_nonpolygon_divide_is_unusable_and_suppresses_area_results(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", [Point(1, 1)])

    result = run_check(path)

    assert result.returncode == 2
    assert "unusable divide" in result.stderr
    assert geometry_value(result, "invalid_geometries.divides") == 0
    assert_no_topology(result)


def test_missing_divides_does_not_report_topology_success(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "nexus", [Point(1, 1)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "schema | missing_layer.divides | 1 |" in result.stdout
    assert geometry_value(result, "invalid_geometries.nexus") == 0
    assert_no_topology(result)


def test_nonspatial_divides_does_not_silently_skip_topology(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "nexus", [Point(1, 1)])
    pyogrio.write_dataframe(pd.DataFrame({"divide_id": [1]}), path, layer="divides")

    result = run_check(path)

    assert result.returncode == 2
    assert "divides topology incomplete" in result.stderr
    assert geometry_value(result, "invalid_geometries.nexus") == 0
    assert_no_topology(result)


def test_geopackage_with_only_attribute_tables_has_no_applicable_geometry_checks(tmp_path):
    path = tmp_path / "build.gpkg"
    pyogrio.write_dataframe(pd.DataFrame({"value": [1]}), path, layer="attributes")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert geometry_value(result, "no_applicable_checks") == 1
    assert_no_topology(result)
