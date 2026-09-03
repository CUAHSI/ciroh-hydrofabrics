#!/usr/bin/env python3
"""
hfsubset.py

Subset a NextGen hydrofabric geopackage down to the upstream network of a
single flowpath/divide.

Given a starting flowpath id (e.g. "wb-11221"), this script:
  1. Walks the network topology upstream, alternating between the
     `flowpaths` layer (id -> toid, where toid is a nexus id) and the
     `nexus` layer (id -> toid, where toid is the next downstream flowpath
     id), collecting every upstream flowpath and nexus id along the way.
  2. Resolves the corresponding divide ids (via `divides`) and poi ids (via
     `flowpaths`/`nexus`) for the collected upstream ids.
  3. Uses those ids to subset every feature layer present in the source
     geopackage (divides, divide-attributes, flowpaths, flowpath-attributes,
     flowpath-attributes-ml, nexus, network, pois, hydrolocations, lakes)
     into a new geopackage, using `ogr2ogr` to preserve geometry, types, and
     spatial indexes.

Usage:
    python hfsubset.py --gpkg /path/to/hydrofabric.gpkg wb-11221
    python hfsubset.py --gpkg /path/to/hydrofabric.gpkg wb-11221 -o /path/to/output/dir
"""

import argparse
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Set, Tuple

# layers to subset from the source geopackage, and the column used to filter
# each one against the set of upstream ids collected during graph traversal.
# "flowpath" -> filter on flowpath/divide ids (wb-*)
# "nexus"    -> filter on nexus ids (nex-*)
# "divide"   -> filter on divide ids (cat-*)
# "poi"      -> filter on poi ids
LAYER_KEYS: Dict[str, Tuple[str, str]] = {
    "divides": ("divide_id", "divide"),
    "divide-attributes": ("divide_id", "divide"),
    "flowpaths": ("id", "flowpath"),
    "flowpath-attributes": ("id", "flowpath"),
    "flowpath-attributes-ml": ("id", "flowpath"),
    "nexus": ("id", "nexus"),
    "network": ("id", "flowpath_or_nexus"),
    "pois": ("poi_id", "poi"),
    "hydrolocations": ("poi_id", "poi"),
    "lakes": ("poi_id", "poi"),
}


def normalize_wb_id(divide_id: str) -> str:
    """
    Normalize a user-supplied identifier (e.g. "wb-11221", "cat-11221", or
    just "11221") to the "wb-<n>" form used as the `id` key in the
    flowpaths/divides/network layers.
    """
    stem = "".join(ch for ch in divide_id if ch.isdigit())
    if not stem:
        raise ValueError(f"Could not parse a numeric id from '{divide_id}'")
    return f"wb-{stem}"


def get_edges(con: sqlite3.Connection, table: str) -> Iterable[Tuple[str, str]]:
    """Read (id, toid) pairs from the given table."""
    cur = con.cursor()
    cur.execute(
        f'SELECT "id", "toid" FROM "{table}" WHERE "id" IS NOT NULL AND "toid" IS NOT NULL'
    )
    return cur.fetchall()


def build_reverse_graph(gpkg_path: Path) -> Dict[str, Set[str]]:
    """
    Build a reverse adjacency map (toid -> set of ids that flow into it) from
    the `flowpaths` (wb -> nex) and `nexus` (nex -> wb) layers. Traversing
    this map from a starting id walks the network upstream.
    """
    con = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    reverse_adj: Dict[str, Set[str]] = {}
    try:
        for table in ("flowpaths", "nexus"):
            for id_, toid in get_edges(con, table):
                reverse_adj.setdefault(toid, set()).add(id_)
    finally:
        con.close()
    return reverse_adj


def find_upstream_ids(reverse_adj: Dict[str, Set[str]], start_id: str) -> Set[str]:
    """
    Starting at `start_id`, repeatedly find the id(s) whose toid points at an
    already-visited node (i.e. the immediate upstream nexus, then the
    flowpaths that drain into that nexus, then the nexus upstream of those,
    and so on), collecting every upstream flowpath (wb-*) and nexus (nex-*)
    id. Includes `start_id` itself in the result.
    """
    visited = {start_id}
    queue = [start_id]
    while queue:
        current = queue.pop()
        for upstream_id in reverse_adj.get(current, ()):
            if upstream_id not in visited:
                visited.add(upstream_id)
                queue.append(upstream_id)
    return visited


def resolve_divide_and_poi_ids(
    gpkg_path: Path, flowpath_ids: Set[str], nexus_ids: Set[str]
) -> Tuple[Set[str], Set[str]]:
    """
    Given the set of upstream flowpath and nexus ids, resolve the
    corresponding divide ids (from `divides`) and poi ids (from `flowpaths`
    and `nexus`).
    """
    con = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()

        divide_ids: Set[str] = set()
        if flowpath_ids:
            placeholders = ",".join("?" * len(flowpath_ids))
            cur.execute(
                f'SELECT divide_id FROM divides WHERE id IN ({placeholders}) AND divide_id IS NOT NULL',
                list(flowpath_ids),
            )
            divide_ids.update(row[0] for row in cur.fetchall())

        poi_ids: Set[str] = set()
        if flowpath_ids:
            placeholders = ",".join("?" * len(flowpath_ids))
            cur.execute(
                f'SELECT poi_id FROM flowpaths WHERE id IN ({placeholders}) AND poi_id IS NOT NULL',
                list(flowpath_ids),
            )
            poi_ids.update(row[0] for row in cur.fetchall())
        if nexus_ids:
            placeholders = ",".join("?" * len(nexus_ids))
            cur.execute(
                f'SELECT poi_id FROM nexus WHERE id IN ({placeholders}) AND poi_id IS NOT NULL',
                list(nexus_ids),
            )
            poi_ids.update(row[0] for row in cur.fetchall())
    finally:
        con.close()

    return divide_ids, poi_ids


def get_available_layers(gpkg_path: Path) -> Set[str]:
    con = sqlite3.connect(f"file:{gpkg_path}?mode=ro", uri=True)
    try:
        cur = con.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        return {row[0] for row in cur.fetchall()}
    finally:
        con.close()


def sql_in_clause(ids: Set[str]) -> str:
    """Build a quoted, comma-separated SQL IN-clause value list."""
    escaped = [str(i).replace("'", "''") for i in ids]
    return ",".join(f"'{value}'" for value in escaped)


def subset_layer(
    source_gpkg: Path,
    dest_gpkg: Path,
    layer: str,
    key_column: str,
    ids: Set[str],
) -> None:
    """Copy the rows of `layer` matching `key_column IN ids` into dest_gpkg."""
    if not ids:
        print(f"  skipping '{layer}': no matching ids")
        return

    where_clause = f'"{key_column}" IN ({sql_in_clause(ids)})'
    sql = f'SELECT * FROM "{layer}" WHERE {where_clause}'

    cmd = [
        "ogr2ogr",
        "-f", "GPKG",
        "-append",
        "-nln", layer,
        "-dialect", "SQLite",
        "-sql", sql,
        str(dest_gpkg),
        str(source_gpkg),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ogr2ogr failed while subsetting layer '{layer}':\n{result.stderr}"
        )
    print(f"  subsetted '{layer}' ({len(ids)} candidate ids)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Subset a NextGen hydrofabric geopackage to the upstream network of a divide/flowpath."
    )
    parser.add_argument(
        "divide_id",
        help="The starting flowpath/divide id, e.g. 'wb-11221' (a bare numeric id or 'cat-' prefixed id is also accepted).",
    )
    parser.add_argument(
        "--gpkg", "-g",
        required=True,
        type=Path,
        help="Path to the source NextGen hydrofabric geopackage to subset.",
    )
    parser.add_argument(
        "--output-dir", "-o",
        default=Path.cwd(),
        type=Path,
        help="Directory in which to write the subset geopackage (default: current directory).",
    )
    args = parser.parse_args()

    if not args.gpkg.exists():
        sys.exit(f"Error: source geopackage not found: {args.gpkg}")
    if shutil.which("ogr2ogr") is None:
        sys.exit("Error: 'ogr2ogr' was not found on PATH. Install GDAL's command-line tools.")

    start_id = normalize_wb_id(args.divide_id)
    print(f"Starting from flowpath id: {start_id}")

    reverse_adj = build_reverse_graph(args.gpkg)
    upstream_ids = find_upstream_ids(reverse_adj, start_id)

    if upstream_ids == {start_id}:
        print(
            f"Warning: no upstream network found for '{start_id}'. "
            "Either it has no upstream contributors, or the id doesn't exist in the source geopackage."
        )

    flowpath_ids = {i for i in upstream_ids if i.startswith("wb-")}
    nexus_ids = {i for i in upstream_ids if i.startswith("nex-")}

    divide_ids, poi_ids = resolve_divide_and_poi_ids(args.gpkg, flowpath_ids, nexus_ids)

    print(
        f"Found {len(flowpath_ids)} upstream flowpaths, {len(nexus_ids)} upstream nexuses, "
        f"{len(divide_ids)} divides, {len(poi_ids)} pois"
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    output_gpkg = args.output_dir / f"subset-{args.divide_id}.gpkg"
    if output_gpkg.exists():
        output_gpkg.unlink()

    available_layers = get_available_layers(args.gpkg)

    print(f"Writing subset geopackage: {output_gpkg}")
    for layer, (key_column, id_kind) in LAYER_KEYS.items():
        if layer not in available_layers:
            print(f"  skipping '{layer}': not present in source geopackage")
            continue

        if id_kind == "divide":
            ids = divide_ids
        elif id_kind == "flowpath":
            ids = flowpath_ids
        elif id_kind == "nexus":
            ids = nexus_ids
        elif id_kind == "flowpath_or_nexus":
            ids = flowpath_ids | nexus_ids
        elif id_kind == "poi":
            ids = poi_ids
        else:
            raise ValueError(f"Unknown id_kind '{id_kind}' for layer '{layer}'")

        subset_layer(args.gpkg, output_gpkg, layer, key_column, ids)

    print("Done.")


if __name__ == "__main__":
    main()
