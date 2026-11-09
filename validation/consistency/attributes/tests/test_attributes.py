"""Attribute Consistency Checks exercised through the real CLI."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pytest
import yaml
from shapely.geometry import Point, box

RUNNER = Path(__file__).resolve().parents[2] / "consistency_check.py"


def run_check(path, kind="ngen", *extra):
    return subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01", *map(str, extra)],
        capture_output=True, text=True, check=False,
    )


def metric(result, name):
    lines = [line.split(" | ") for line in result.stdout.splitlines()
             if line.startswith(f"attributes | {name} | ")]
    assert len(lines) == 1, (name, result.stdout, result.stderr)
    return lines[0]


def create_gpkg(path):
    gpd.GeoDataFrame({"id": ["one"]}, geometry=[Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="nexus", engine="pyogrio"
    )


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_positive_divide_area_is_reported_for_both_products(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"areasqkm": [1.0, 0.0, -1.0]},
        geometry=[box(0, 0, 1, 1), box(2, 0, 3, 1), box(4, 0, 5, 1)], crs="EPSG:5070",
    ).to_file(path, layer="divides", engine="pyogrio")

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.divides.areasqkm_positive")[2:] == ["2", "0", "FAIL", "advisory"]


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_flowpath_area_applies_only_to_valid_has_divide_flags(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL, areasqkm REAL, has_divide)')
        db.executemany('INSERT INTO flowpaths VALUES (?, ?, ?, ?)', [
            ("one", 1, 0, 1), ("two", 1, 0, 0), ("three", 1, 0, None),
            ("four", 1, 0, 2), ("five", 1, 1, 1),
        ])

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.flowpaths.areasqkm_positive_with_divide")[2] == "1"
    assert metric(result, "indeterminate_applicability.flowpaths.areasqkm_positive_with_divide")[2:5] == ["2", "-", "INFO"]


def test_numeric_diagnostics_and_hydraulic_boundaries(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL, So REAL, n REAL, MusX REAL)')
        db.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?, ?, ?, ?)', [
            ("one", 1, 0, 0, 0), ("two", 1, -9998, 1, .5),
            ("three", 1, None, 1.01, .51), ("four", 1, "bad", -1, -.01),
            ("five", 1, float("inf"), .5, .2),
        ])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.flowpath-attributes.So_nonnegative")[2] == "1"
    assert metric(result, "sentinel.flowpath-attributes.So")[2] == "1"
    assert metric(result, "invalid_numeric.flowpath-attributes.So")[2] == "2"
    assert metric(result, "indeterminate_null.flowpath-attributes.So")[2:5] == ["1", "-", "INFO"]
    assert metric(result, "violations.flowpath-attributes.n_range")[2] == "3"
    assert metric(result, "violations.flowpath-attributes.MusX_range")[2] == "2"


def test_terrain_slope_uses_physical_degree_bounds(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "divide-attributes" ("mean.slope" REAL)')
        db.executemany('INSERT INTO "divide-attributes" VALUES (?)', [(-0.1,), (0,), (90,), (90.1,)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.divide-attributes.mean.slope_range")[2] == "2"


def test_impervious_surface_is_checked_as_a_percentage(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "divide-attributes" ("mean.impervious" REAL)')
        db.executemany('INSERT INTO "divide-attributes" VALUES (?)', [(-0.1,), (0,), (50,), (100,), (100.1,)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.divide-attributes.mean.impervious_range")[2] == "2"


@pytest.mark.parametrize("column", [
    "mean.slope_1km",
    "mean.smcmax_soil_layers_stag=1", "mean.smcmax_soil_layers_stag=2",
    "mean.smcmax_soil_layers_stag=3", "mean.smcmax_soil_layers_stag=4",
    "mean.smcwlt_soil_layers_stag=1", "mean.smcwlt_soil_layers_stag=2",
    "mean.smcwlt_soil_layers_stag=3", "mean.smcwlt_soil_layers_stag=4",
])
def test_drainage_factor_and_volumetric_soil_moisture_are_bounded(tmp_path, column):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute(f'CREATE TABLE "divide-attributes" ("{column}" REAL)')
        db.executemany('INSERT INTO "divide-attributes" VALUES (?)', [(-0.1,), (0,), (1,), (1.1,)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, f"violations.divide-attributes.{column}_range")[2] == "2"


def test_sentinel_is_reported_in_an_unbounded_numeric_model_column(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "divide-attributes" ("mean.elevation" REAL)')
        db.executemany('INSERT INTO "divide-attributes" VALUES (?)', [(-9998,), (2.0,)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "sentinel.divide-attributes.mean.elevation")[2] == "1"
    assert metric(result, "not_checked.divide-attributes.mean.elevation")[4] == "INFO"


def test_length_comparison_reports_only_unambiguous_pairs(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL)')
        db.executemany('INSERT INTO flowpaths VALUES (?, ?)', [
            ("exact", 1), ("within", 1), ("bad", 1), ("dup-left", 1),
            ("dup-right", 1), ("dup-right", 2), ("right-only", 1), (None, 1),
            ("overflow", 1e308),
        ])
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL)')
        db.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?)', [
            ("exact", 1000), ("within", 1001), ("bad", 1001.1),
            ("dup-left", 1), ("dup-left", 2000), ("dup-right", 1000),
            ("left-only", 1000), (None, 1), ("overflow", 1),
        ])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    rule = "flowpath-attributes.length_consistency"
    assert metric(result, f"violations.{rule}")[2] == "1"
    assert metric(result, f"indeterminate_duplicate_keys.{rule}")[2:5] == ["2", "-", "INFO"]
    assert metric(result, f"unmatched_left_rows.{rule}")[2:5] == ["1", "-", "INFO"]
    assert metric(result, f"unmatched_right_rows.{rule}")[2:5] == ["1", "-", "INFO"]
    assert metric(result, f"null_join_key_left_rows.{rule}")[2:5] == ["1", "-", "INFO"]
    assert metric(result, f"null_join_key_right_rows.{rule}")[2:5] == ["1", "-", "INFO"]
    assert metric(result, f"nonfinite_calculation.{rule}")[2] == "1"


def test_unmatched_duplicate_keys_are_reported_as_indeterminate(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL)')
        db.executemany('INSERT INTO flowpaths VALUES (?, ?)', [("right-only", 1), ("right-only", 1)])
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL)')
        db.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?)', [("left-only", 1000), ("left-only", 1000)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    rule = "flowpath-attributes.length_consistency"
    assert metric(result, f"indeterminate_duplicate_keys.{rule}")[2] == "2"
    assert metric(result, f"unmatched_left_rows.{rule}")[2] == "2"
    assert metric(result, f"unmatched_right_rows.{rule}")[2] == "2"


def test_length_comparison_handles_minimum_sqlite_integer(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm INTEGER)')
        db.execute('INSERT INTO flowpaths VALUES (?, ?)', ("one", 0))
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m INTEGER)')
        db.execute('INSERT INTO "flowpath-attributes" VALUES (?, ?)', ("one", -(2**63)))

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.flowpath-attributes.length_consistency")[2] == "1"


def test_length_report_distinguishes_compared_and_indeterminate_pairs(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL)')
        db.executemany('INSERT INTO flowpaths VALUES (?, ?)', [("good", 1), ("null", 1), ("bad", 1)])
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL)')
        db.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?)', [("good", 1000), ("null", None), ("bad", "bad")])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    rule = "flowpath-attributes.length_consistency"
    assert metric(result, f"compared_pairs.{rule}")[2:5] == ["1", "-", "INFO"]
    assert metric(result, f"indeterminate_operands.{rule}")[2:5] == ["2", "-", "INFO"]


def test_length_join_uses_exact_text_ids_and_reports_other_types(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id NUMERIC, lengthkm REAL)')
        db.executemany('INSERT INTO flowpaths VALUES (?, ?)', [(1, 1), ("A", 1)])
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT COLLATE NOCASE, Length_m REAL)')
        db.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?)', [
            ("1", 1000), ("01", 2000), ("a", 1000),
        ])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    rule = "flowpath-attributes.length_consistency"
    assert metric(result, f"violations.{rule}")[2] == "0"
    assert metric(result, f"invalid_join_key_right_rows.{rule}")[2:5] == ["1", "-", "INFO"]
    assert metric(result, f"unmatched_left_rows.{rule}")[2] == "3"
    assert metric(result, f"unmatched_right_rows.{rule}")[2] == "1"


def test_length_tolerance_does_not_hide_large_absolute_mismatches(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL)')
        db.execute('INSERT INTO flowpaths VALUES (?, ?)', ("one", 1e13))
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL)')
        db.execute('INSERT INTO "flowpath-attributes" VALUES (?, ?)', ("one", 10000000000000002.0))

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.flowpath-attributes.length_consistency")[2] == "1"


def test_length_tolerance_accounts_for_float_roundoff_at_the_boundary(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL)')
        db.executemany('INSERT INTO flowpaths VALUES (?, ?)', [("exact", 2.007), ("outside", 2.007)])
        db.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL)')
        db.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?)', [("exact", 2006), ("outside", 2005.999)])

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert metric(result, "violations.flowpath-attributes.length_consistency")[2] == "1"


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_columns_without_bounds_are_listed_as_not_checked(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert metric(result, "not_checked.flowpaths.id")[2:5] == ["1", "-", "INFO"]
    assert "attributes | not_checked.flowpaths.lengthkm |" not in result.stdout


def test_attribute_blocking_uses_recorded_limits_and_checks_ml_table(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE "flowpath-attributes-ml" (So REAL)')
        db.execute('INSERT INTO "flowpath-attributes-ml" VALUES (-0.1)')
    config = tmp_path / "checks.yaml"
    config.write_text(yaml.safe_dump({
        "geopackage_layers": {"blocking": False}, "schema": {"blocking": False},
        "network": {"blocking": False}, "geometry": {"blocking": False},
        "attributes": {"blocking": True},
    }))
    counts = tmp_path / "counts.yaml"
    counts.write_text(yaml.safe_dump({"v2.2": {"ngen": {"01": {"attributes": {
        "violations.flowpath-attributes-ml.So_nonnegative": 1,
    }}}}}))

    failed = run_check(path, "ngen", "--config", config)
    passed = run_check(path, "ngen", "--config", config, "--counts", counts)

    assert failed.returncode == 1, failed.stderr
    assert metric(failed, "violations.flowpath-attributes-ml.So_nonnegative")[2:] == ["1", "0", "FAIL", "blocking"]
    assert passed.returncode == 0, passed.stderr
    assert metric(passed, "violations.flowpath-attributes-ml.So_nonnegative")[2:] == ["1", "1", "PASS", "blocking"]


def test_missing_prerequisites_are_not_mistaken_for_a_pass(tmp_path):
    path = tmp_path / "build.gpkg"
    create_gpkg(path)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE flowpaths (areasqkm REAL)')
        db.execute('INSERT INTO flowpaths VALUES (1)')

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert metric(result, "no_applicable_checks")[2] == "1"
    assert metric(result, "not_evaluated.flowpaths.areasqkm_positive_with_divide")[2:5] == ["1", "-", "INFO"]
    assert "attributes | violations.flowpaths.areasqkm_positive_with_divide |" not in result.stdout
