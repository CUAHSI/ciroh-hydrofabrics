"""Relationship checks exercised through the consistency-check CLI."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import Point, box

RUNNER = Path(__file__).resolve().parents[2] / "consistency_check.py"


def run_check(path, kind="ngen"):
    return subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01"],
        capture_output=True,
        text=True,
        check=False,
    )


def test_network_duplicate_rows_include_geometry(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["same", "same", "same"], "toid": ["next", "next", "next"]},
        geometry=[Point(0, 0), Point(1, 0), Point(0, 0)], crs="EPSG:5070",
    ).to_file(path, layer="network", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 1 | 0 | FAIL | advisory" in result.stdout


def test_network_duplicate_rows_group_null_geometries(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["same", "same", "same"]},
        geometry=gpd.GeoSeries.from_wkt(pd.Series([None, None, "POINT (0 0)"]), crs="EPSG:5070"),
    ).to_file(path, layer="network", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 1 | 0 | FAIL | advisory" in result.stdout


def test_network_duplicate_rows_use_all_data_columns_with_nulls(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["a", "a", "a", "a", None, None], "toid": ["b", "b", "b", "c", None, None]},
        geometry=[Point(0, 0)] * 6, crs="EPSG:5070",
    ).to_file(path, layer="network", engine="pyogrio")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 3 | 0 | FAIL | advisory" in result.stdout
    assert all(" | " in line for line in result.stdout.splitlines())


def write_layer(path, name, data):
    count = len(next(iter(data.values())))
    geometry = [box(i, 0, i + 1, 1) if name == "divides" else Point(i, 0) for i in range(count)]
    gpd.GeoDataFrame(data, geometry=geometry, crs="EPSG:5070").to_file(path, layer=name, engine="pyogrio")


def test_relationship_orphans_include_nulls_and_flags_are_informational(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {
        "divide_id": ["d-1", "d-2", "d-3", "d-4", "d-5", "d-6", None],
        "id": ["f-1", "f-missing", None, "f-dup", None, "f-dup", "f-missing"],
        "has_flowline": [1, 1, 0, 0, None, 1, None],
    })
    write_layer(path, "flowpaths", {
        "id": ["f-1", "f-dup", "f-dup", "f-4", "f-5", "f-6", "f-7"],
        "divide_id": ["d-1", "d-4", "d-missing", None, None, "d-2", "d-missing"],
        "has_divide": [1, 1, 1, 0, None, 0, None],
    })
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "divide-attributes" (divide_id TEXT)')
        connection.executemany(
            'INSERT INTO "divide-attributes" VALUES (?)',
            [("d-1",), ("d-1",), ("d-3",), ("d-5",), (None,)],
        )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert all(" | " in line for line in result.stdout.splitlines())
    for metric, count in {
        "divides_without_flowpaths": 4,
        "flowpaths_without_divides": 4,
        "divides_without_attributes": 4,
        "divides_without_attributes.has_flowline_0": 1,
        "divides_without_flowpaths.has_flowline_0": 1,
        "flowpaths_without_divides.has_divide_0": 1,
    }.items():
        assert f"network | {metric} | {count} | 0 | FAIL | advisory" in result.stdout



@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_divide_without_referencing_flowpath_is_distinct_from_forward_orphan(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {
        "divide_id": ["cat-1", "cat-2", "cat-3"],
        "id": ["wb-1", "wb-2", "wb-3"],
        "has_flowline": [0, 0, 1],
    })
    write_layer(path, "flowpaths", {
        "id": ["wb-1", "wb-2", "wb-3"], "divide_id": ["cat-2", "cat-2", "cat-3"],
    })

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_flowpaths | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | flowpaths_without_divides | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | divides_without_referencing_flowpaths | 1 | 0 | FAIL | advisory" in result.stdout
    assert "network | divides_without_referencing_flowpaths.has_flowline_0 | 1 | 0 | FAIL | advisory" in result.stdout


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_unreferenced_divides_count_source_rows_including_nulls_and_duplicate_keys(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {
        "divide_id": ["cat-x", "cat-x", "cat-y", "cat-y", None, None, "cat-z"],
        "has_flowline": [0, 1, 0, 1, 0, 1, None],
    })
    write_layer(path, "flowpaths", {"divide_id": ["cat-y", "cat-y", None]})

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_referencing_flowpaths | 5 | 0 | FAIL | advisory" in result.stdout
    assert "network | divides_without_referencing_flowpaths.has_flowline_0 | 2 | 0 | FAIL | advisory" in result.stdout
    assert "network | divides_without_flowpaths |" not in result.stdout
    assert "network | reciprocal_divide_flowpath_mismatches |" not in result.stdout


def test_unreferenced_divides_with_empty_flowpaths_counts_all_source_rows(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"divide_id": [None, "cat-1", "cat-2"], "has_flowline": [0, 0, 1]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "flowpaths" (divide_id TEXT)')

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_referencing_flowpaths | 3 | 0 | FAIL | advisory" in result.stdout
    assert "network | divides_without_referencing_flowpaths.has_flowline_0 | 2 | 0 | FAIL | advisory" in result.stdout


@pytest.mark.parametrize("layer", ["divides", "flowpaths"])
def test_unreferenced_divides_metric_is_omitted_when_a_layer_is_missing(tmp_path, layer):
    path = tmp_path / "build.gpkg"
    write_layer(path, layer, {"divide_id": ["cat-1"], "has_flowline": [0]})

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_referencing_flowpaths |" not in result.stdout
    assert "network | divides_without_referencing_flowpaths.has_flowline_0 |" not in result.stdout


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_reciprocal_mismatch_is_separate_from_orphans(tmp_path, kind):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"divide_id": ["cat-1", "cat-2"], "id": ["wb-1", "wb-2"]})
    write_layer(path, "flowpaths", {"id": ["wb-1", "wb-2"], "divide_id": ["cat-2", "cat-2"]})

    result = run_check(path, kind)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_flowpaths | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | flowpaths_without_divides | 0 | 0 | PASS | advisory" in result.stdout
    # cat-1 -> wb-1 and wb-1 -> cat-2 are distinct nonreciprocal links.
    assert "network | reciprocal_divide_flowpath_mismatches | 2 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory" in result.stdout


def test_reciprocal_detects_a_flowpath_pointing_to_a_divide_with_a_different_flowpath(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"divide_id": ["cat-1"], "id": ["wb-1"]})
    write_layer(path, "flowpaths", {"id": ["wb-1", "wb-2"], "divide_id": ["cat-1", "cat-1"]})

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_flowpaths | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | flowpaths_without_divides | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_mismatches | 1 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory" in result.stdout


@pytest.mark.parametrize("duplicate_targets", [("cat-3", "cat-3"), ("cat-3", "cat-ok"), ("cat-ok", "cat-3")])
def test_reciprocal_duplicate_ids_are_ambiguous_and_nulls_or_orphans_are_skipped(tmp_path, duplicate_targets):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {
        "divide_id": ["cat-dup", "cat-dup", "cat-3", "cat-4", "cat-t", "cat-t", "cat-ok", "cat-mis",
                      "cat-no-flow", "cat-no-reverse", "cat-dangle", None, "cat-no-ref"],
        "id": ["wb-1", "wb-2", "wb-dup", "wb-4", None, None, "wb-ok", "wb-mis",
               "wb-missing", "wb-null", "wb-dangle", "wb-nodiv", None],
    })
    write_layer(path, "flowpaths", {
        "id": ["wb-1", "wb-2", "wb-dup", "wb-dup", "wb-4", "wb-ok", "wb-mis", "wb-null",
               "wb-dangle", "wb-nodiv", None],
        "divide_id": ["cat-dup", "cat-dup", *duplicate_targets, "cat-t", "cat-ok", "cat-ok", None,
                      "cat-absent", "cat-ok", "cat-mis"],
    })

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_flowpaths | 4 | 0 | FAIL | advisory" in result.stdout
    assert "network | flowpaths_without_divides | 2 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_mismatches | 3 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 9 | 0 | FAIL | advisory" in result.stdout


def test_reciprocal_skips_null_or_dangling_back_reference_even_if_source_id_is_duplicated(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"divide_id": ["cat-dup", "cat-dup", "cat-3"], "id": ["wb-1", "wb-2", "wb-3"]})
    write_layer(path, "flowpaths", {"id": ["wb-1", "wb-2", "wb-3"], "divide_id": [None, "cat-missing", "cat-3"]})

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | flowpaths_without_divides | 2 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_mismatches | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory" in result.stdout


def test_reciprocal_reference_numeric_identifiers(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"divide_id": [1.0, 2.0], "id": [10.0, 20.0]})
    write_layer(path, "flowpaths", {"id": [10.0, 20.0], "divide_id": [2.0, 2.0]})

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert "network | reciprocal_divide_flowpath_mismatches | 2 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory" in result.stdout


def test_reciprocal_shared_reference_is_checked_per_divide_row(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"divide_id": ["cat-1", "cat-2"], "id": ["wb-1", "wb-1"]})
    write_layer(path, "flowpaths", {"id": ["wb-1"], "divide_id": ["cat-1"]})

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | reciprocal_divide_flowpath_mismatches | 1 | 0 | FAIL | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory" in result.stdout


def test_reciprocal_empty_tables_report_zero(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "base", {"name": ["example"]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "divides" (id TEXT, divide_id TEXT)')
        connection.execute('CREATE TABLE "flowpaths" (id TEXT, divide_id TEXT)')

    result = run_check(path)

    assert result.returncode == 2
    assert "divides is not a spatial layer" in result.stderr
    assert "network | reciprocal_divide_flowpath_mismatches | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | divides_without_referencing_flowpaths | 0 | 0 | PASS | advisory" in result.stdout


def test_ngen_hydrolocations_count_null_and_unmatched_nexus_references(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "hydrolocations", {"nex_id": ["nex-1", None, "nex-missing", "nex-dup"]})
    write_layer(path, "nexus", {"id": ["nex-1", "nex-dup", "nex-dup", None]})

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | hydrolocations_without_nexus | 2 | 0 | FAIL | advisory" in result.stdout


def test_reference_omits_nextgen_only_relationships_even_if_tables_exist(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"id": [None], "divide_id": ["d-1"], "has_flowline": [0]})
    write_layer(path, "flowpaths", {"id": [None], "divide_id": [None], "has_divide": [0]})
    write_layer(path, "hydrolocations", {"nex_id": [None]})
    write_layer(path, "nexus", {"id": [None]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "divide-attributes" (divide_id TEXT)')

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    for metric in ("divides_without_flowpaths", "flowpaths_without_divides",
                   "divides_without_flowpaths.has_flowline_0", "flowpaths_without_divides.has_divide_0"):
        assert f"network | {metric} | 1 | 0 | FAIL | advisory" in result.stdout
    assert "network | divides_without_attributes |" not in result.stdout
    assert "network | divides_without_attributes.has_flowline_0 |" not in result.stdout
    assert "network | hydrolocations_without_nexus |" not in result.stdout


@pytest.mark.parametrize(
    "missing_table,missing_column,metric",
    [
        ("divides", "id", "divides_without_flowpaths"),
        ("flowpaths", "id", "divides_without_flowpaths"),
        ("divides", "divide_id", "divides_without_referencing_flowpaths"),
        ("flowpaths", "divide_id", "divides_without_referencing_flowpaths"),
        ("flowpaths", "divide_id", "flowpaths_without_divides"),
        ("divides", "divide_id", "flowpaths_without_divides"),
        ("divides", "divide_id", "divides_without_attributes"),
        ("divide-attributes", "divide_id", "divides_without_attributes"),
        ("hydrolocations", "nex_id", "hydrolocations_without_nexus"),
        ("nexus", "id", "hydrolocations_without_nexus"),
    ],
)
def test_relationship_metric_is_omitted_when_a_key_column_is_missing(
    tmp_path, missing_table, missing_column, metric,
):
    path = tmp_path / "build.gpkg"
    write_layer(path, "base", {"name": ["example"]})
    tables = {
        "divides": ["id", "divide_id", "has_flowline"],
        "flowpaths": ["id", "divide_id", "has_divide"],
        "divide-attributes": ["divide_id"],
        "hydrolocations": ["nex_id"],
        "nexus": ["id"],
    }
    tables[missing_table].remove(missing_column)
    with sqlite3.connect(path) as connection:
        for table, fields in tables.items():
            declarations = [f'"{field}" TEXT' for field in fields] or ['"other" TEXT']
            connection.execute(f'CREATE TABLE "{table}" ({", ".join(declarations)})')

    result = run_check(path)

    assert result.returncode == 2
    assert "divides is not a spatial layer" in result.stderr
    assert f"network | {metric} |" not in result.stdout
    if missing_table in {"divides", "flowpaths"}:
        assert "network | reciprocal_divide_flowpath_mismatches |" not in result.stdout
        assert "network | reciprocal_divide_flowpath_ambiguous |" not in result.stdout
    if metric == "divides_without_flowpaths":
        assert "network | divides_without_flowpaths.has_flowline_0 |" not in result.stdout
    if metric == "divides_without_referencing_flowpaths":
        assert "network | divides_without_referencing_flowpaths.has_flowline_0 |" not in result.stdout
    if metric == "flowpaths_without_divides":
        assert "network | flowpaths_without_divides.has_divide_0 |" not in result.stdout
    if metric == "divides_without_attributes":
        assert "network | divides_without_attributes.has_flowline_0 |" not in result.stdout


def test_network_counts_duplicates_of_full_row_not_repeated_id(tmp_path):
    path = tmp_path / "build.gpkg"
    destinations = [f"destination-{i}" for i in range(500)]
    destinations.extend(["destination-17", "destination-17", "destination-200", "destination-17"])
    gpd.GeoDataFrame(
        {
            "id": ["same-id"] * len(destinations),
            "toid": destinations,
            'other"field': ["same-value"] * (len(destinations) - 1) + ["different-value"],
        },
        geometry=[Point(0, 0)] * len(destinations), crs="EPSG:5070",
    ).to_file(path, layer="network", engine="pyogrio")

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 3 | 0 | FAIL | advisory" in result.stdout


def test_duplicate_rows_include_custom_geometry_and_exclude_case_variant_fid(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(
        {"id": ["same", "same", "same"]}, geometry=[Point(0, 0), Point(0, 0), Point(1, 0)], crs="EPSG:5070",
    ).to_file(path, layer="network", engine="pyogrio", FID="FID", GEOMETRY_NAME="shape")

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 1 | 0 | FAIL | advisory" in result.stdout


def test_empty_target_and_orphan_flag_subset_are_reported(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"id": [None, "f-missing"], "has_flowline": [0, 1]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "flowpaths" (id TEXT)')

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_flowpaths | 2 | 0 | FAIL | advisory" in result.stdout
    assert "network | divides_without_flowpaths.has_flowline_0 | 1 | 0 | FAIL | advisory" in result.stdout
    assert "network | flowpaths_without_divides |" not in result.stdout
    assert "network | flowpaths_without_divides.has_divide_0 |" not in result.stdout


def test_empty_source_reports_zero_orphans_and_zero_flag_subset(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "base", {"name": ["example"]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "divides" (id TEXT, has_flowline BOOLEAN)')
        connection.execute('CREATE TABLE "flowpaths" (id TEXT)')

    result = run_check(path)

    assert result.returncode == 2
    assert "divides is not a spatial layer" in result.stderr
    assert "network | divides_without_flowpaths | 0 | 0 | PASS | advisory" in result.stdout
    assert "network | divides_without_flowpaths.has_flowline_0 | 0 | 0 | PASS | advisory" in result.stdout


def test_network_with_only_geometry_counts_duplicate_rows(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame(geometry=[Point(0, 0), Point(1, 0), Point(0, 0)], crs="EPSG:5070").to_file(
        path, layer="network", engine="pyogrio"
    )

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 1 | 0 | FAIL | advisory" in result.stdout


def test_network_with_only_fid_omits_duplicate_metric(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "base", {"name": ["example"]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "network" (fid INTEGER PRIMARY KEY)')
        connection.executemany('INSERT INTO "network" (fid) VALUES (?)', [(1,), (2,)])

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows |" not in result.stdout


def test_nonspatial_network_counts_all_data_columns_and_nulls(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "base", {"name": ["example"]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "network" (fid INTEGER PRIMARY KEY, id TEXT, toid TEXT, extra TEXT)')
        connection.executemany(
            'INSERT INTO "network" (id, toid, extra) VALUES (?, ?, ?)',
            [("x", "y", None), ("x", "y", None), ("x", "y", "different"), ("x", "z", None)],
        )

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 1 | 0 | FAIL | advisory" in result.stdout


def test_network_duplicate_rows_compare_text_exactly_even_with_nocase_columns(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "base", {"name": ["example"]})
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "network" (fid INTEGER PRIMARY KEY, id TEXT COLLATE NOCASE)')
        connection.executemany('INSERT INTO "network" (id) VALUES (?)', [("a",), ("A",), ("a",)])

    result = run_check(path, "reference")

    assert result.returncode == 0, result.stderr
    assert "network | duplicate_network_rows | 1 | 0 | FAIL | advisory" in result.stdout


@pytest.mark.parametrize(
    "missing_flag,orphan_metric,subset_metric",
    [
        ("has_flowline", "divides_without_flowpaths", "divides_without_flowpaths.has_flowline_0"),
        ("has_flowline", "divides_without_referencing_flowpaths", "divides_without_referencing_flowpaths.has_flowline_0"),
        ("has_divide", "flowpaths_without_divides", "flowpaths_without_divides.has_divide_0"),
        ("has_flowline", "divides_without_attributes", "divides_without_attributes.has_flowline_0"),
    ],
)
def test_orphan_metric_is_reported_without_missing_flag_subset(tmp_path, missing_flag, orphan_metric, subset_metric):
    path = tmp_path / "build.gpkg"
    divides = {"id": [None], "divide_id": ["d-1"]}
    flowpaths = {"id": ["f-1"], "divide_id": [None]}
    if missing_flag != "has_flowline":
        divides["has_flowline"] = [0]
    if missing_flag != "has_divide":
        flowpaths["has_divide"] = [0]
    write_layer(path, "divides", divides)
    write_layer(path, "flowpaths", flowpaths)
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "divide-attributes" (divide_id TEXT)')

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert f"network | {orphan_metric} | 1 | 0 | FAIL | advisory" in result.stdout
    assert f"network | {subset_metric} |" not in result.stdout


def test_flag_subsets_are_omitted_without_relationship_columns_or_target_tables(tmp_path):
    path = tmp_path / "build.gpkg"
    write_layer(path, "divides", {"has_flowline": [0, 0, 1, None, 2]})
    write_layer(path, "flowpaths", {"has_divide": [0, 1, None, 2, 0]})

    result = run_check(path)

    assert result.returncode == 0, result.stderr
    assert "network | divides_without_flowpaths.has_flowline_0 |" not in result.stdout
    assert "network | divides_without_referencing_flowpaths.has_flowline_0 |" not in result.stdout
    assert "network | flowpaths_without_divides.has_divide_0 |" not in result.stdout
    assert "network | divides_without_attributes.has_flowline_0 |" not in result.stdout
    for metric in ("divides_without_flowpaths", "flowpaths_without_divides", "divides_without_attributes"):
        assert f"network | {metric} |" not in result.stdout
