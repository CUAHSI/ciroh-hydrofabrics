#!/usr/bin/env python3
"""
Compare a locally-produced hydrofabric GeoPackage against an official
reference GeoPackage downloaded from a configured URL.

This is the tool used both for local, manual testing of a pipeline run
(e.g. `pipelines/v2.2`) and, eventually, as a GitHub Action check on pull
requests that touch pipeline code or parameters.

Design: each step below is a small, single-purpose function (config lookup,
download, schema diff, attribute diff, geometry diff, report writers) so the
pieces can be reused or tested independently, per the Unix philosophy.
"""

import argparse
import csv
import json
import math
import subprocess
import sys
import urllib.request
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
import yaml


def get_git_commit_sha() -> str:
    """Return the current repo's commit SHA, or 'unknown' outside a git checkout."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def load_reference_config(config_path: Path) -> dict:
    """Read the YAML file that maps remote hydrofabric type/version/VPU -> reference URL."""
    with config_path.open() as f:
        return yaml.safe_load(f)


def resolve_reference(config: dict, remote_hydrofabric_type: str, version: str, vpu: str) -> dict:
    """Look up the reference URL and key-column settings for one dataset/version."""
    try:
        version_config = config[remote_hydrofabric_type][version]
    except KeyError:
        available = sorted(config.get(remote_hydrofabric_type, {}))
        sys.exit(
            f"Error: no config for remote_hydrofabric_type={remote_hydrofabric_type!r} version={version!r}. "
            f"Available versions: {available}"
        )

    url = version_config["url_template"].format(vpu=vpu)
    return {
        "url": url,
        "default_key_column": version_config.get("default_key_column", "id"),
        "key_columns": version_config.get("key_columns", {}),
    }


def download_reference(url: str, cache_dir: Path, force: bool = False) -> Path:
    """Download the reference GeoPackage to a local cache, reusing it on repeat runs."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / url.rsplit("/", 1)[-1]

    if dest.exists() and not force:
        print(f"Using cached reference file: {dest}")
        return dest

    print(f"Downloading reference file from {url} ...")
    urllib.request.urlretrieve(url, dest)
    return dest


def list_layers(gpkg_path: Path) -> dict:
    """Return {layer_name: geometry_type} for every layer in a GeoPackage."""
    layers = pyogrio.list_layers(str(gpkg_path))
    return {name: geom_type for name, geom_type in layers}


def compare_schema(local_layers: dict, reference_layers: dict) -> list:
    """Diff the set of layers and each layer's geometry type."""
    rows = []
    for layer in sorted(set(local_layers) | set(reference_layers)):
        # Use "in" (not a .get(...) is None check) so a non-spatial layer
        # that legitimately has geometry_type=None isn't mistaken for a
        # layer that is missing entirely from one of the files.
        local_present = layer in local_layers
        reference_present = layer in reference_layers
        local_geom = local_layers.get(layer)
        reference_geom = reference_layers.get(layer)
        if not local_present:
            status = "missing_in_local"
        elif not reference_present:
            status = "missing_in_reference"
        elif local_geom != reference_geom:
            status = "geometry_type_mismatch"
        else:
            status = "match"
        rows.append(
            {
                "layer": layer,
                "local_geometry_type": local_geom,
                "reference_geometry_type": reference_geom,
                "status": status,
            }
        )
    return rows


def values_equal(local_value, reference_value) -> bool:
    """Compare two attribute values, treating NaN/None on both sides as equal.

    Plain `!=` treats NaN as never equal to itself, which would otherwise
    flag every missing-value cell as a "difference" even when both files
    agree that the value is missing.
    """
    if pd.isna(local_value) and pd.isna(reference_value):
        return True
    return local_value == reference_value


def key_column_for_layer(layer: str, key_columns: dict, default_key_column):
    """Pick the id column(s) used to match features for one layer.

    A layer's key may be a single column name or, for layers where no single
    column is unique per row (e.g. a "network" table with one row per
    divide/flowpath pairing), a list of column names used together.
    """
    return key_columns.get(layer, default_key_column)


def format_key_label(key_column, key_value) -> str:
    """Render a feature key as "column=value" (or "col1=v1, col2=v2" for a
    composite key), so reports show which id column a key refers to instead
    of a bare, ambiguous value.
    """
    columns = [key_column] if isinstance(key_column, str) else list(key_column)
    values = key_value if isinstance(key_value, tuple) else (key_value,)
    return ", ".join(f"{c}={v}" for c, v in zip(columns, values))


def count_vertices(geom) -> int:
    """Count a geometry's total coordinate points, recursing into multi-part
    geometries and polygon rings so the count is meaningful for any type.
    """
    if geom is None:
        return 0
    if hasattr(geom, "geoms"):  # Multi* geometry
        return sum(count_vertices(part) for part in geom.geoms)
    if geom.geom_type == "Polygon":
        return len(geom.exterior.coords) + sum(len(ring.coords) for ring in geom.interiors)
    return len(geom.coords)


def describe_geometry_diff(local_geom, reference_geom) -> dict:
    """Compute specific metrics describing how two differing geometries
    differ, instead of only flagging that they are unequal: how far apart
    they are (Hausdorff distance), how their size compares (length for
    lines, area for polygons), how many vertices each has, and whether one
    is simply the other with its vertex order reversed.
    """
    metrics = {
        "hausdorff_distance": None,
        "size_kind": None,
        "reference_size": None,
        "local_size": None,
        "reference_vertex_count": count_vertices(reference_geom),
        "local_vertex_count": count_vertices(local_geom),
        "reversed": False,
    }
    if local_geom is None or reference_geom is None:
        return metrics

    metrics["hausdorff_distance"] = local_geom.hausdorff_distance(reference_geom)

    is_polygonal = reference_geom.geom_type in ("Polygon", "MultiPolygon")
    metrics["size_kind"] = "area" if is_polygonal else "length"
    metrics["reference_size"] = reference_geom.area if is_polygonal else reference_geom.length
    metrics["local_size"] = local_geom.area if is_polygonal else local_geom.length

    if reference_geom.geom_type == local_geom.geom_type:
        metrics["reversed"] = shapely.reverse(local_geom).equals_exact(reference_geom, 1e-6)

    return metrics


def compare_layer(local_gdf, reference_gdf, key_column, layer: str, tolerance: float) -> dict:
    """Compare one layer's row counts, attribute values, geometries, and CRS.

    Some layers (e.g. "network") are plain attribute tables with no geometry
    column, so geopandas returns a regular DataFrame for them instead of a
    GeoDataFrame. CRS/geometry checks are skipped for those layers.
    """
    key_columns = [key_column] if isinstance(key_column, str) else list(key_column)
    is_spatial = hasattr(local_gdf, "crs") and hasattr(reference_gdf, "crs")

    result = {
        "layer": layer,
        "key_column": key_column,
        "local_row_count": len(local_gdf),
        "reference_row_count": len(reference_gdf),
        "local_crs": str(local_gdf.crs) if is_spatial else None,
        "reference_crs": str(reference_gdf.crs) if is_spatial else None,
        "crs_match": (local_gdf.crs == reference_gdf.crs) if is_spatial else True,
        "attribute_diffs": [],
        "geometry_diffs": [],
        "missing_in_local": [],
        "missing_in_reference": [],
    }

    missing_columns = [
        c for c in key_columns if c not in local_gdf.columns or c not in reference_gdf.columns
    ]
    if missing_columns:
        result["error"] = f"key column(s) {missing_columns} not present in both layers"
        return result

    local_by_key = local_gdf.set_index(key_columns)
    reference_by_key = reference_gdf.set_index(key_columns)

    for name, gdf in (("local", local_by_key), ("reference", reference_by_key)):
        if gdf.index.duplicated().any():
            result["error"] = (
                f"key column(s) {key_columns} are not unique in the {name} layer; "
                "choose a different key_columns entry for this layer"
            )
            return result

    local_keys = set(local_by_key.index)
    reference_keys = set(reference_by_key.index)

    # Keep keys in their original (scalar or tuple) form here; they are only
    # rendered as "column=value" labels later, in build_attribute_diff_rows
    # and build_geometry_diff_rows, where the key column name(s) are
    # available.
    result["missing_in_local"] = sorted(reference_keys - local_keys, key=str)
    result["missing_in_reference"] = sorted(local_keys - reference_keys, key=str)

    # Compare only columns present in both files, excluding the geometry
    # column (compared separately below) and the key column itself (it is
    # no longer a column after set_index above).
    shared_columns = [
        c
        for c in local_by_key.columns
        if c in reference_by_key.columns and c != "geometry"
    ]

    for key in sorted(local_keys & reference_keys, key=str):
        local_row = local_by_key.loc[key]
        reference_row = reference_by_key.loc[key]

        for column in shared_columns:
            local_value = local_row[column]
            reference_value = reference_row[column]
            if not values_equal(local_value, reference_value):
                result["attribute_diffs"].append(
                    {
                        "key": key,
                        "column": column,
                        "local_value": local_value,
                        "reference_value": reference_value,
                    }
                )

        local_geom = local_row.geometry if is_spatial else None
        reference_geom = reference_row.geometry if is_spatial else None
        if not is_spatial:
            continue
        if local_geom is None or reference_geom is None:
            geometries_equal = local_geom is reference_geom
        else:
            geometries_equal = local_geom.equals_exact(reference_geom, tolerance)
        if not geometries_equal:
            result["geometry_diffs"].append(
                {"key": key, **describe_geometry_diff(local_geom, reference_geom)}
            )

    return result


def build_report(schema_diffs: list, layer_results: list, metadata: dict) -> dict:
    """Combine schema and per-layer results, plus a short pass/fail summary."""
    has_differences = any(row["status"] != "match" for row in schema_diffs) or any(
        layer.get("error")
        or layer["local_row_count"] != layer["reference_row_count"]
        or not layer["crs_match"]
        or layer["attribute_diffs"]
        or layer["geometry_diffs"]
        or layer["missing_in_local"]
        or layer["missing_in_reference"]
        for layer in layer_results
    )
    return {
        "metadata": metadata,
        "has_differences": has_differences,
        "schema_diffs": schema_diffs,
        "layer_results": layer_results,
    }


def build_attribute_diff_rows(report: dict) -> list:
    """Flatten non-geometry differences into one row per difference.

    Each row is [layer, kind, key, attribute, original_value, new_value],
    where "original_value" comes from the official reference GeoPackage and
    "new_value" comes from the local/generated GeoPackage being checked.
    Geometry differences are handled separately by
    `build_geometry_diff_rows`, since they report different metrics.
    """
    rows = []

    for row in report["schema_diffs"]:
        if row["status"] != "match":
            rows.append(
                [row["layer"], "schema", "", "geometry_type", row["reference_geometry_type"], row["local_geometry_type"]]
            )

    for layer in report["layer_results"]:
        name = layer["layer"]
        if layer.get("error"):
            rows.append([name, "error", "", "", "", layer["error"]])
            continue
        if layer["local_row_count"] != layer["reference_row_count"]:
            rows.append([name, "row_count", "", "", layer["reference_row_count"], layer["local_row_count"]])
        if not layer["crs_match"]:
            rows.append([name, "crs", "", "", layer["reference_crs"], layer["local_crs"]])

        key_column = layer["key_column"]
        for key in layer["missing_in_local"]:
            rows.append([name, "missing_in_local", format_key_label(key_column, key), "", "", ""])
        for key in layer["missing_in_reference"]:
            rows.append([name, "missing_in_reference", format_key_label(key_column, key), "", "", ""])
        for diff in layer["attribute_diffs"]:
            rows.append(
                [
                    name,
                    "attribute",
                    format_key_label(key_column, diff["key"]),
                    diff["column"],
                    diff["reference_value"],
                    diff["local_value"],
                ]
            )

    return rows


def build_geometry_diff_rows(report: dict) -> list:
    """Flatten geometry differences into one row per differing feature.

    Each row is [layer, key, hausdorff_distance, length_or_area,
    vertex_count, vertex_order], reporting only the local/new file's
    values (not the reference/original ones), since these are descriptive
    metrics rather than a single changed value. A cell is left blank when
    that particular metric matches between the two files, so only the
    metric(s) that actually explain the geometry difference are shown.
    """
    rows = []
    for layer in report["layer_results"]:
        if layer.get("error"):
            continue
        name = layer["layer"]
        key_column = layer["key_column"]
        for diff in layer["geometry_diffs"]:
            hausdorff_distance = "" if diff["hausdorff_distance"] == 0 else f"{diff['hausdorff_distance']:.6g}"
            # Use a relative tolerance, not exact equality: summing segment
            # lengths in reverse order can produce a tiny floating-point
            # difference even when the shape's size is really unchanged.
            size_unchanged = math.isclose(diff["local_size"], diff["reference_size"], rel_tol=1e-9, abs_tol=1e-9)
            length_or_area = "" if size_unchanged else f"{diff['local_size']:.6g} ({diff['size_kind']})"
            count_unchanged = diff["local_vertex_count"] == diff["reference_vertex_count"]
            vertex_count = "" if count_unchanged else diff["local_vertex_count"]
            vertex_order = "reversed" if diff["reversed"] else ""
            rows.append(
                [
                    name,
                    format_key_label(key_column, diff["key"]),
                    hausdorff_distance,
                    length_or_area,
                    vertex_count,
                    vertex_order,
                ]
            )
    return rows


def write_json_report(report: dict, path: Path) -> None:
    path.write_text(json.dumps(report, indent=2, default=str))


def write_csv_report(attribute_rows: list, geometry_rows: list, path: Path) -> None:
    """Write one CSV with two sections: attribute/schema differences, then
    geometry differences, since the two kinds of difference report
    different columns.
    """
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["layer", "kind", "key", "attribute", "original_value", "new_value"])
        writer.writerows(attribute_rows)
        writer.writerow([])
        writer.writerow(["layer", "key", "hausdorff_distance", "length_or_area", "vertex_count", "vertex_order"])
        writer.writerows(geometry_rows)


def write_markdown_report(report: dict, attribute_rows: list, geometry_rows: list, path: Path) -> None:
    """Write a short human-readable summary, suitable for a PR comment or job summary."""
    metadata = report["metadata"]
    lines = ["# Hydrofabric Comparison Report", ""]
    lines.append(f"- **Hydrofabric type:** {metadata['remote_hydrofabric_type']}")
    lines.append(f"- **Version:** {metadata['version']}")
    lines.append(f"- **VPU:** {metadata['vpu']}")
    lines.append(f"- **Git commit:** {metadata['git_commit']}")
    lines.append("")
    status = "DIFFERENCES FOUND" if report["has_differences"] else "MATCH"
    lines.append(f"**Result:** {status}")
    lines.append("")

    lines.append("## Schema")
    lines.append("")
    lines.append("| Layer | Original Geometry | New Geometry | Status |")
    lines.append("|---|---|---|---|")
    for row in report["schema_diffs"]:
        lines.append(
            f"| {row['layer']} | {row['reference_geometry_type']} | {row['local_geometry_type']} | {row['status']} |"
        )
    lines.append("")

    lines.append("## Layers")
    lines.append("")
    lines.append("| Layer | Original Rows | New Rows | CRS Match | Attribute Diffs | Geometry Diffs | Missing Local | Missing Reference |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for layer in report["layer_results"]:
        if layer.get("error"):
            lines.append(f"| {layer['layer']} | - | - | - | - | - | - | error: {layer['error']} |")
            continue
        lines.append(
            f"| {layer['layer']} | {layer['reference_row_count']} | {layer['local_row_count']} | "
            f"{layer['crs_match']} | {len(layer['attribute_diffs'])} | {len(layer['geometry_diffs'])} | "
            f"{len(layer['missing_in_local'])} | {len(layer['missing_in_reference'])} |"
        )
    lines.append("")

    lines.append("## Attribute & Schema Differences")
    lines.append("")
    lines.append(
        "Each row below is one non-geometry difference found between the local "
        "(your pipeline's) GeoPackage and the official reference GeoPackage.  "
    )
    lines.append(
        "**Key** identifies the feature as `column=value` (using the id column(s) "
        "configured for that layer); **Attribute** is the specific column that "
        "differs (blank for schema/row-count/CRS/missing-feature differences).  "
    )
    lines.append(
        "**Original Value** is the value from the official reference file, and "
        "**New Value** is the value from the local file being checked."
    )
    lines.append("")
    if attribute_rows:
        lines.append("| Layer | Kind | Key | Attribute | Original Value | New Value |")
        lines.append("|---|---|---|---|---|---|")
        for layer, kind, key, attribute, original_value, new_value in attribute_rows:
            lines.append(f"| {layer} | {kind} | {key} | {attribute} | {original_value} | {new_value} |")
    else:
        lines.append("No attribute or schema differences found.")
    lines.append("")

    lines.append("## Geometry Differences")
    lines.append("")
    lines.append(
        "Each row below is one feature whose shape differs between the local "
        "and reference files, described by these metrics (only the local/new "
        "file's values are shown, since these describe the shape rather than "
        "a single changed value). A cell is left blank when that metric is "
        "the same in both files, so only the metric(s) that explain the "
        "difference are shown:  "
    )
    lines.append("")
    lines.append("- `hausdorff_distance`: the maximum distance between the local and reference shapes (blank when 0, i.e. the shapes occupy exactly the same points).")
    lines.append("- `length_or_area`: the line length (or polygon area) of the local shape (blank when it matches the reference shape's size).")
    lines.append("- `vertex_count`: the number of coordinate points making up the local shape (blank when it matches the reference shape's vertex count).")
    lines.append("- `vertex_order`: `reversed` when the shape is otherwise identical but its vertices are stored in the opposite direction; blank otherwise.")
    lines.append("")
    if geometry_rows:
        lines.append("| Layer | Key | Hausdorff Distance | Length / Area | Vertex Count | Vertex Order |")
        lines.append("|---|---|---|---|---|---|")
        for layer, key, hausdorff_distance, length_or_area, vertex_count, vertex_order in geometry_rows:
            lines.append(f"| {layer} | {key} | {hausdorff_distance} | {length_or_area} | {vertex_count} | {vertex_order} |")
    else:
        lines.append("No geometry differences found.")
    lines.append("")


    path.write_text("\n".join(lines))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare a local hydrofabric GeoPackage against an official reference version."
    )
    parser.add_argument("local_gpkg", type=Path, help="Path to the pipeline-produced GeoPackage")
    parser.add_argument("--version", required=True, help="Hydrofabric version key, e.g. v2.2")
    parser.add_argument("--vpu", required=True, help="VPU id, e.g. 01, 03N, 16")
    parser.add_argument(
        "--remote-hydrofabric-type",
        default="ngen_hydrofabric",
        choices=["ngen_hydrofabric", "reference_hydrofabric"],
        help="Which official/remote hydrofabric to compare against (default: ngen_hydrofabric)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "reference_sources.yaml",
        help="Path to reference_sources.yaml",
    )
    parser.add_argument(
        "--reference-url",
        help="Override the reference GeoPackage URL instead of looking it up in the config",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).parent / ".cache",
        help="Directory used to cache downloaded reference GeoPackages",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download the reference GeoPackage even if it is already cached",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent / "reports",
        help="Directory to write the CSV/JSON/Markdown reports into",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-6,
        help="Coordinate tolerance used for geometry equality checks",
    )
    parser.add_argument(
        "--fail-on-diff",
        action="store_true",
        help="Exit with a non-zero status if any differences are found",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.local_gpkg.is_file():
        sys.exit(f"Error: local GeoPackage not found: {args.local_gpkg}")

    # Always load key-column settings from the config (so per-layer id
    # columns are respected); --reference-url only overrides which file gets
    # downloaded, not how features within it are matched.
    config = load_reference_config(args.config)
    reference = resolve_reference(config, args.remote_hydrofabric_type, args.version, args.vpu)
    if args.reference_url:
        reference["url"] = args.reference_url

    reference_gpkg = download_reference(reference["url"], args.cache_dir, force=args.force_download)

    local_layers = list_layers(args.local_gpkg)
    reference_layers = list_layers(reference_gpkg)
    schema_diffs = compare_schema(local_layers, reference_layers)

    layer_results = []
    shared_layers = sorted(set(local_layers) & set(reference_layers))
    for layer in shared_layers:
        local_gdf = gpd.read_file(args.local_gpkg, layer=layer)
        reference_gdf = gpd.read_file(reference_gpkg, layer=layer)
        key_column = key_column_for_layer(layer, reference["key_columns"], reference["default_key_column"])
        layer_results.append(compare_layer(local_gdf, reference_gdf, key_column, layer, args.tolerance))

    metadata = {
        "remote_hydrofabric_type": args.remote_hydrofabric_type,
        "version": args.version,
        "vpu": args.vpu,
        "git_commit": get_git_commit_sha(),
    }
    report = build_report(schema_diffs, layer_results, metadata)
    attribute_rows = build_attribute_diff_rows(report)
    geometry_rows = build_geometry_diff_rows(report)

    output_dir = args.output_dir / args.remote_hydrofabric_type / args.version / args.vpu
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json_report(report, output_dir / "report.json")
    write_csv_report(attribute_rows, geometry_rows, output_dir / "report.csv")
    write_markdown_report(report, attribute_rows, geometry_rows, output_dir / "report.md")

    print(f"Reports written to {output_dir}")

    if args.fail_on_diff and report["has_differences"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
