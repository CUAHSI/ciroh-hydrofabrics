"""The shared check runner keeps fixture runs independent of the official recorded counts."""

import geopandas as gpd
from shapely.geometry import box

from check_runner import run_check


def recorded_counts(result):
    """Read the 'recorded count' column of every metric row in a report."""
    counts = {}
    for line in result.stdout.splitlines():
        fields = [field.strip() for field in line.split("|")]
        if len(fields) == 6 and fields[0] != "check":
            counts[f"{fields[0]} | {fields[1]}"] = fields[3]
    return counts


def fixture_gpkg(tmp_path):
    path = tmp_path / "build.gpkg"
    gpd.GeoDataFrame({"divide_id": [1.0]}, geometry=[box(0, 0, 10, 10)], crs="EPSG:5070").to_file(
        path, layer="divides", engine="pyogrio"
    )
    return path


def test_a_fixture_run_does_not_pick_up_the_official_recorded_counts(tmp_path):
    result = run_check(fixture_gpkg(tmp_path), "reference")

    assert result.returncode == 0, result.stderr
    official = {metric: count for metric, count in recorded_counts(result).items() if count not in ("0", "-")}
    assert official == {}


def test_a_test_can_still_supply_its_own_counts(tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  reference:\n    "01":\n      schema:\n        missing_layer.flowpaths: 7\n')

    result = run_check(fixture_gpkg(tmp_path), "reference", "--counts", counts)

    assert recorded_counts(result)["schema | missing_layer.flowpaths"] == "7"
