"""Routing graph behavior exercised through the consistency-check CLI."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Point, box

RUNNER = Path(__file__).resolve().parents[2] / "consistency_check.py"


def write_layer(path, name, data):
    count = len(next(iter(data.values())))
    geometry = [box(index, 0, index + 1, 1) if name == "divides" else Point(index, 0) for index in range(count)]
    gpd.GeoDataFrame(data, geometry=geometry, crs="EPSG:5070").to_file(path, layer=name, engine="pyogrio")


def run_check(path, kind):
    result = subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_reference_flowpath_dangling_targets_exclude_numeric_terminal(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1, 2, 3, 4], "toid": [2, 0, 99, None]})

    report = run_check(path, "reference")

    assert "network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory" in report
    assert "network | indeterminate_null_toid.flowpaths | 1 | 0 | FAIL | advisory" in report


def test_reference_cycles_count_only_members_and_keep_conflicting_edges(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {
        "id": [1, 2, 2, 2, 2, 3, 5, 6], "toid": [2, 3, 1, 6, 6, 6, 5, 0],
    })

    report = run_check(path, "reference")

    assert "network | cycle_nodes.flowpaths | 3 | 0 | FAIL | advisory" in report


def test_reference_network_deduplicates_edges_but_counts_dangling_rows(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "network", {
        "id": [1, 1, 2, 2, 3, 4, 5, 5], "toid": [2, 2, 1, 3, 0, 4, 99, 99],
    })

    report = run_check(path, "reference")

    assert "network | dangling_toid.network | 2 | 0 | FAIL | advisory" in report
    assert "network | cycle_nodes.network | 3 | 0 | FAIL | advisory" in report


def test_nextgen_routing_uses_all_actual_ids_and_combines_layer_graphs(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["wb-1", "wb-2", "wb-3"], "toid": ["nex-1", "cnx-1", "nex-missing"],
    })
    write_layer(path, "nexus", {
        "id": ["nex-1", "nex-1", "nex-1", "cnx-1", "inx-1", "nex-2", "nex-3"],
        "toid": ["wb-2", "wb-1", "wb-3", "wb-0", "wb-0", "wb-net", "wb-missing"],
    })
    write_layer(path, "network", {
        "id": ["wb-1", "wb-1", "nex-1", "nex-1", "wb-2", "wb-net", "nex-4", "nex-5", "nex-6"],
        "toid": ["nex-1", "nex-1", "wb-1", "wb-2", "cnx-1", "inx-1", "nex-5", "missing", "wb-3"],
    })

    report = run_check(path, "ngen")

    assert "network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory" in report
    assert "network | dangling_toid.nexus | 2 | 0 | FAIL | advisory" in report
    assert "network | dangling_toid.network | 1 | 0 | FAIL | advisory" in report
    assert "network | cycle_nodes.flowpaths_nexus | 2 | 0 | FAIL | advisory" in report
    assert "network | cycle_nodes.network | 2 | 0 | FAIL | advisory" in report


def test_nextgen_flowpath_targets_must_exist_in_nexus_not_other_layers(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["wb-1", "wb-2", "wb-3", "wb-4"],
        "toid": ["wb-2", "nex-network-only", "nex-actual", "wb-0"],
    })
    write_layer(path, "nexus", {"id": ["nex-actual"], "toid": ["wb-0"]})
    write_layer(path, "network", {"id": ["nex-network-only"], "toid": ["wb-0"]})

    report = run_check(path, "ngen")

    assert "network | dangling_toid.flowpaths | 2 | 0 | FAIL | advisory" in report


@pytest.mark.parametrize("layer", ["flowpath-attributes", "flowpath-attributes-ml"])
def test_nextgen_attribute_targets_resolve_in_nexus_and_nulls_are_indeterminate(tmp_path, layer):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "nexus", {"id": ["nex-actual", "nex-actual"], "toid": ["wb-0", "wb-0"]})
    write_layer(path, "flowpaths", {"id": ["wb-1"], "toid": ["nex-actual"]})
    write_layer(path, "network", {"id": ["nex-network-only"], "toid": ["nex-actual"]})
    with sqlite3.connect(path) as connection:
        connection.execute(f'CREATE TABLE "{layer}" (fid INTEGER PRIMARY KEY, id TEXT, toid TEXT)')
        connection.executemany(
            f'INSERT INTO "{layer}" (id, toid) VALUES (?, ?)',
            [("wb-1", target) for target in (
                "nex-actual", "nex-missing", "nex-network-only", "wb-1", None, "wb-0", "nex-missing"
            )],
        )
        connection.execute(
            "INSERT INTO gpkg_contents (table_name, data_type, identifier, srs_id) VALUES (?, 'attributes', ?, 0)",
            (layer, layer),
        )

    report = run_check(path, "ngen")

    assert f"network | dangling_toid.{layer} | 4 | 0 | FAIL | advisory" in report
    assert f"network | indeterminate_null_toid.{layer} | 1 | 0 | FAIL | advisory" in report
    assert f"network | terminal_convention.{layer} | 1 | 0 | FAIL | advisory" in report


def test_nextgen_attribute_checks_skip_only_missing_prerequisites(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "nexus", {"label": ["not-an-id"]})
    write_layer(path, "flowpath-attributes", {"toid": ["nex-1", None]})
    write_layer(path, "flowpath-attributes-ml", {"id": ["wb-1"]})

    report = run_check(path, "ngen")

    assert "network | indeterminate_null_toid.flowpath-attributes | 1 | 0 | FAIL | advisory" in report
    assert "network | terminal_convention.flowpath-attributes | 0 | 0 | PASS | advisory" in report
    assert "network | dangling_toid.flowpath-attributes |" not in report
    assert "network | indeterminate_null_toid.flowpath-attributes-ml |" not in report
    assert "network | dangling_toid.flowpath-attributes-ml |" not in report
    assert "network | terminal_convention.flowpath-attributes-ml |" not in report


def test_nextgen_attribute_checks_need_only_source_toid_and_nexus_id(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "nexus", {"id": ["nex-1"]})
    for layer in ("flowpath-attributes", "flowpath-attributes-ml"):
        write_layer(path, layer, {"toid": ["nex-1", "nex-missing", None]})

    report = run_check(path, "ngen")

    for layer in ("flowpath-attributes", "flowpath-attributes-ml"):
        assert f"network | dangling_toid.{layer} | 1 | 0 | FAIL | advisory" in report
        assert f"network | indeterminate_null_toid.{layer} | 1 | 0 | FAIL | advisory" in report


def test_reference_does_not_apply_nextgen_attribute_routing_checks(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpath-attributes", {"toid": [None, "nex-missing"]})
    write_layer(path, "flowpath-attributes-ml", {"toid": [None, "nex-missing"]})

    report = run_check(path, "reference")

    assert "network | dangling_toid.flowpath-attributes" not in report
    assert "network | indeterminate_null_toid.flowpath-attributes" not in report
    assert "network | terminal_convention.flowpath-attributes" not in report


def test_nextgen_nexus_targets_must_exist_in_flowpaths_not_other_layers(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-actual"], "toid": ["nex-1"]})
    write_layer(path, "nexus", {
        "id": ["nex-1", "nex-2", "nex-3", "tnx-1"],
        "toid": ["wb-network-only", "nex-3", "wb-actual", "wb-0"],
    })
    write_layer(path, "network", {"id": ["wb-network-only"], "toid": ["wb-0"]})

    report = run_check(path, "ngen")

    assert "network | dangling_toid.nexus | 2 | 0 | FAIL | advisory" in report


def test_nextgen_divide_targets_resolve_in_nexus_including_coastal_internal(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "divides", {
        "divide_id": ["cat-1", "cat-2", "cat-3", "cat-4", "cat-5", "cat-6"],
        "toid": ["cnx-1", "inx-1", "inx-missing", "nex-network-only", "wb-1", "wb-0"],
    })
    write_layer(path, "nexus", {"id": ["cnx-1", "inx-1"], "toid": ["wb-0", "wb-0"]})
    write_layer(path, "flowpaths", {"id": ["wb-1"], "toid": ["cnx-1"]})
    write_layer(path, "network", {"id": ["nex-network-only"], "toid": ["inx-1"]})

    report = run_check(path, "ngen")

    assert "network | dangling_toid.divides | 3 | 0 | FAIL | advisory" in report
    assert "network | terminal_convention.divides | 1 | 0 | FAIL | advisory" in report


def test_nextgen_nexus_outlet_convention_reports_untyped_and_shared_outlets(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "nexus", {
        "id": ["tnx-1", "cnx-1", "inx-1", "tnx-2", "tnx-3", "cnx-2", "inx-2",
               "nex-1", "nex-2", None, "tnx-4", "nex-3", "nex-4"],
        "type": ["terminal", "coastal", "internal", "terminal", "internal", "terminal", "internal",
                 "nexus", None, None, None, "terminal", "nexus"],
        "toid": ["wb-0", "wb-0", "wb-0", "wb-1", "wb-0", "wb-0", None,
                 "wb-0", "wb-0", "wb-0", "wb-0", "wb-1", "wb-1"],
    })

    report = run_check(path, "ngen")

    assert "network | terminal_convention.nexus | 9 | 0 | FAIL | advisory" in report
    assert "network | indeterminate_null_toid.nexus | 1 | 0 | FAIL | advisory" in report


def test_nextgen_network_outlet_check_does_not_misclassify_terminal_flowpaths(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "network", {
        "id": ["wb-1", "tnx-1", "inx-1", "cnx-1", "nex-1", "tnx-2", "nex-2", "wb-2", None],
        "type": ["terminal", "terminal", "internal", "coastal", "nexus", "terminal", "terminal", "terminal", None],
        "toid": ["tnx-1", "wb-0", "wb-0", "wb-0", "wb-0", "wb-1", "wb-1", "wb-0", "wb-0"],
    })

    report = run_check(path, "ngen")

    assert "network | terminal_convention.network | 5 | 0 | FAIL | advisory" in report


def test_nextgen_flowpaths_must_not_use_the_nexus_outlet_sentinel(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-1", "wb-2", "wb-3"], "toid": ["wb-0", "tnx-1", None]})

    report = run_check(path, "ngen")

    assert "network | terminal_convention.flowpaths | 1 | 0 | FAIL | advisory" in report


def test_missing_fields_skip_only_dependent_nextgen_metrics(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-1"], "toid": ["nex-1"]})
    write_layer(path, "nexus", {"id": ["nex-1"], "type": ["nexus"]})
    write_layer(path, "network", {"id": ["wb-1"], "toid": ["nex-1"], "type": ["flowpath"]})

    report = run_check(path, "ngen")

    assert "network | dangling_toid.flowpaths | 0 | 0 | PASS | advisory" in report
    assert "network | dangling_toid.network | 0 | 0 | PASS | advisory" in report
    assert "network | cycle_nodes.network | 0 | 0 | PASS | advisory" in report
    assert "network | terminal_convention.network | 0 | 0 | PASS | advisory" in report
    assert "network | dangling_toid.nexus |" not in report
    assert "network | cycle_nodes.flowpaths_nexus |" not in report
    assert "network | terminal_convention.nexus |" not in report


def test_nextgen_layer_dangling_checks_do_not_require_network_ids(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-1"], "toid": ["nex-1"]})
    write_layer(path, "divides", {"toid": ["nex-1"]})
    write_layer(path, "nexus", {"id": ["nex-1"], "toid": ["wb-1"]})
    write_layer(path, "network", {"toid": ["nex-1"]})

    report = run_check(path, "ngen")

    assert "network | cycle_nodes.flowpaths_nexus | 2 | 0 | FAIL | advisory" in report
    assert "network | dangling_toid.flowpaths | 0 | 0 | PASS | advisory" in report
    assert "network | dangling_toid.divides | 0 | 0 | PASS | advisory" in report
    assert "network | dangling_toid.nexus | 0 | 0 | PASS | advisory" in report
    assert "network | dangling_toid.network |" not in report
    assert "network | cycle_nodes.network |" not in report
    assert "network | terminal_convention.flowpaths | 0 | 0 | PASS | advisory" in report
    assert "network | terminal_convention.nexus |" not in report
    assert "network | terminal_convention.network |" not in report


def test_missing_nexus_ids_only_skip_checks_that_need_nexus_targets(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-1"], "toid": ["nex-1"]})
    write_layer(path, "divides", {"toid": ["nex-1"]})
    write_layer(path, "nexus", {"toid": ["wb-1"]})
    write_layer(path, "network", {"id": ["wb-1"], "toid": ["wb-1"]})

    report = run_check(path, "ngen")

    assert "network | dangling_toid.nexus | 0 | 0 | PASS | advisory" in report
    for layer in ("flowpaths", "divides", "network"):
        assert f"network | dangling_toid.{layer} |" not in report
        assert f"network | indeterminate_null_toid.{layer} | 0 | 0 | PASS | advisory" in report


def test_missing_flowpath_ids_only_skip_checks_that_need_flowpath_targets(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"toid": ["nex-1"]})
    write_layer(path, "divides", {"toid": ["nex-1"]})
    write_layer(path, "nexus", {"id": ["nex-1"], "toid": ["wb-1"]})
    write_layer(path, "network", {"id": ["wb-1"], "toid": ["nex-1"]})

    report = run_check(path, "ngen")

    for layer in ("flowpaths", "divides"):
        assert f"network | dangling_toid.{layer} | 0 | 0 | PASS | advisory" in report
    for layer in ("nexus", "network"):
        assert f"network | dangling_toid.{layer} |" not in report
        assert f"network | indeterminate_null_toid.{layer} | 0 | 0 | PASS | advisory" in report


def test_reference_missing_toid_skips_routing_metrics(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1]})
    write_layer(path, "network", {"id": [1]})

    report = run_check(path, "reference")

    assert "network | dangling_toid." not in report
    assert "network | indeterminate_null_toid." not in report
    assert "network | cycle_nodes." not in report


@pytest.mark.parametrize(
    ("kind", "layers", "target"),
    [("ngen", ("divides", "flowpaths", "nexus", "network"), "wb-0"),
     ("reference", ("flowpaths", "network"), 0)],
)
def test_null_toids_are_indeterminate_without_target_prerequisites(tmp_path, kind, layers, target):
    path = tmp_path / "build.gpkg"
    for layer in layers:
        write_layer(path, layer, {"toid": [None, target, None]})

    report = run_check(path, kind)

    for layer in layers:
        assert f"network | indeterminate_null_toid.{layer} | 2 | 0 | FAIL | advisory" in report
        assert f"network | dangling_toid.{layer} |" not in report


def test_reference_string_zero_is_not_the_numeric_sentinel(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1], "toid": ["0"]})

    report = run_check(path, "reference")

    assert "network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory" in report


def test_cycles_are_detected_beyond_python_recursion_limit(tmp_path):
    path = tmp_path / "reference.gpkg"
    size = 1800
    write_layer(path, "flowpaths", {
        "id": list(range(1, size + 2)),
        "toid": list(range(2, size + 1)) + [1, 0],
    })

    report = run_check(path, "reference")

    assert "network | cycle_nodes.flowpaths | 1800 | 0 | FAIL | advisory" in report
