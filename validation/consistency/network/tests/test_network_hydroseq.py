"""Hydrosequence consistency behavior through the command-line interface."""

import sqlite3
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import Point


RUNNER = Path(__file__).resolve().parents[2] / "consistency_check.py"


def write_layer(path, layer, data):
    size = len(next(iter(data.values())))
    gpd.GeoDataFrame(
        data, geometry=[Point(i, 0) for i in range(size)], crs="EPSG:5070"
    ).to_file(path, layer=layer, engine="pyogrio", layer_options={"SPATIAL_INDEX": "NO"})


def write_network(path, data):
    pyogrio.write_dataframe(pd.DataFrame(data), path, layer="network", driver="GPKG")


def run_check(path, kind):
    result = subprocess.run(
        [sys.executable, str(RUNNER), str(path), "--type", kind, "--vpu", "01"],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return {
        parts[1]: int(parts[2])
        for line in result.stdout.splitlines()
        if (parts := [part.strip() for part in line.split("|")])[0] == "network"
    }


def test_reference_compares_the_actual_downstream_flowpath(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {
        "id": [101, 102, 103, 104],
        "toid": [102, 103, 0, 102],
        "hydroseq": [40, 20, 15, 10],
        "dnhydroseq": [15, 15, 999, 20],
    })

    metrics = run_check(path, "reference")

    assert metrics["dnhydroseq_mismatches.flowpaths"] == 1
    assert metrics["hydroseq_order_violations.flowpaths"] == 1
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 0
    assert metrics["hydroseq_order_ambiguous.flowpaths"] == 0
    assert metrics["dnhydroseq_indeterminate.flowpaths"] == 0
    assert metrics["dnhydroseq_ambiguous.flowpaths"] == 0


def test_reference_network_compares_each_row_to_its_downstream_flowpath(tmp_path):
    path = tmp_path / "reference.gpkg"
    # The target network row deliberately disagrees with the target flowpath.
    # Two network rows share a source ID, as in the official Reference product.
    write_layer(path, "flowpaths", {
        "id": [100, 200, 300], "hydroseq": [50, 20, 10],
    })
    write_network(path, {
        "id": [100, 100, 200, 300],
        "toid": [200, 200, 300, 0],
        "hydroseq": [50, 50, 5, 10],
        "dnhydroseq": [10, 20, 10, 999],
        "hf_id": [701, 702, 703, 704],
        "topo": ["fl-fl", "fl-fl", "fl-fl", "fl-fl"],
    })

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_ambiguous.network"] == 0
    assert metrics["hydroseq_order_indeterminate.network"] == 0
    assert metrics["dnhydroseq_mismatches.network"] == 1
    assert metrics["dnhydroseq_ambiguous.network"] == 0
    assert metrics["dnhydroseq_indeterminate.network"] == 0


def test_reference_network_unknown_topology_is_indeterminate(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1], "hydroseq": [10]})
    write_network(path, {
        "id": [4, 5, 6, 7, 8], "toid": [1, 1, 1, 1, 0],
        "hydroseq": [5, 5, 5, 20, 1], "dnhydroseq": [5, 5, 5, 10, 1],
        "topo": [None, "other", "", "fl-fl", "other"],
    })

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.network"] == 0
    assert metrics["hydroseq_order_indeterminate.network"] == 3
    assert metrics["dnhydroseq_mismatches.network"] == 0
    assert metrics["dnhydroseq_indeterminate.network"] == 3


def test_reference_network_reports_ambiguous_targets_and_indeterminate_values(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {
        "id": [1, 2, 2, 3, 4, 5], "hydroseq": [50, 20, 20, None, 10, 5],
    })
    write_network(path, {
        "id": [1, 1, 1, 1, 1, 1, None, 1, 1, 1, 1, 900, 1, 1],
        "toid": [2, 3, 4, 5, 999, None, 4, 0, 4, 4, 2, 4, 4, 4],
        "hydroseq": [50, 50, None, 50, 50, 50, 50, None, 10, 5, None, 5, 30, 30],
        "dnhydroseq": [20, 10, 10, None, 1, 1, 10, 999, 5, 10, None, 5, 10, 10],
        "topo": ["fl-fl"] * 14,
    })
    # The source of a network row need not be resolved in the flowpath table;
    # malformed values must not silently count as valid comparisons.
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE network SET hydroseq = 'bad' WHERE fid = 13")
        connection.execute("UPDATE network SET dnhydroseq = 'bad' WHERE fid = 14")

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.network"] == 3
    assert metrics["hydroseq_order_ambiguous.network"] == 2
    assert metrics["hydroseq_order_indeterminate.network"] == 6
    assert metrics["dnhydroseq_mismatches.network"] == 2
    assert metrics["dnhydroseq_ambiguous.network"] == 2
    assert metrics["dnhydroseq_indeterminate.network"] == 6


@pytest.mark.parametrize("missing", ["layer", "id", "toid", "topo"])
def test_missing_reference_network_prerequisites_only_skip_network_sequence_metrics(tmp_path, missing):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {
        "id": [1, 2], "toid": [2, 0], "hydroseq": [20, 10], "dnhydroseq": [10, 0],
    })
    if missing != "layer":
        data = {"id": [1], "toid": [2], "hydroseq": [20], "dnhydroseq": [10], "topo": ["fl-fl"]}
        del data[missing]
        write_network(path, data)

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.flowpaths"] == 0
    assert metrics["dnhydroseq_mismatches.flowpaths"] == 0
    assert not any(name.endswith(".network") and name.startswith(("hydroseq_order_", "dnhydroseq_")) for name in metrics)


@pytest.mark.parametrize("missing", ["id", "hydroseq"])
def test_reference_network_requires_downstream_flowpath_id_and_hydroseq(tmp_path, missing):
    path = tmp_path / "reference.gpkg"
    flowpaths = {"id": [1], "hydroseq": [10]}
    del flowpaths[missing]
    write_layer(path, "flowpaths", flowpaths)
    write_network(path, {
        "id": [2], "toid": [1], "hydroseq": [20], "dnhydroseq": [10], "topo": ["fl-fl"],
    })

    metrics = run_check(path, "reference")

    assert not any(name.endswith(".network") and name.startswith(("hydroseq_order_", "dnhydroseq_")) for name in metrics)


def test_reference_network_without_dnhydroseq_still_reports_order(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1], "hydroseq": [10]})
    write_network(path, {"id": [2], "toid": [1], "hydroseq": [5], "topo": ["fl-fl"]})

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_indeterminate.network"] == 0
    assert "dnhydroseq_mismatches.network" not in metrics


def test_reference_network_without_source_hydroseq_still_compares_dnhydroseq(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1, 3, 3], "hydroseq": [10, 7, 7]})
    write_network(path, {
        "id": [2, 2, 2, 2, 2], "toid": [1, 3, None, 1, 0],
        "dnhydroseq": [5, 7, 0, 10, 5], "topo": ["fl-fl", "fl-fl", "fl-fl", "other", "fl-fl"],
    })

    metrics = run_check(path, "reference")

    assert metrics["dnhydroseq_mismatches.network"] == 1
    assert metrics["dnhydroseq_ambiguous.network"] == 1
    assert metrics["dnhydroseq_indeterminate.network"] == 2
    assert "hydroseq_order_violations.network" not in metrics


def test_reference_network_without_sequence_fields_omits_sequence_metrics(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1], "hydroseq": [10]})
    write_network(path, {"id": [2], "toid": [1], "topo": ["fl-fl"]})

    metrics = run_check(path, "reference")

    assert not any(name.endswith(".network") and name.startswith(("hydroseq_order_", "dnhydroseq_")) for name in metrics)


def test_nextgen_network_orders_against_actual_downstream_network_sequence(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-1", "wb-2"], "hydroseq": [100, 50]})
    write_layer(path, "nexus", {"id": ["nex-1", "tnx-2"], "toid": ["wb-2", "wb-0"]})
    write_network(path, {
        "id": ["wb-1", "nex-1", "wb-2", "wb-2", "tnx-2"],
        "toid": ["nex-1", "wb-2", "tnx-2", "tnx-2", "wb-0"],
        "hydroseq": [100, None, 200, 200, None],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_ambiguous.network"] == 0
    assert metrics["hydroseq_order_indeterminate.network"] == 0
    assert metrics["hydroseq_mismatches.network"] == 2


def test_nextgen_network_resolves_repeated_and_missing_downstream_sequences(tmp_path):
    path = tmp_path / "ngen.gpkg"
    sources = ["u-1", "u-2", "u-3", "u-4", "u-5", "u-6", "u-7"]
    destinations = ["d-same", "d-diff", "d-mixed", "d-invalid", "d-missing", "d-null", "d-other"]
    nexus_ids = ["n-1", "n-2", "n-3", "n-4", "n-5", "n-6", "n-7"]
    write_layer(path, "flowpaths", {
        "id": sources + destinations, "hydroseq": [100] * 7 + [20] * 7,
    })
    write_layer(path, "nexus", {"id": nexus_ids + ["n-term"], "toid": destinations + ["wb-0"]})
    write_network(path, {
        "id": sources + nexus_ids + [
            "d-same", "d-same", "d-diff", "d-diff", "d-mixed", "d-mixed",
            "d-invalid", "d-invalid", "d-null", "d-null", "d-other", "d-other", "n-term",
        ],
        "toid": nexus_ids + destinations + ["n-term"] * 12 + ["wb-0"],
        "hydroseq": [100] * 7 + [None] * 7 + [
            20, 20, 20, 200, 20, None, None, None, None, None, 200, 200, None,
        ],
    })
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE network SET hydroseq = 'bad' WHERE id = 'd-invalid' AND fid = 21")

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_ambiguous.network"] == 2
    assert metrics["hydroseq_order_indeterminate.network"] == 3
    assert metrics["hydroseq_mismatches.network"] == 3
    assert metrics["hydroseq_comparison_indeterminate.network"] == 5
    assert metrics["hydroseq_comparison_ambiguous.network"] == 0


@pytest.mark.parametrize("sequences,ambiguous,indeterminate", [
    ([10, None], 1, 0), ([None, 10], 1, 0),
    ([10, 20], 1, 0), ([20, 10], 1, 0), ([None, None], 0, 1),
])
def test_nextgen_network_downstream_sequence_resolution_is_order_independent(
    tmp_path, sequences, ambiguous, indeterminate,
):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["up", "down"], "hydroseq": [100, 10]})
    write_layer(path, "nexus", {"id": ["n-1", "n-end"]})
    write_network(path, {
        "id": ["up", "n-1", "down", "down", "n-end"],
        "toid": ["n-1", "down", "n-end", "n-end", "wb-0"],
        "hydroseq": [100, None, *sequences, None],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 0
    assert metrics["hydroseq_order_ambiguous.network"] == ambiguous
    assert metrics["hydroseq_order_indeterminate.network"] == indeterminate


def test_nextgen_network_orders_its_own_edge_when_nexus_layer_disagrees(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["wb-1", "wb-2", "wb-3"], "hydroseq": [20, 50, 10],
    })
    write_layer(path, "nexus", {"id": ["nex-1"], "toid": ["wb-3"]})
    write_network(path, {
        "id": ["wb-1", "nex-1", "wb-2"],
        "toid": ["nex-1", "wb-2", "missing"],
        "hydroseq": [20, None, 50],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_indeterminate.network"] == 1
    assert metrics["hydroseq_order_ambiguous.network"] == 0


def test_nextgen_network_reports_each_sequence_disagreement_with_flowpaths(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["wb-1", "wb-2"], "hydroseq": [20, 10]})
    write_layer(path, "nexus", {"id": ["nex-1", "tnx-1"], "toid": ["wb-2", "wb-0"]})
    write_network(path, {
        "id": ["wb-1", "nex-1", "wb-2", "wb-2", "wb-2", "tnx-1"],
        "toid": ["nex-1", "wb-2", "tnx-1", "tnx-1", "tnx-1", "wb-0"],
        "hydroseq": [20, None, 10, 50, 50, None],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 0
    assert metrics["hydroseq_mismatches.network"] == 2
    assert metrics["hydroseq_comparison_indeterminate.network"] == 0
    assert metrics["hydroseq_comparison_ambiguous.network"] == 0


def test_nextgen_network_preserves_nexus_destinations_and_reports_missing_outlets(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["u-1", "u-2", "u-3", "u-4", "u-5", "u-6", "u-7", "u-8", "d-1", "d-2"],
        "hydroseq": [20, 20, 20, 20, 20, 20, 20, 20, 10, 30],
    })
    write_layer(path, "nexus", {
        "id": ["n-same", "n-conflict", "n-mixed", "inx-missing", "cnx-missing", "n-term", "n-null", "n-other"],
        "toid": ["d-1", "d-1", "d-1", "wb-0", "wb-0", "wb-0", "d-1", "d-1"],
    })
    write_network(path, {
        "id": [
            "u-1", "u-2", "u-3", "u-4", "u-5", "u-6", "u-7", "u-8",
            "n-same", "n-same", "n-conflict", "n-conflict", "n-mixed", "n-mixed",
            "n-term", "n-term", "n-null", "n-other", "d-1",
        ],
        "toid": [
            "n-same", "n-conflict", "n-mixed", "inx-missing", "cnx-missing", "n-term", "n-null", "n-other",
            "d-1", "d-1", "d-1", "d-2", "d-1", None, "wb-0", "wb-0", None, "absent", "n-term",
        ],
        "hydroseq": [20] * 8 + [None] * 10 + [10],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 0
    assert metrics["hydroseq_order_ambiguous.network"] == 2
    assert metrics["hydroseq_order_indeterminate.network"] == 4
    assert metrics["hydroseq_mismatches.network"] == 0


def test_nextgen_network_orders_flowpath_rows_through_nexus(tmp_path):
    path = tmp_path / "ngen.gpkg"
    # Network has multiple rows per flowpath; type labels the downstream nexus,
    # not necessarily the source. Nexus rows have no flowpath hydrosequence.
    write_layer(path, "flowpaths", {
        "id": ["wb-A", "wb-B", "wb-C"], "hydroseq": [30, 20, 10],
    })
    write_layer(path, "nexus", {
        "id": ["nex-1", "nex-2", "tnx-1", "inx-1"],
        "toid": ["wb-B", "wb-C", "wb-0", "wb-0"],
    })
    write_network(path, {
        "id": ["wb-A", "wb-A", "wb-B", "wb-C", "nex-1", "nex-2", "tnx-1", "inx-1"],
        "toid": ["nex-1", "nex-1", "nex-2", "tnx-1", "wb-B", "wb-C", "wb-0", "wb-0"],
        "hydroseq": [30, 5, 5, 10, None, None, None, None],
        "type": ["nexus", "nexus", "nexus", "terminal", "nexus", "nexus", "terminal", "internal"],
        "topo": ["fl-nex"] * 8,
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 2
    assert metrics["hydroseq_order_indeterminate.network"] == 0
    assert metrics["hydroseq_order_ambiguous.network"] == 0
    assert not any(name.startswith("dnhydroseq_") for name in metrics)


def test_nextgen_network_reports_uncertain_source_and_target_classification(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["up", "dup", "dup", "end", "dup-src", "dup-src", "both", "no-seq", "target-both"],
        "hydroseq": [50, 20, 20, 10, 50, 50, 50, None, 5],
    })
    write_layer(path, "nexus", {
        "id": [
            "n-good", "n-dup", "n-dup", "n-term", "n-noval", "both", "n-to-dup",
            "n-to-both", "target-both", "n-to-noseq", "n-same", "n-same",
        ],
        "toid": ["end", "end", "wb-0", "wb-0", None, "end", "dup", "target-both", "end", "no-seq", "end", "end"],
    })
    write_network(path, {
        "id": [
            "up", "up", "up", "up", "dup-src", "both", "unknown", None, "up", "up", "up",
            "up", "up", "up", "up", "up", "n-good", "n-dup", "target-both", "unknown", "up", "up",
            "n-dup", "n-to-dup", "n-to-both", "n-to-noseq", "n-term", "n-noval", "n-same", "n-same", "end",
        ],
        "toid": [
            "n-good", "n-good", "n-dup", "n-to-dup", "n-good", "n-good", "n-good", "n-good",
            "absent", None, "n-noval", "n-good", "n-good", "n-to-both", "both", "n-term",
            "end", "end", "end", "n-term", "n-to-noseq", "n-same",
            "wb-0", "dup", "target-both", "no-seq", "wb-0", None, "end", "end", "n-term",
        ],
        "hydroseq": [
            50, 5, 50, 50, 50, 50, 50, 50, 50, 50, 50, None, 50, 50, 50, None, None, 20, 50, 50, 50, 50,
            None, None, None, None, None, None, None, None, 10,
        ],
    })
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE network SET hydroseq = 'bad' WHERE fid = 13")

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_ambiguous.network"] == 7
    assert metrics["hydroseq_order_indeterminate.network"] == 9
    assert metrics["hydroseq_mismatches.network"] == 1
    assert metrics["hydroseq_comparison_ambiguous.network"] == 3
    assert metrics["hydroseq_comparison_indeterminate.network"] == 6


def test_nextgen_network_does_not_use_reference_dnhydroseq_or_topo_rules(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1", "f-2"], "hydroseq": [10, 5]})
    write_layer(path, "nexus", {"id": ["n-1", "n-end"], "toid": ["f-1", "wb-0"]})
    write_network(path, {
        "id": ["f-2", "n-1", "f-1", "n-end"],
        "toid": ["n-1", "f-1", "n-end", "wb-0"], "hydroseq": [5, None, 10, None],
        "dnhydroseq": [1, None, None, None], "topo": ["fl-fl"] * 4,
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert not any(name.startswith("dnhydroseq_") for name in metrics)


@pytest.mark.parametrize("missing", ["layer", "id", "toid", "hydroseq"])
def test_missing_nextgen_network_fields_do_not_disable_flowpath_checks(tmp_path, missing):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1", "f-2"], "toid": ["n-1", "n-2"], "hydroseq": [20, 10]})
    write_layer(path, "nexus", {"id": ["n-1", "n-2"], "toid": ["f-2", "wb-0"]})
    if missing != "layer":
        data = {"id": ["f-1"], "toid": ["n-1"], "hydroseq": [20]}
        del data[missing]
        write_network(path, data)

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.flowpaths"] == 0
    assert not any(name.startswith("hydroseq_order_") and name.endswith(".network") for name in metrics)


@pytest.mark.parametrize("missing", ["layer", "id"])
def test_nextgen_network_requires_nexus_identifiers(tmp_path, missing):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1", "f-2"], "hydroseq": [20, 10]})
    write_network(path, {"id": ["f-1"], "toid": ["n-1"], "hydroseq": [20]})
    if missing != "layer":
        data = {"id": ["n-1"], "toid": ["f-2"]}
        del data[missing]
        write_layer(path, "nexus", data)

    metrics = run_check(path, "ngen")

    assert not any(name.startswith("hydroseq_order_") and name.endswith(".network") for name in metrics)


def test_nextgen_network_order_does_not_require_nexus_toid(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1", "f-2"], "hydroseq": [5, 10]})
    write_layer(path, "nexus", {"id": ["n-1", "n-end"]})
    write_network(path, {
        "id": ["f-1", "n-1", "f-2", "n-end"],
        "toid": ["n-1", "f-2", "n-end", "wb-0"], "hydroseq": [5, None, 10, None],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_indeterminate.network"] == 0
    assert metrics["hydroseq_mismatches.network"] == 0


def test_nextgen_network_sequence_comparison_does_not_require_routing_fields(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1"], "hydroseq": [10]})
    write_layer(path, "nexus", {"id": ["n-1"]})
    write_network(path, {"id": ["f-1"], "hydroseq": [20]})

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_mismatches.network"] == 1
    assert metrics["hydroseq_comparison_indeterminate.network"] == 0
    assert "hydroseq_order_violations.network" not in metrics


def test_nextgen_network_order_does_not_require_flowpath_layer_hydroseq(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1", "f-2"]})
    write_layer(path, "nexus", {"id": ["n-1", "n-end"]})
    write_network(path, {
        "id": ["f-1", "n-1", "f-2", "n-end"],
        "toid": ["n-1", "f-2", "n-end", "wb-0"], "hydroseq": [5, None, 10, None],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.network"] == 1
    assert metrics["hydroseq_order_indeterminate.network"] == 0
    assert "hydroseq_mismatches.network" not in metrics


def test_nextgen_network_requires_flowpath_identifiers(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"hydroseq": [20]})
    write_layer(path, "nexus", {"id": ["n-1"], "toid": ["f-1"]})
    write_network(path, {"id": ["f-1"], "toid": ["n-1"], "hydroseq": [20]})

    metrics = run_check(path, "ngen")

    assert not any(name.startswith("hydroseq_order_") and name.endswith(".network") for name in metrics)


def test_nextgen_orders_edges_through_nexus_and_excludes_terminals(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["f-1", "f-2", "f-3", "f-4", "f-5"],
        "toid": ["n-1", "n-2", "n-3", "n-4", "n-5"],
        "hydroseq": [30, 20, 20, 100, 10],
    })
    write_layer(path, "nexus", {
        "id": ["n-1", "n-2", "n-3", "n-4", "n-5"],
        "toid": ["f-2", "f-3", "wb-0", "f-2", "f-2"],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.flowpaths"] == 2
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 0
    assert metrics["hydroseq_order_ambiguous.flowpaths"] == 0
    assert not any(name.startswith("dnhydroseq_") for name in metrics)


def test_reference_distinguishes_ambiguous_and_indeterminate_edges(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {
        "id": [1, 2, 2, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13, 13, None],
        "toid": [2, 0, 0, 4, 4, 999, None, 8, 0, 2, 4, 4, 4, 4, 4],
        "hydroseq": [50, 20, 21, 50, 40, 30, 30, None, 10, 20, 5, 80, 90, 90, 90],
        "dnhydroseq": [20, 0, 0, 40, 0, 1, 1, 10, 0, 20, None, 40, 40, 40, 40],
    })

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.flowpaths"] == 2
    assert metrics["hydroseq_order_ambiguous.flowpaths"] == 4
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 4
    assert metrics["dnhydroseq_mismatches.flowpaths"] == 1
    assert metrics["dnhydroseq_ambiguous.flowpaths"] == 4
    assert metrics["dnhydroseq_indeterminate.flowpaths"] == 4


def test_nextgen_reports_missing_links_and_duplicate_ids_without_selecting_one(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["f-1", "f-2", "f-2", "f-3", "f-4", "f-5", "f-6", "f-7", "f-8", None, "f-10", "f-11", "f-12", "f-12", "f-13"],
        "toid": ["n-dup", "n-terminal", "n-terminal", "n-3", "n-4", "n-5", "n-6", "n-7", "n-8", "n-8", "n-10", "n-11", "n-10", "n-10", "n-identical"],
        "hydroseq": [100, 50, 51, 60, 55, 50, 45, 40, None, 30, 20, 10, 90, 90, 100],
    })
    write_layer(path, "nexus", {
        "id": ["n-dup", "n-dup", "n-terminal", "n-3", "n-4", "n-5", "n-7", "n-8", "n-10", "n-11", "n-identical", "n-identical"],
        "toid": ["f-3", "wb-0", "wb-0", "f-2", "f-404", None, "f-8", "f-3", "f-11", "wb-0", "f-3", "f-3"],
    })

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.flowpaths"] == 0
    assert metrics["hydroseq_order_ambiguous.flowpaths"] == 5
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 6


def test_reference_invalid_sequences_are_not_treated_as_matches_or_ordered(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {
        "id": [1, 2, 3, 4, 5, 6],
        "toid": [2, 3, 4, 5, 0, 5],
        "hydroseq": [50, 40, 30, 20, 10, 5],
        "dnhydroseq": [40, 30, 20, 10, 0, 10],
    })
    # SQLite permits malformed values even in a numerically declared column.
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE flowpaths SET hydroseq = 'bad' WHERE id = 2")
        connection.execute("UPDATE flowpaths SET dnhydroseq = 'bad' WHERE id = 3")
        connection.execute("UPDATE flowpaths SET dnhydroseq = NULL WHERE id = 4")
        connection.execute("UPDATE flowpaths SET hydroseq = NULL WHERE id = 6")

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.flowpaths"] == 0
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 3
    assert metrics["dnhydroseq_mismatches.flowpaths"] == 0
    assert metrics["dnhydroseq_indeterminate.flowpaths"] == 3


def test_nextgen_missing_and_nonfinite_sequences_are_indeterminate(tmp_path):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {
        "id": ["f-1", "f-2", "f-3", "f-4", "f-5"],
        "toid": ["n-1", "n-2", "n-3", None, "n-5"],
        "hydroseq": [40, 30, 20, 10, 5],
    })
    write_layer(path, "nexus", {
        "id": ["n-1", "n-2", "n-3", "n-5"],
        "toid": ["f-2", "f-3", "f-5", "wb-0"],
    })
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE flowpaths SET hydroseq = ? WHERE id = 'f-2'", (float("inf"),))
        connection.execute("UPDATE flowpaths SET hydroseq = 'bad' WHERE id = 'f-3'")

    metrics = run_check(path, "ngen")

    assert metrics["hydroseq_order_violations.flowpaths"] == 0
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 4
    assert metrics["hydroseq_order_ambiguous.flowpaths"] == 0


@pytest.mark.parametrize("kind,missing", [
    ("reference", "id"), ("reference", "toid"), ("reference", "hydroseq"),
    ("ngen", "id"), ("ngen", "toid"), ("ngen", "hydroseq"),
])
def test_missing_flowpath_prerequisite_omits_dependent_metrics(tmp_path, kind, missing):
    path = tmp_path / "build.gpkg"
    data = {"id": [1], "toid": [0], "hydroseq": [20], "dnhydroseq": [0]}
    del data[missing]
    write_layer(path, "flowpaths", data)
    if kind == "ngen":
        write_layer(path, "nexus", {"id": ["n-1"], "toid": ["wb-0"]})

    metrics = run_check(path, kind)

    assert not any(name.startswith(("hydroseq_order_", "dnhydroseq_")) for name in metrics)


@pytest.mark.parametrize("missing", ["layer", "id", "toid"])
def test_missing_nexus_prerequisite_omits_nextgen_metrics(tmp_path, missing):
    path = tmp_path / "ngen.gpkg"
    write_layer(path, "flowpaths", {"id": ["f-1"], "toid": ["n-1"], "hydroseq": [20]})
    if missing != "layer":
        data = {"id": ["n-1"], "toid": ["wb-0"]}
        del data[missing]
        write_layer(path, "nexus", data)

    metrics = run_check(path, "ngen")

    assert not any(name.startswith("hydroseq_order_") for name in metrics)


def test_reference_without_dnhydroseq_still_reports_order(tmp_path):
    path = tmp_path / "reference.gpkg"
    write_layer(path, "flowpaths", {"id": [1, 2], "toid": [2, 0], "hydroseq": [5, 10]})

    metrics = run_check(path, "reference")

    assert metrics["hydroseq_order_violations.flowpaths"] == 1
    assert metrics["hydroseq_order_indeterminate.flowpaths"] == 0
    assert not any(name.startswith("dnhydroseq_") for name in metrics)
