"""Geometry Consistency Checks for v2.2 GeoPackages."""

import math
import sqlite3
from contextlib import closing

import pyogrio
import shapely
from pyproj import CRS
from shapely import STRtree
from shapely.geometry import MultiPolygon, Polygon


def _invalid_duplicates(geometries):
    """Group exact normalized representations in either coordinate direction."""
    parents = list(range(len(geometries)))
    seen = {}

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    # Invalid rings can normalize differently when reversed or rotated. Keeping
    # both representations and merging matching groups avoids choosing a key
    # that depends on the original ring orientation.
    for index, geometry in enumerate(geometries):
        for variant in (geometry, shapely.reverse(geometry)):
            key = shapely.to_wkb(shapely.normalize(variant), output_dimension=2)
            if key in seen:
                parents[root(index)] = root(seen[key])
            else:
                seen[key] = index
    return len(geometries) - len({root(index) for index in range(len(geometries))})


def _duplicates(geometries):
    """Count extra rows in each group of equal geometries."""
    non_null = [geometry for geometry in geometries if geometry is not None]
    non_empty = [geometry for geometry in non_null if not geometry.is_empty]
    usable = [geometry for geometry in non_empty if geometry.is_valid]
    # Topological equality is undefined for invalid geometries. Normalized WKB
    # still detects exact repeats, including NaN coordinates excluded by STRtree.
    invalid = [geometry for geometry in non_empty if not geometry.is_valid]
    tree = STRtree(usable)
    # Empty geometries are topologically equal but cannot be indexed by STRtree.
    duplicates = max(0, len(non_null) - len(non_empty) - 1) + _invalid_duplicates(invalid)
    for index, geometry in enumerate(usable):
        # An equal geometry necessarily has the same envelope; spatial indexing
        # avoids comparing every pair in a large layer.
        for candidate in tree.query(geometry):
            if candidate < index and geometry.equals(usable[candidate]):
                duplicates += 1
                break
    return duplicates


def _layer_metrics(layer, geometries):
    non_null = [geometry for geometry in geometries if geometry is not None]
    non_empty = [geometry for geometry in non_null if not geometry.is_empty]
    return {
        f"null_geometries.{layer}": len(geometries) - len(non_null),
        f"empty_geometries.{layer}": len(non_null) - len(non_empty),
        f"invalid_geometries.{layer}": sum(not geometry.is_valid for geometry in non_empty),
    }


def _correct_divides_crs(path, crs):
    """Require the v2.2 CRS registration and an equivalent CRS definition."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        registration = connection.execute(
            "SELECT c.srs_id, g.srs_id, s.organization, s.organization_coordsys_id, s.definition "
            "FROM gpkg_contents c JOIN gpkg_geometry_columns g ON c.table_name = g.table_name "
            "JOIN gpkg_spatial_ref_sys s ON g.srs_id = s.srs_id WHERE c.table_name = ?",
            ("divides",),
        ).fetchone()
    if registration is None or registration[:4] != (5070, 5070, "EPSG", 5070) or crs is None or not isinstance(registration[4], str):
        return False
    expected = CRS.from_epsg(5070)
    return CRS.from_user_input(crs).equals(expected) and CRS.from_wkt(registration[4]).equals(expected)


def _repair_divide(geometry):
    """Repair an invalid divide, retaining its polygonal area when possible."""
    if geometry.is_valid:
        return geometry
    repaired = shapely.make_valid(geometry)
    if repaired.geom_type != "GeometryCollection":
        return repaired
    # make_valid can retain collapsed edges as lines next to valid polygons.
    # These have no area and must not obscure the usable polygonal result.
    polygons = []
    parts = list(repaired.geoms)
    while parts:
        part = parts.pop()
        if part.geom_type in {"Polygon", "MultiPolygon"}:
            polygons.append(part)
        elif part.geom_type == "GeometryCollection":
            parts.extend(part.geoms)
    return shapely.union_all(polygons)


def _topology(divides, threshold):
    """Measure unordered overlaps and bounded uncovered holes in the union."""
    tree = STRtree(divides)
    overlap_count, overlap_total, overlap_max = 0, 0.0, 0.0
    for index, geometry in enumerate(divides):
        for candidate in tree.query(geometry, predicate="intersects"):
            if candidate <= index:
                continue
            area = geometry.intersection(divides[candidate]).area
            if area > threshold:
                overlap_count += 1
                overlap_total += area
                overlap_max = max(overlap_max, area)

    union = shapely.union_all(divides)
    # Remove island shells, not the entire island polygons. An island's own
    # holes are measured separately, avoiding double counting nested gaps.
    if isinstance(union, Polygon):
        polygons = [union]
    elif isinstance(union, MultiPolygon):
        polygons = list(union.geoms)
    elif union.is_empty:
        polygons = []
    else:
        raise ValueError("divide union is not polygonal")
    polygon_tree = STRtree(polygons)
    gap_areas = []
    for polygon in polygons:
        for ring in polygon.interiors:
            hole = Polygon(ring)
            islands = [Polygon(polygons[index].exterior)
                       for index in polygon_tree.query(hole, predicate="covers")]
            if islands:
                hole = hole.difference(shapely.union_all(islands))
            components = shapely.get_parts(hole)
            gap_areas.extend(part.area for part in components if isinstance(part, Polygon) and part.area > 100)
    return {
        "divide_overlaps.count": overlap_count,
        "divide_overlaps.total_area_m2": float(overlap_total),
        "divide_overlaps.largest_area_m2": float(overlap_max),
        "divide_gaps.count": len(gap_areas),
        "divide_gaps.total_area_m2": float(sum(gap_areas)),
        "divide_gaps.largest_area_m2": float(max(gap_areas, default=0)),
    }, {"divide_union_area_m2": float(union.area)}


def geometry(path, model, kind, *, overlap_min_area_m2=100):
    """Return geometry metrics, informational values and incomplete-check errors."""
    if model != "v2.2" or kind not in {"ngen", "reference"}:
        raise ValueError(f"no geometry checks for Data Model {model!r}, output kind {kind!r}")
    if type(overlap_min_area_m2) not in (int, float) or not math.isfinite(overlap_min_area_m2) or overlap_min_area_m2 < 0:
        raise ValueError("overlap_min_area_m2 must be a finite nonnegative number")
    metrics, informational, errors = {}, {"overlap_min_area_m2": float(overlap_min_area_m2)}, []
    layers = pyogrio.list_layers(path)
    spatial_layers = [name for name, geometry_type in layers if geometry_type is not None]
    if any(name == "divides" and geometry_type is None for name, geometry_type in layers):
        errors.append("divides topology incomplete: divides is not a spatial layer")
    for layer in spatial_layers:
        try:
            frame = pyogrio.read_dataframe(path, layer=layer, columns=[])
            geometries = list(frame.geometry)
            metrics.update(_layer_metrics(layer, geometries))
        except (RuntimeError, ValueError, shapely.GEOSException) as exc:
            errors.append(f"geometry checks incomplete for layer {layer!r}: {exc}")
            continue
        try:
            metrics[f"duplicate_geometries.{layer}"] = _duplicates(geometries)
        except shapely.GEOSException as exc:
            errors.append(f"duplicate geometry checks incomplete for layer {layer!r}: {exc}")
        if layer != "divides":
            continue
        try:
            correct_crs = _correct_divides_crs(path, frame.crs)
        except (sqlite3.Error, ValueError, RuntimeError) as exc:
            errors.append(f"divides topology incomplete: could not verify CRS: {exc}")
            continue
        if not correct_crs:
            errors.append("divides topology requires the registered v2.2 EPSG:5070 CRS")
            continue
        if any(geometry is None or geometry.is_empty for geometry in geometries):
            errors.append("divides topology incomplete: null or empty divide geometry")
            continue
        try:
            repaired = [_repair_divide(item) for item in geometries]
            if any(item.is_empty or item.geom_type not in {"Polygon", "MultiPolygon"} for item in repaired):
                errors.append("divides topology incomplete: unusable divide geometry after repair")
                continue
            topology, values = _topology(repaired, overlap_min_area_m2)
            if not all(math.isfinite(value) for value in (*topology.values(), *values.values())):
                errors.append("divides topology incomplete: non-finite area")
                continue
        except (ValueError, shapely.GEOSException) as exc:
            errors.append(f"divides topology incomplete: geometry operation failed: {exc}")
            continue
        metrics.update(topology)
        informational.update(values)
    if not spatial_layers:
        metrics["no_applicable_checks"] = 1
    return metrics, informational, errors
