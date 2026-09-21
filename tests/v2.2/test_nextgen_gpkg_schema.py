"""
Schema-structure tests for the NextGen v2.2 hydrofabric pipeline output.

These tests compare the *structure* (layer names/registration, column
names/order, column types, geometry types, and id-naming conventions) of the
pipeline's output geopackage (ngen-workflow/output/v2.2/ngen/16/
ngen_hydrofabric_final.gpkg) against the official NextGen v2.2 hydrofabric
geopackage (/Users/castro/Documents/work/hydrofabric/data/v2.2/
conus_nextgen.gpkg). They intentionally do NOT compare data values, since the
pipeline output is a single-VPU subset and the reference file is the full
CONUS dataset.

NOTE: this module is specific to the v2.2 hydrofabric data model. Future
hydrofabric versions (e.g. v2.3+) are expected to introduce schema changes and
should get their own test module under tests/v2.3/, rather than modifying
this one.
"""

import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import pytest

# The full set of NextGen v2.2 layers, as defined by the official reference
# geopackage (data/v2.2/conus_nextgen.gpkg).
EXPECTED_LAYERS = [
    "divides",
    "divide-attributes",
    "flowpaths",
    "flowpath-attributes",
    "flowpath-attributes-ml",
    "nexus",
    "network",
    "pois",
    "hydrolocations",
    "lakes",
]

# Layers that carry their own geometry column (the rest are attribute-only
# tables joined to a spatial layer via id/divide_id/poi_id).
SPATIAL_LAYERS = ["divides", "flowpaths", "nexus", "hydrolocations", "lakes"]

# id-like columns to check for a consistent prefixed-identifier naming
# convention (e.g. "wb-1234", "nex-1234", "cat-1234"), per layer. Columns not
# listed here either aren't identifiers or don't use a prefix convention
# (e.g. lakes.poi_id, which is a bare integer).
ID_LIKE_COLUMNS = {
    "divides": ["divide_id", "id", "toid"],
    "flowpaths": ["id", "toid", "divide_id"],
    "nexus": ["id", "toid"],
    "network": ["id", "toid", "divide_id"],
    "pois": ["id", "nex_id"],
    "hydrolocations": ["id", "nex_id"],
    "flowpath-attributes": ["id", "toid"],
    "flowpath-attributes-ml": ["id", "toid"],
}


# --------------------------------------------------------------------------
# sqlite helpers
# --------------------------------------------------------------------------


def _connect(gpkg: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{gpkg}?mode=ro", uri=True)


def table_exists(gpkg: Path, table: str) -> bool:
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (table,)
        )
        return cur.fetchone() is not None
    finally:
        con.close()


def get_gpkg_contents(gpkg: Path) -> Dict[str, str]:
    """Return {layer_name: data_type} for every layer registered in gpkg_contents."""
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute("SELECT table_name, data_type FROM gpkg_contents")
        return dict(cur.fetchall())
    finally:
        con.close()


def get_columns(gpkg: Path, table: str) -> List[Tuple[str, str]]:
    """Return an ordered list of (column_name, declared_type) for a table."""
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute(f'PRAGMA table_info("{table}")')
        return [(row[1], row[2]) for row in cur.fetchall()]
    finally:
        con.close()


def get_geometry_info(gpkg: Path, table: str) -> Optional[Tuple[str, int]]:
    """Return (geometry_type_name, srs_id) for a spatial layer, or None."""
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute(
            "SELECT geometry_type_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
            (table,),
        )
        return cur.fetchone()
    finally:
        con.close()


def get_id_prefixes(gpkg: Path, table: str, column: str) -> Set[str]:
    """
    Return the *complete* set of alphabetic prefixes used by an id-like
    column's values, e.g. 'wb-1234' -> 'wb', 'nex-1234' -> 'nex'.

    This queries every distinct prefix directly via SQL (not a small sample
    of distinct full values), since a naive small LIMIT-based sample of an
    unordered SELECT DISTINCT can be dominated by a single prefix purely due
    to SQLite's internal scan/dedup order (e.g. returning 500 'tnx-' rows
    before ever reaching a 'nex-' row), producing false negatives for
    legitimately-used prefixes that happen to be less common or ordered
    later.
    """
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute(
            f'SELECT DISTINCT substr("{column}", 1, instr("{column}", \'-\') - 1) '
            f'FROM "{table}" WHERE "{column}" IS NOT NULL AND "{column}" LIKE \'%-%\''
        )
        return {row[0] for row in cur.fetchall() if row[0]}
    finally:
        con.close()


def count_non_null(gpkg: Path, table: str, column: str) -> int:
    """Return the number of non-null values of a column in a table."""
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IS NOT NULL')
        return cur.fetchone()[0]
    finally:
        con.close()


def count_rows(gpkg: Path, table: str) -> int:
    """Return the total number of rows in a table."""
    con = _connect(gpkg)
    try:
        cur = con.cursor()
        cur.execute(f'SELECT COUNT(*) FROM "{table}"')
        return cur.fetchone()[0]
    finally:
        con.close()


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------


@pytest.mark.parametrize("layer", EXPECTED_LAYERS)
def test_layer_exists(pipeline_gpkg, reference_gpkg, layer):
    """Every layer in the official v2.2 schema must exist as a table in the pipeline output."""
    assert table_exists(reference_gpkg, layer), (
        f"'{layer}' unexpectedly missing from the reference file itself; "
        "check EXPECTED_LAYERS against the reference geopackage"
    )
    assert table_exists(pipeline_gpkg, layer), (
        f"layer '{layer}' does not exist as a table in the pipeline output geopackage"
    )


@pytest.mark.parametrize("layer", EXPECTED_LAYERS)
def test_layer_registered_in_gpkg_contents(pipeline_gpkg, reference_gpkg, layer):
    """
    Every layer must be properly registered in gpkg_contents with the same
    data_type ('features' or 'attributes') as the official reference file.
    A layer that exists as a raw sqlite table but is missing from
    gpkg_contents will not be recognized by GeoPackage-spec-compliant tooling
    (e.g. ngiab_data_cli), even though it can still be queried directly with
    SQL.
    """
    ref_contents = get_gpkg_contents(reference_gpkg)
    pipe_contents = get_gpkg_contents(pipeline_gpkg)

    assert layer in ref_contents, f"'{layer}' unexpectedly missing from the reference file's gpkg_contents"
    assert layer in pipe_contents, (
        f"layer '{layer}' is missing from the pipeline output's gpkg_contents table "
        "(it may exist as a raw table but isn't registered as a proper GeoPackage layer)"
    )
    assert pipe_contents[layer] == ref_contents[layer], (
        f"layer '{layer}' has data_type '{pipe_contents[layer]}' in the pipeline output, "
        f"expected '{ref_contents[layer]}' (as in the reference file)"
    )


@pytest.mark.parametrize("layer", EXPECTED_LAYERS)
def test_column_names_match(pipeline_gpkg, reference_gpkg, layer):
    """The set of column names in each layer must match the reference schema."""
    if not table_exists(pipeline_gpkg, layer):
        pytest.fail(f"layer '{layer}' does not exist in the pipeline output")

    ref_cols = {name for name, _ in get_columns(reference_gpkg, layer)}
    pipe_cols = {name for name, _ in get_columns(pipeline_gpkg, layer)}

    missing = ref_cols - pipe_cols
    extra = pipe_cols - ref_cols
    assert not missing and not extra, (
        f"column mismatch in layer '{layer}': missing={sorted(missing)}, extra={sorted(extra)}"
    )


@pytest.mark.parametrize("layer", EXPECTED_LAYERS)
def test_column_order_matches(pipeline_gpkg, reference_gpkg, layer):
    """
    Columns should also appear in the same physical order as the reference
    schema. This matters beyond cosmetics: some downstream tools (e.g.
    ngiab_data_cli's subset_table()/insert_data()) copy rows between
    geopackages using positional `INSERT INTO ... VALUES (...)` statements
    built against a fixed template schema, so a column in the wrong physical
    position will silently receive the wrong value instead of raising an
    error.
    """
    if not table_exists(pipeline_gpkg, layer):
        pytest.fail(f"layer '{layer}' does not exist in the pipeline output")

    ref_cols = [name for name, _ in get_columns(reference_gpkg, layer)]
    pipe_cols = [name for name, _ in get_columns(pipeline_gpkg, layer)]

    if set(ref_cols) != set(pipe_cols):
        pytest.skip(f"column sets differ for '{layer}'; see test_column_names_match")

    assert pipe_cols == ref_cols, (
        f"column order mismatch in layer '{layer}':\n"
        f"  expected: {ref_cols}\n"
        f"  actual:   {pipe_cols}"
    )


@pytest.mark.parametrize("layer", EXPECTED_LAYERS)
def test_column_types_match(pipeline_gpkg, reference_gpkg, layer):
    """
    Declared SQL types for columns common to both files should match (e.g.
    TEXT, REAL, MEDIUMINT, BOOLEAN). The 'geom' column's exact geometry
    subtype is checked separately in test_geometry_matches, since GDAL may
    report either a generic 'GEOMETRY' or a specific subtype here depending
    on how the layer was written.
    """
    if not table_exists(pipeline_gpkg, layer):
        pytest.fail(f"layer '{layer}' does not exist in the pipeline output")

    ref_types = dict(get_columns(reference_gpkg, layer))
    pipe_types = dict(get_columns(pipeline_gpkg, layer))

    mismatches = []
    for col, ref_type in ref_types.items():
        if col == "geom":
            continue
        if col not in pipe_types:
            continue  # already reported by test_column_names_match
        if pipe_types[col] != ref_type:
            mismatches.append(f"{col}: expected {ref_type!r}, got {pipe_types[col]!r}")

    assert not mismatches, (
        f"type mismatches in layer '{layer}':\n  " + "\n  ".join(mismatches)
    )


@pytest.mark.parametrize("layer", SPATIAL_LAYERS)
def test_geometry_matches(pipeline_gpkg, reference_gpkg, layer):
    """
    Spatial layers should have the same registered SRS, and either the same
    geometry type or a more specific one than the reference.

    GDAL infers a layer's declared geometry_type_name from the actual
    geometries written to it. This means:
      - an empty layer (0 features, e.g. a VPU with no lake/reservoir POIs)
        has nothing for GDAL to infer a type from, so it's registered as
        generic 'GEOMETRY' -- this isn't a schema defect, just a consequence
        of there being no data for this VPU, so it's skipped rather than
        failed.
      - a layer where every feature happens to share one concrete subtype
        (e.g. all MULTILINESTRING) may be declared with that specific type
        even where the reference (built across more geometry variety, e.g.
        full CONUS) settled on the generic 'GEOMETRY'. A specific declared
        type is strictly more informative than a generic one and is not a
        real mismatch, so it's accepted here too.
    """
    if count_rows(pipeline_gpkg, layer) == 0:
        pytest.skip(
            f"'{layer}' has no features in the pipeline output for this VPU; "
            "geometry type can't be meaningfully validated with no data"
        )

    ref_geom = get_geometry_info(reference_gpkg, layer)
    pipe_geom = get_geometry_info(pipeline_gpkg, layer)

    assert ref_geom is not None, (
        f"'{layer}' unexpectedly has no geometry column registered in the reference file"
    )
    assert pipe_geom is not None, (
        f"'{layer}' has no geometry column registered in gpkg_geometry_columns "
        "in the pipeline output"
    )

    ref_geom_type, ref_srs = ref_geom
    pipe_geom_type, pipe_srs = pipe_geom

    assert pipe_geom_type == ref_geom_type or ref_geom_type == "GEOMETRY", (
        f"geometry type mismatch in '{layer}': expected {ref_geom_type!r}, got {pipe_geom_type!r}"
    )
    assert pipe_srs == ref_srs, (
        f"SRS mismatch in '{layer}': expected {ref_srs!r}, got {pipe_srs!r}"
    )


@pytest.mark.parametrize(
    "layer,column",
    [(layer, col) for layer, cols in ID_LIKE_COLUMNS.items() for col in cols],
)
def test_id_naming_convention_matches(pipeline_gpkg, reference_gpkg, layer, column):
    """
    id-like columns (id, toid, divide_id, nex_id, ...) should use the same
    prefixed-identifier naming convention (e.g. 'wb-', 'nex-', 'cat-') as the
    official reference file. This does NOT check exact values (which will
    differ, since the pipeline output is a single-VPU subset) -- only that
    the *set* of naming prefixes used is consistent with the reference.

    Some VPUs legitimately have no POIs at all (e.g. a closed/endorheic basin
    with no NWM reservoirs or gages), which leaves poi-derived columns like
    pois.id/nex_id or hydrolocations.id/nex_id entirely NULL -- that's a
    property of the VPU's data, not a naming-convention defect, so those
    cases are skipped rather than failed.
    """
    if not table_exists(pipeline_gpkg, layer):
        pytest.fail(f"layer '{layer}' does not exist in the pipeline output")

    if count_non_null(pipeline_gpkg, layer, column) == 0:
        pytest.skip(
            f"{layer}.{column} has no non-null values in the pipeline output for this VPU "
            "(e.g. no POIs assigned); naming convention can't be validated with no data"
        )

    ref_prefixes = get_id_prefixes(reference_gpkg, layer, column)
    pipe_prefixes = get_id_prefixes(pipeline_gpkg, layer, column)

    assert ref_prefixes, (
        f"no prefixed id values found for {layer}.{column} in the reference file; "
        "check that this column is expected to use a prefix convention"
    )
    assert pipe_prefixes, (
        f"no prefixed id values found for {layer}.{column} in the pipeline output "
        f"(expected prefixes like {sorted(ref_prefixes)})"
    )
    unexpected = pipe_prefixes - ref_prefixes
    assert not unexpected, (
        f"{layer}.{column} in the pipeline output uses unexpected id prefixes {sorted(unexpected)}; "
        f"reference file only uses prefixes {sorted(ref_prefixes)}"
    )
