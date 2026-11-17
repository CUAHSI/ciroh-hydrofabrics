"""The Data Model spec extractor regenerates observations and keeps reviewed rules.

Every test runs the command line (``main``) on small GeoPackages built in a
temporary directory, against a model directory that is also temporary, so the
checked-in specifications are never read or written.
"""

import copy
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import pytest
from shapely.geometry import LineString

CONSISTENCY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSISTENCY))

import data_model
import extract_data_model
from golden_fixtures import write_ngen, write_reference

# Sections a reviewer owns: the extractor must carry them over untouched.
REVIEWED = ("format_version", "data_model_version", "structure_basis", "identifier_basis",
            "output_kind", "checks", "attribute_constraints")


def base_reference_spec():
    """A reviewed specification, stale in every section the extractor regenerates."""
    return {
        "format_version": "1.0",
        "data_model_version": "v9.9",
        "structure_basis": "Reviewed wording about the structure.",
        "identifier_basis": "Reviewed wording about the identifiers.",
        "output_kind": "reference",
        "sources": [{"vpu": "99", "filename": "stale.gpkg", "local_path": "stale.gpkg", "sha256": "0" * 64}],
        "tables": {"stale": {"gpkg_contents": {"data_type": "attributes", "srs_id": 0},
                             "geometry": None, "columns": [{"name": "gone", "type": "TEXT"}]}},
        "identifiers": [],
        "checks": {
            "schema": {"id_prefix_separator": "-"},
            "network": {
                "primary_ids": {"flowpaths": "id"},
                "relationships": [],
                "reciprocal_links": None,
                "routing": {"style": "direct", "terminal_id": 0, "layers": ["flowpaths", "network"],
                            "link_label": "fl-fl"},
            },
            "geometry": {"topology_layer": "divides", "overlap_min_area_m2": 100, "gap_min_area_m2": 100},
        },
        "terminal_observations": [],
        "attribute_constraints": {
            "numeric_value_policy": {
                "scope": "numeric operand columns of these rules, independent of row applicability",
                "sqlite_storage_classes": ["integer", "real"], "require_finite": True,
                "invalid_or_nonfinite": "report", "nonfinite_intermediate": "report",
                "null": "undetermined", "null_reporting": "report_indeterminate",
            },
            "sentinel_handling": {
                "scope": "all numeric-declared Data Model columns, independent of row applicability",
                "unrecognized_candidate": "report", "field_defined_missing": "apply_null_policy",
                "otherwise_apply_numeric_rules_when_applicable": True,
            },
            "rules": [{
                "id": "divides.areasqkm_positive", "kind": "range", "source": "reviewed by a scientist",
                "table": "divides", "column": "areasqkm", "operator": "gt", "value": 0,
                "applies_when": {"kind": "all_rows"}, "null_policy": "undetermined",
                "sentinel_policy": "report_unless_field_defined_missing",
            }],
            "sentinels": [],
            "unlisted_constraints": "undetermined",
        },
    }


def base_ngen_spec():
    """The same reviewed content for the NextGen output kind: routing goes through nexus points."""
    spec = base_reference_spec()
    spec["output_kind"] = "ngen"
    spec["checks"]["network"] = {
        "primary_ids": {"flowpaths": "id"},
        "relationships": [],
        "reciprocal_links": None,
        "routing": {"style": "via_nexus", "terminal_id": "wb-0", "target_layers": ["flowpaths"],
                    "outlet_types": {"tnx-": "terminal", "inx-": "internal"}, "nexus_id_prefixes": ["nex-"]},
    }
    return spec


@pytest.fixture
def models(monkeypatch, tmp_path):
    """An isolated models directory holding the reviewed ``v9.9`` reference specification."""
    root = tmp_path / "models"
    (root / "v9.9").mkdir(parents=True)
    monkeypatch.setattr(data_model, "MODELS", root)
    return root


def install(models, spec, kind="reference"):
    path = models / "v9.9" / f"{kind}.json"
    path.write_text(json.dumps(spec, indent=2) + "\n")
    return path


def ngen_gpkg(tmp_path, vpu="01"):
    path = tmp_path / "data" / f"ngen-hydrofabric-vpu-{vpu}.gpkg"
    path.parent.mkdir(exist_ok=True)
    write_ngen(path)
    return path


def reference_gpkg(tmp_path, vpu="01"):
    path = tmp_path / "data" / f"reference-hydrofabric-vpu-{vpu}.gpkg"
    path.parent.mkdir(exist_ok=True)
    write_reference(path)
    return path


def edit_gpkg(path, *statements):
    """Change the fixture's data so one case is present in it."""
    with sqlite3.connect(path) as connection:
        for statement in statements:
            connection.execute(statement)
    connection.close()


def extract(*arguments):
    return extract_data_model.main([str(argument) for argument in arguments])


def test_candidate_regenerates_structure_and_sources_and_keeps_reviewed_sections(models, tmp_path):
    base = base_reference_spec()
    checked_in = install(models, base)
    checked_in_text = checked_in.read_text()
    gpkg = reference_gpkg(tmp_path)
    candidate_path = tmp_path / "candidate.json"

    status = extract(gpkg, "--data-model", "v9.9", "--type", "reference", "--output", candidate_path)

    candidate = json.loads(candidate_path.read_text())
    assert status == 0
    # Structure comes from the GeoPackage, not from the stale base.
    assert list(candidate["tables"]) == ["divides", "flowpaths", "network"]
    assert candidate["tables"]["network"] == {
        "gpkg_contents": {"data_type": "attributes", "srs_id": 0},
        "geometry": None,
        "columns": [{"name": "fid", "type": "INTEGER"}, {"name": "id", "type": "REAL"},
                    {"name": "toid", "type": "REAL"}, {"name": "topo", "type": "TEXT"},
                    {"name": "hydroseq", "type": "REAL"}, {"name": "dnhydroseq", "type": "REAL"}],
    }
    assert candidate["tables"]["divides"]["geometry"] == {
        "column": "geom", "type": "POLYGON", "srs_id": 5070,
        "crs": {"name": "NAD83 / Conus Albers", "authority": "EPSG", "code": 5070}, "z": 0, "m": 0,
    }
    # The source records the file's identity, with its digest taken independently.
    assert candidate["sources"] == [{
        "vpu": "01", "filename": gpkg.name, "local_path": str(gpkg),
        "sha256": hashlib.sha256(gpkg.read_bytes()).hexdigest(),
    }]
    # Reviewed sections are carried over untouched, and the checked-in file is not.
    for section in REVIEWED:
        assert candidate[section] == base[section]
    assert checked_in.read_text() == checked_in_text
    # The checks can use the candidate as it is.
    data_model.validate_spec(copy.deepcopy(candidate))


def with_identifiers(models, *columns):
    """Install the base specification with a reviewed choice of identifier columns, stale observations included."""
    base = base_reference_spec()
    base["identifiers"] = [
        {"table": table, "column": column, "observations": {"99": {"storage_class_counts": {"real": 1},
                                                                    "fractional_numeric_count": 0}}}
        for table, column in columns
    ]
    install(models, base)
    return base


def test_numeric_identifiers_are_observed_by_storage_class_over_the_whole_column(models, tmp_path):
    with_identifiers(models, ("network", "id"), ("network", "toid"), ("network", "dnhydroseq"))
    gpkg = reference_gpkg(tmp_path)
    edit_gpkg(gpkg,
              "UPDATE network SET dnhydroseq = NULL WHERE id = 1.0",
              "UPDATE network SET toid = 1.5 WHERE id = 1.0",
              "UPDATE network SET toid = 'abc' WHERE id = 2.0")
    candidate_path = tmp_path / "candidate.json"

    status = extract(gpkg, "--data-model", "v9.9", "--type", "reference", "--output", candidate_path)

    identifiers = {(i["table"], i["column"]): i["observations"]
                   for i in json.loads(candidate_path.read_text())["identifiers"]}
    assert status == 0
    # The reviewed column list is kept; the stale observation for another VPU is replaced.
    assert identifiers[("network", "id")] == {
        "01": {"storage_class_counts": {"real": 2}, "fractional_numeric_count": 0}}
    assert identifiers[("network", "toid")] == {
        "01": {"storage_class_counts": {"real": 1, "text": 1}, "fractional_numeric_count": 1}}
    assert identifiers[("network", "dnhydroseq")] == {
        "01": {"storage_class_counts": {"null": 1, "real": 1}, "fractional_numeric_count": 0}}


def test_text_identifiers_are_observed_by_prefix_over_the_whole_column(models, tmp_path):
    base = base_ngen_spec()
    base["identifiers"] = [{"table": table, "column": column, "observations": {}}
                           for table, column in (("divides", "divide_id"), ("network", "id"),
                                                 ("network", "divide_id"))]
    install(models, base, "ngen")
    gpkg = ngen_gpkg(tmp_path)
    # One ID has no prefix at all and one starts with the separator, so neither has a prefix.
    edit_gpkg(gpkg,
              "UPDATE network SET id = 'plain' WHERE id = 'wb-1'",
              "UPDATE network SET id = '-x' WHERE id = 'nex-1'")
    candidate_path = tmp_path / "candidate.json"

    status = extract(gpkg, "--data-model", "v9.9", "--type", "ngen", "--output", candidate_path)

    identifiers = {(i["table"], i["column"]): i for i in json.loads(candidate_path.read_text())["identifiers"]}
    assert status == 0
    assert identifiers[("divides", "divide_id")]["observations"] == {
        "01": {"row_count": 2, "null_count": 0, "unprefixed_count": 0, "prefix_counts": {"cat": 2}}}
    assert identifiers[("network", "id")]["observations"] == {
        "01": {"row_count": 3, "null_count": 0, "unprefixed_count": 2, "prefix_counts": {"wb": 1}}}
    assert identifiers[("network", "divide_id")]["observations"] == {
        "01": {"row_count": 3, "null_count": 1, "unprefixed_count": 0, "prefix_counts": {"cat": 2}}}
    # The observed vocabulary is a summary of what was seen, in sorted order.
    assert identifiers[("divides", "divide_id")]["observed_prefixes"] == ["cat"]
    assert identifiers[("network", "id")]["observed_prefixes"] == ["wb"]


def test_direct_routing_records_terminal_observations_per_layer_and_vpu(models, tmp_path):
    install(models, base_reference_spec())
    gpkg = reference_gpkg(tmp_path)
    # Rebuild the routed layers so every counted case is present: terminals, a null and a dangling link.
    lines = [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)]), LineString([(2, 2), (3, 3)])]
    gpd.GeoDataFrame(
        {"id": [1.0, 2.0, 3.0], "toid": [0.0, 0.0, 7.0], "dnhydroseq": [0.0, 4.0, 0.0]},
        geometry=lines, crs="EPSG:5070").to_file(gpkg, layer="flowpaths", engine="pyogrio")
    pyogrio.write_dataframe(
        pd.DataFrame({"id": [1.0, 2.0, 3.0], "toid": [9.0, 0.0, None], "dnhydroseq": [0.0, 0.0, 0.0]}),
        gpkg, layer="network", geometry_type=None)
    candidate_path = tmp_path / "candidate.json"

    status = extract(gpkg, "--data-model", "v9.9", "--type", "reference", "--output", candidate_path)

    assert status == 0
    assert json.loads(candidate_path.read_text())["terminal_observations"] == [
        {"table": "flowpaths", "vpu": "01", "row_count": 3, "toid_zero_count": 2, "toid_null_count": 0,
         "nonzero_toid_not_in_same_table_id_count": 1, "dnhydroseq_zero_count": 2,
         "both_toid_and_dnhydroseq_zero_count": 1},
        {"table": "network", "vpu": "01", "row_count": 3, "toid_zero_count": 1, "toid_null_count": 1,
         "nonzero_toid_not_in_same_table_id_count": 1},
    ]


def test_nexus_routing_groups_terminal_rows_by_id_prefix_and_type(models, tmp_path):
    install(models, base_ngen_spec(), "ngen")
    gpkg = ngen_gpkg(tmp_path)
    # Two more network rows reach the terminal, so the network layer has several (prefix, type) groups.
    edit_gpkg(gpkg,
              "UPDATE network SET toid = 'wb-0' WHERE id = 'wb-1'",
              "UPDATE network SET toid = 'wb-0' WHERE id = 'nex-1'")
    candidate_path = tmp_path / "candidate.json"

    status = extract(gpkg, "--data-model", "v9.9", "--type", "ngen", "--output", candidate_path)

    assert status == 0
    assert json.loads(candidate_path.read_text())["terminal_observations"] == [
        {"table": "nexus", "vpu": "01", "groups": [
            {"id_prefix": "nex", "type": "terminal", "toid": "wb-0", "count": 1}]},
        {"table": "network", "vpu": "01", "groups": [
            {"id_prefix": "nex", "type": "nexus", "toid": "wb-0", "count": 1},
            {"id_prefix": "wb", "type": "nexus", "toid": "wb-0", "count": 1},
            {"id_prefix": "wb", "type": "terminal", "toid": "wb-0", "count": 1}]},
    ]


def test_several_vpus_are_merged_in_vpu_order_with_per_vpu_observations(models, tmp_path):
    base = base_ngen_spec()
    base["identifiers"] = [{"table": "network", "column": "id", "observations": {}}]
    install(models, base, "ngen")
    first, second = ngen_gpkg(tmp_path, "01"), ngen_gpkg(tmp_path, "02")
    edit_gpkg(second, "UPDATE network SET id = 'zz-2' WHERE id = 'wb-2'")
    candidate_path = tmp_path / "candidate.json"

    # Supplied out of order on purpose.
    status = extract(second, first, "--data-model", "v9.9", "--type", "ngen", "--output", candidate_path)

    candidate = json.loads(candidate_path.read_text())
    assert status == 0
    assert [source["vpu"] for source in candidate["sources"]] == ["01", "02"]
    identifier = candidate["identifiers"][0]
    assert identifier["observations"]["01"]["prefix_counts"] == {"nex": 1, "wb": 2}
    assert identifier["observations"]["02"]["prefix_counts"] == {"nex": 1, "wb": 1, "zz": 1}
    # The vocabulary is the union over every VPU supplied.
    assert identifier["observed_prefixes"] == ["nex", "wb", "zz"]
    assert [(entry["vpu"], entry["table"]) for entry in candidate["terminal_observations"]] == [
        ("01", "nexus"), ("01", "network"), ("02", "nexus"), ("02", "network")]


def test_conflicting_structures_are_reported_and_no_candidate_is_written(models, tmp_path, capsys):
    install(models, base_ngen_spec(), "ngen")
    first, second = ngen_gpkg(tmp_path, "01"), ngen_gpkg(tmp_path, "02")
    # VPU 02's network layer lacks a column that VPU 01's has.
    pyogrio.write_dataframe(
        pd.DataFrame({"id": ["wb-1"], "toid": ["wb-0"], "hydroseq": [1.0], "divide_id": ["cat-1"], "vpuid": ["02"]}),
        second, layer="network", geometry_type=None)
    candidate_path = tmp_path / "candidate.json"

    status = extract(first, second, "--data-model", "v9.9", "--type", "ngen", "--output", candidate_path)

    report = capsys.readouterr().err
    assert status == 1
    assert not candidate_path.exists()
    # The report names the layer, both VPUs and the column that differs.
    assert "network" in report and "01" in report and "02" in report and "type" in report


def test_urls_are_recorded_only_when_supplied(models, tmp_path):
    install(models, base_ngen_spec(), "ngen")
    first, second = ngen_gpkg(tmp_path, "01"), ngen_gpkg(tmp_path, "02")
    resource = "https://www.hydroshare.org/resource/0123456789abcdef0123456789abcdef/"
    file_url = resource + "data/contents/ngen-hydrofabric-vpu-01.gpkg"
    candidate_path = tmp_path / "candidate.json"

    status = extract(first, second, "--data-model", "v9.9", "--type", "ngen", "--output", candidate_path,
                     "--resource-url", resource, "--file-url", f"01={file_url}")

    sources = json.loads(candidate_path.read_text())["sources"]
    assert status == 0
    # The file URL is attached to the VPU it was given for; nothing is invented for the other VPU.
    assert list(sources[0]) == ["vpu", "filename", "resource_url", "file_url", "local_path", "sha256"]
    assert (sources[0]["resource_url"], sources[0]["file_url"]) == (resource, file_url)
    assert list(sources[1]) == ["vpu", "filename", "resource_url", "local_path", "sha256"]


def test_candidate_goes_to_the_scratch_folder_by_default(models, tmp_path, monkeypatch):
    checked_in = install(models, base_reference_spec())
    before = checked_in.read_text()
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(extract_data_model, "CANDIDATES", scratch)

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference")

    assert status == 0
    assert list(json.loads((scratch / "v9.9" / "reference.json").read_text())["tables"]) == [
        "divides", "flowpaths", "network"]
    assert checked_in.read_text() == before


def test_update_replaces_the_checked_in_specification(models, tmp_path):
    checked_in = install(models, base_reference_spec())

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference", "--update")

    assert status == 0
    updated = data_model.load_spec("v9.9", "reference")
    assert list(updated["tables"]) == ["divides", "flowpaths", "network"]
    assert updated["attribute_constraints"] == base_reference_spec()["attribute_constraints"]
    assert checked_in.exists()


def test_the_checked_in_specification_is_not_overwritten_without_update(models, tmp_path, capsys):
    checked_in = install(models, base_reference_spec())
    before = checked_in.read_text()

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference",
                     "--output", checked_in)

    assert status == 2
    assert "--update" in capsys.readouterr().err
    assert checked_in.read_text() == before


def spec_with_a_rule_the_files_cannot_satisfy():
    """Reviewed content that refers to a layer these GeoPackages do not have."""
    base = base_reference_spec()
    base["checks"]["network"]["primary_ids"]["hydrolocations"] = "hl_id"
    return base


def test_candidate_the_checks_cannot_use_is_written_for_review_and_flagged(models, tmp_path, capsys):
    install(models, spec_with_a_rule_the_files_cannot_satisfy())
    candidate_path = tmp_path / "candidate.json"

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference",
                     "--output", candidate_path)

    report = capsys.readouterr().err
    assert status == 1
    assert candidate_path.exists()
    assert "hydrolocations" in report and "reviewed" in report


def test_update_refuses_a_specification_the_checks_cannot_use(models, tmp_path, capsys):
    checked_in = install(models, spec_with_a_rule_the_files_cannot_satisfy())
    before = checked_in.read_text()

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference", "--update")

    assert status == 1
    assert checked_in.read_text() == before
    assert "hydrolocations" in capsys.readouterr().err


def test_a_data_model_without_a_reviewed_specification_is_refused(models, tmp_path, capsys):
    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference",
                     "--output", tmp_path / "candidate.json")

    assert status == 2
    assert "reviewed specification" in capsys.readouterr().err
    assert not (tmp_path / "candidate.json").exists()


def test_a_geopackage_with_an_unexpected_name_is_refused(models, tmp_path, capsys):
    install(models, base_reference_spec())
    wrong = reference_gpkg(tmp_path).rename(tmp_path / "data" / "my-copy.gpkg")

    status = extract(wrong, "--data-model", "v9.9", "--type", "reference", "--output", tmp_path / "c.json")

    assert status == 2
    assert "my-copy.gpkg" in capsys.readouterr().err


def test_two_geopackages_for_one_vpu_are_refused(models, tmp_path, capsys):
    install(models, base_reference_spec())
    first = reference_gpkg(tmp_path)
    (tmp_path / "other").mkdir()
    second = tmp_path / "other" / first.name
    second.write_bytes(first.read_bytes())

    status = extract(first, second, "--data-model", "v9.9", "--type", "reference", "--output", tmp_path / "c.json")

    assert status == 2
    assert "VPU 01" in capsys.readouterr().err


@pytest.mark.parametrize("option", ["99=https://example.org/f.gpkg", "no-equals-sign"])
def test_a_file_url_must_name_a_supplied_vpu(models, tmp_path, capsys, option):
    install(models, base_reference_spec())

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference",
                     "--output", tmp_path / "c.json", "--file-url", option)

    assert status == 2
    assert "--file-url" in capsys.readouterr().err


def test_a_file_that_is_not_a_geopackage_is_refused(models, tmp_path, capsys):
    install(models, base_reference_spec())
    fake = tmp_path / "reference-hydrofabric-vpu-01.gpkg"
    fake.write_text("not a database")

    status = extract(fake, "--data-model", "v9.9", "--type", "reference", "--output", tmp_path / "c.json")

    assert status == 2
    assert "not a readable GeoPackage" in capsys.readouterr().err


def test_content_that_a_regeneration_drops_is_reported(models, tmp_path, capsys):
    base = base_reference_spec()
    base["identifiers"] = [
        {"table": "network", "column": "id", "observations": {}},
        {"table": "hydrolocations", "column": "hl_id", "observations": {}},
    ]
    install(models, base)

    status = extract(reference_gpkg(tmp_path), "--data-model", "v9.9", "--type", "reference",
                     "--output", tmp_path / "c.json")

    notes = capsys.readouterr().err
    assert status == 0
    # The base listed VPU 99 as a source and an identifier column that these files do not have.
    assert "VPU 99" in notes
    assert "hydrolocations.hl_id" in notes
