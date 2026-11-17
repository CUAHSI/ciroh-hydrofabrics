"""The shared check runner keeps test runs independent of the official recorded counts."""

import geopandas as gpd
from shapely.geometry import box

from check_runner import run_check, run_consistency_check


def recorded_counts(result):
    """Read the 'recorded count' column of every metric row in a report."""
    counts = {}
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split("|")]
        # A metric row is: check | metric | value | recorded count | result | mode.
        if len(fields) == 6 and fields[0] != "check":
            counts[f"{fields[0]} | {fields[1]}"] = fields[3]
    return counts


def official_counts(result):
    """The recorded counts of a report that are neither zero nor absent, so they came from counts.yaml."""
    return {metric: count for metric, count in recorded_counts(result).items() if count not in ("0", "-")}


def fixture_gpkg(folder, name="build.gpkg"):
    path = folder / name
    gpd.GeoDataFrame({"divide_id": [1.0]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:5070").to_file(
        path, layer="divides", engine="pyogrio"
    )
    return path


def test_a_fixture_run_does_not_pick_up_the_official_recorded_counts(tmp_path):
    result = run_check(fixture_gpkg(tmp_path), "reference")

    assert result.returncode == 0, result.stderr
    assert official_counts(result) == {}


def test_any_run_avoids_the_official_counts_not_only_vpu_01(tmp_path):
    # VPU 16 and a directory target are the shapes the CLI tests use; both have official counts on file.
    gpkg = fixture_gpkg(tmp_path, "reference-hydrofabric-vpu-16.gpkg")

    single = run_consistency_check(gpkg, "--type", "reference", "--vpu", "16")
    batch = run_consistency_check(tmp_path)

    assert single.returncode == 0, single.stderr
    assert official_counts(single) == {}
    assert official_counts(batch) == {}


def test_a_test_can_still_supply_its_own_counts(tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  reference:\n    "01":\n      schema:\n        missing_layer.flowpaths: 7\n')

    result = run_check(fixture_gpkg(tmp_path), "reference", "--counts", counts)

    assert recorded_counts(result)["schema | missing_layer.flowpaths"] == "7"


def test_an_abbreviated_counts_option_still_wins(tmp_path):
    # The command accepts unambiguous abbreviations, so the runner must not depend on spotting "--counts".
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  reference:\n    "01":\n      schema:\n        missing_layer.flowpaths: 7\n')

    result = run_check(fixture_gpkg(tmp_path), "reference", "--count", counts)

    assert recorded_counts(result)["schema | missing_layer.flowpaths"] == "7"


def test_running_leaves_no_counts_file_beside_the_fixture(tmp_path):
    gpkg = fixture_gpkg(tmp_path)

    run_check(gpkg, "reference")

    assert sorted(path.name for path in tmp_path.iterdir()) == [gpkg.name]
