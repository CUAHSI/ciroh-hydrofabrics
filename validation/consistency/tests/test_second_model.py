"""A second, compatible Data Model runs end to end without any code change.

The model ``v9.9`` is derived from v2.2 but uses different conventions: another
CRS, terminal ID, outlet naming, link label and numeric thresholds. Adding its
specification directory is all that is needed to check both output kinds.
"""

import copy
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import LineString, Point, box

CONSISTENCY = Path(__file__).resolve().parents[1]
RUNNER = CONSISTENCY / "consistency_check.py"
sys.path.insert(0, str(CONSISTENCY))

import data_model

CRS = "EPSG:3857"


def v22_spec(kind):
    return json.loads((CONSISTENCY / "models" / "v2.2" / f"{kind}.json").read_text())


def derive(kind, output_kind=None):
    """A v9.9 specification: v2.2 structure with different conventions."""
    spec = copy.deepcopy(v22_spec(kind))
    spec["data_model_version"] = "v9.9"
    spec["output_kind"] = output_kind or kind
    for table in spec["tables"].values():
        if table["geometry"]:
            table["geometry"]["srs_id"] = 3857
            table["geometry"]["crs"] = {"name": "WGS 84 / Pseudo-Mercator", "authority": "EPSG", "code": 3857}
            table["gpkg_contents"]["srs_id"] = 3857
    checks = spec["checks"]
    checks["geometry"].update(overlap_min_area_m2=1, gap_min_area_m2=1)
    routing = checks["network"]["routing"]
    if routing["style"] == "direct":
        routing.update(terminal_id=-1, link_label="dn")
    else:
        routing.update(terminal_id="end-0", outlet_types={"out-": "terminal"}, nexus_id_prefixes=["nx-"])
    return spec


def install(root, spec):
    directory = root / "v9.9"
    directory.mkdir(exist_ok=True)
    (directory / f"{spec['output_kind']}.json").write_text(json.dumps(spec))


@pytest.fixture
def models(monkeypatch, tmp_path):
    root = tmp_path / "models"
    # Start from the checked-in v2.2 model; tests add further models beside it.
    shutil.copytree(CONSISTENCY / "models" / "v2.2", root / "v2.2")
    monkeypatch.setattr(data_model, "MODELS", root)
    return root


@pytest.fixture
def cli(monkeypatch, tmp_path, capsys):
    """Run the CLI in-process, with recorded counts isolated from the repo."""
    monkeypatch.syspath_prepend(str(CONSISTENCY))
    module_spec = importlib.util.spec_from_file_location("consistency_check", RUNNER)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    counts = tmp_path / "counts.yaml"
    counts.write_text("{}\n")

    def run(*args):
        status = module.main([*map(str, args), "--counts", str(counts)])
        captured = capsys.readouterr()
        return status, captured.out, captured.err

    return run


def spatial(path, layer, data, geometry):
    gpd.GeoDataFrame(data, geometry=geometry, crs=CRS).to_file(path, layer=layer, engine="pyogrio")


def tabular(path, layer, data):
    pyogrio.write_dataframe(pd.DataFrame(data), path, layer=layer, geometry_type=None)


def write_reference(path):
    """Reference-style build whose outlets use the sentinel -1 and label ``dn``."""
    spatial(path, "divides", {"divide_id": [1.0, 2.0], "id": [1.0, 2.0], "vpuid": ["01", "01"]},
            [box(0, 0, 10, 10), box(5, 0, 15, 10)])
    spatial(path, "flowpaths", {
        "id": [1.0, 2.0], "toid": [2.0, -1.0], "hydroseq": [20.0, 10.0], "vpuid": ["01", "01"],
    }, [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])])
    tabular(path, "network", {
        "id": [1.0, 2.0], "toid": [2.0, -1.0], "topo": ["dn", "dn"], "hydroseq": [20.0, 10.0],
    })


def write_nextgen(path):
    """NextGen-style build whose outlet nexus is ``out-2`` routing to ``end-0``."""
    spatial(path, "flowpaths", {"id": ["wb-1", "wb-2"], "toid": ["nx-1", "out-2"], "vpuid": ["01", "01"]},
            [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])])
    spatial(path, "nexus", {
        "id": ["nx-1", "out-2"], "toid": ["wb-2", "end-0"], "type": ["nexus", "terminal"], "vpuid": ["01", "01"],
    }, [Point(1, 1), Point(2, 2)])


def line(report, check, metric):
    matches = [row for row in report.splitlines() if row.startswith(f"{check} | {metric} | ")]
    assert len(matches) == 1, (metric, report)
    return matches[0]


def test_reference_run_uses_the_second_models_conventions(models, cli, tmp_path):
    install(models, derive("reference"))
    path = tmp_path / "build.gpkg"
    write_reference(path)

    status, out, err = cli(path, "--data-model", "v9.9", "--type", "reference", "--vpu", "01")

    assert status == 0, err
    assert " | v9.9 | reference | 01" in out
    # The model's terminal ID, link label, CRS and overlap threshold apply.
    assert line(out, "network", "dangling_toid.flowpaths").endswith("| 0 | 0 | PASS | advisory")
    assert line(out, "network", "cycle_nodes.flowpaths").endswith("| 0 | 0 | PASS | advisory")
    assert line(out, "network", "hydroseq_order_indeterminate.network").endswith("| 0 | 0 | PASS | advisory")
    assert line(out, "geometry", "overlap_min_area_m2").endswith("| 1.0 | - | INFO | advisory")
    assert line(out, "geometry", "divide_overlaps.count").endswith("| 1 | 0 | FAIL | advisory")
    assert line(out, "schema", "geometry_crs.divides").endswith("| 0 | 0 | PASS | advisory")


def test_the_same_build_is_judged_by_the_selected_model(models, cli, tmp_path):
    install(models, derive("reference"))
    path = tmp_path / "build.gpkg"
    write_reference(path)

    status, out, err = cli(path, "--data-model", "v2.2", "--type", "reference", "--vpu", "01")

    # v2.2 treats -1 as a dangling link, ``dn`` as an unsupported label, and
    # the EPSG:3857 divides as outside its registered CRS.
    assert status == 2
    assert line(out, "network", "dangling_toid.flowpaths").endswith("| 1 | 0 | FAIL | advisory")
    assert line(out, "network", "hydroseq_order_indeterminate.network").endswith("| 2 | 0 | FAIL | advisory")
    assert "requires the registered v2.2 EPSG:5070 CRS" in err


def test_nextgen_run_uses_the_second_models_outlet_convention(models, cli, tmp_path):
    install(models, derive("ngen"))
    path = tmp_path / "build.gpkg"
    write_nextgen(path)

    status, out, err = cli(path, "--data-model", "v9.9", "--type", "ngen", "--vpu", "01")

    assert status == 0, err
    assert line(out, "network", "dangling_toid.nexus").endswith("| 0 | 0 | PASS | advisory")
    assert line(out, "network", "terminal_convention.nexus").endswith("| 0 | 0 | PASS | advisory")
    assert line(out, "network", "cycle_nodes.flowpaths_nexus").endswith("| 0 | 0 | PASS | advisory")


def test_nextgen_build_is_judged_by_v22_conventions_under_v22(models, cli, tmp_path):
    path = tmp_path / "build.gpkg"
    write_nextgen(path)

    status, out, err = cli(path, "--data-model", "v2.2", "--type", "ngen", "--vpu", "01")

    assert status == 0, err
    assert line(out, "network", "dangling_toid.nexus").endswith("| 1 | 0 | FAIL | advisory")
    assert line(out, "network", "terminal_convention.nexus").endswith("| 1 | 0 | FAIL | advisory")


def test_a_model_may_name_its_own_output_kind(models, cli, tmp_path):
    install(models, derive("ngen", output_kind="nextgen"))
    path = tmp_path / "build.gpkg"
    write_nextgen(path)

    status, out, err = cli(path, "--data-model", "v9.9", "--type", "nextgen", "--vpu", "01")

    assert status == 0, err
    assert " | v9.9 | nextgen | 01" in out


def test_a_directory_run_derives_filenames_from_the_models_kinds(models, cli, tmp_path):
    install(models, derive("reference"))
    install(models, derive("ngen", output_kind="nextgen"))
    builds = tmp_path / "builds"
    builds.mkdir()
    write_reference(builds / "reference-hydrofabric-vpu-01.gpkg")
    write_nextgen(builds / "nextgen-hydrofabric-vpu-01.gpkg")
    write_nextgen(builds / "ngen-hydrofabric-vpu-01.gpkg")

    status, out, err = cli(builds, "--data-model", "v9.9")

    assert " | v9.9 | reference | 01" in out
    assert " | v9.9 | nextgen | 01" in out
    # ``ngen`` is not a kind of this model, so that file is reported, not checked.
    assert "unrecognized GeoPackage filename" in err
    assert status == 2


def test_a_kind_the_model_does_not_specify_is_rejected(models, cli, tmp_path):
    install(models, derive("reference"))
    path = tmp_path / "build.gpkg"
    write_nextgen(path)

    status, out, err = cli(path, "--data-model", "v9.9", "--type", "ngen", "--vpu", "01")

    assert status == 2
    assert "unsupported output kind 'ngen' for Data Model 'v9.9'; available: reference" in err
    assert out == ""


def test_an_unsupported_semantic_stops_the_run_before_any_file_is_read(models, cli, tmp_path):
    spec = derive("reference")
    spec["checks"]["network"]["routing"]["style"] = "mesh"
    install(models, spec)

    status, out, err = cli(tmp_path / "does-not-exist.gpkg", "--data-model", "v9.9", "--type", "reference", "--vpu", "01")

    assert status == 2
    assert "output kind 'reference'" in err and "unsupported routing style 'mesh'" in err
    assert out == ""


def test_a_model_without_check_semantics_does_not_fall_back_to_v22(models, cli, tmp_path):
    spec = derive("reference")
    del spec["checks"]
    install(models, spec)

    status, out, err = cli(tmp_path / "does-not-exist.gpkg", "--data-model", "v9.9", "--type", "reference", "--vpu", "01")

    assert status == 2
    assert "no checks section" in err
    assert out == ""


def test_a_missing_model_lists_the_available_models(models, cli, tmp_path):
    install(models, derive("reference"))

    status, out, err = cli(tmp_path / "build.gpkg", "--data-model", "v1.0", "--type", "reference", "--vpu", "01")

    assert status == 2
    assert "no Data Model 'v1.0'; available: v2.2, v9.9" in err
    assert out == ""
