"""
Render a map of the features that changed in one hydrofabric layer.

Every feature of the reference layer is drawn in grey. Features that differ
between the two files (modified, added, or removed) are drawn on top in blue,
using the new geometry where one exists.

What is drawn next to the overview map depends on how many features changed:

  * Few changes (at most MAX_ZOOM_FEATURES) in a few separate areas: a zoomed
    panel for each area, since a handful of features is otherwise invisible at
    the scale of a whole VPU. Nearby changes share a panel.
  * Few changes spread over many areas: the overview alone.
  * Many changes: a density map showing where the changes are concentrated,
    plus zoomed "hotspot" panels when most of the changes are concentrated in
    a few places.

This module only draws; deciding what differs is done by
compare_hydrofabric.py, whose per-layer result supplies the changed keys.
"""

from collections import Counter
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

GREY = "#9a9a9a"
BLUE = "#1f5fd1"

# Lighter grey for polygon outlines, which are so dense that the default grey
# would hide the changed polygons.
POLYGON_GREY = "#b0b0b0"

# Layers with more changed features than this skip the per-feature zoom
# panels and use the density map instead.
MAX_ZOOM_FEATURES = 50

# Per-feature zoom panels are only drawn when the changes fall into at most
# this many separate areas.
MAX_ZOOM_PANELS = 4

# A zoomed panel shows this many times the feature's own extent, so the
# surrounding (grey) network gives context.
ZOOM_CONTEXT_FACTOR = 2.0

# Smallest zoom window, as a fraction of the layer's full extent. Used for
# points and other features with no meaningful size of their own.
MIN_ZOOM_FRACTION = 0.005

# Hotspots: the layer is divided into a HOTSPOT_GRID x HOTSPOT_GRID grid, and a
# cell is "hot" if it holds at least HOTSPOT_MIN_SHARE of all changes. Touching
# hot cells form one hotspot. Hotspot panels are only drawn if the largest
# hotspots (at most MAX_HOTSPOT_PANELS) together hold at least
# HOTSPOT_MIN_TOTAL_SHARE of all changes; otherwise the changes are spread out
# and the density map alone describes them.
HOTSPOT_GRID = 20
HOTSPOT_MIN_SHARE = 0.05
HOTSPOT_MIN_TOTAL_SHARE = 0.5
MAX_HOTSPOT_PANELS = 4

# Number of hexagons across the density map.
DENSITY_GRIDSIZE = 22


def changed_feature_keys(layer_result: dict) -> list:
    """List the key of every feature that differs in any way, without duplicates."""
    keys = [d["key"] for d in layer_result["attribute_diffs"]]
    keys += [d["key"] for d in layer_result["geometry_diffs"]]
    keys += layer_result["missing_in_local"]
    keys += layer_result["missing_in_reference"]
    return list(dict.fromkeys(keys))


def is_polygonal(gdf) -> bool:
    return bool(gdf.geom_type.isin(["Polygon", "MultiPolygon"]).all())


def select_changed_features(local_by_key, reference_by_key, keys: list):
    """Collect the geometry of each changed feature, preferring the new (local)
    version and falling back to the reference version for removed features.
    """
    local_keys = [k for k in keys if k in local_by_key.index]
    removed_keys = [k for k in keys if k not in local_by_key.index and k in reference_by_key.index]
    rows = pd.concat([local_by_key.loc[local_keys], reference_by_key.loc[removed_keys]])
    changed = gpd.GeoDataFrame(rows, geometry="geometry", crs=reference_by_key.crs)
    return changed[~changed.geometry.isna() & ~changed.geometry.is_empty]


def draw_features(ax, base, changed, polygons: bool, zoomed: bool) -> None:
    """Draw the grey reference features, then the blue changed features on top."""
    if polygons:
        grey_width, blue_width = (0.6, 1.5) if zoomed else (0.2, 1.0)
        if len(base):
            base.boundary.plot(ax=ax, color=POLYGON_GREY, linewidth=grey_width)
        if len(changed):
            changed.plot(ax=ax, facecolor=BLUE, alpha=0.9, edgecolor=BLUE, linewidth=blue_width)
        return

    grey_width, blue_width = (0.8, 2.0) if zoomed else (0.3, 1.2)
    marker_grey, marker_blue = (8, 30) if zoomed else (2, 10)
    if len(base):
        base.plot(ax=ax, color=GREY, linewidth=grey_width, markersize=marker_grey)
    if len(changed):
        changed.plot(ax=ax, color=BLUE, linewidth=blue_width, markersize=marker_blue)


def square_window(minx, miny, maxx, maxy, min_size: float) -> tuple:
    """Return a square window centered on the given bounds, at least `min_size` wide."""
    size = max(maxx - minx, maxy - miny, min_size)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    return cx - size / 2, cy - size / 2, cx + size / 2, cy + size / 2


def windows_overlap(a: tuple, b: tuple) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def zoom_clusters(changed, full_bounds) -> list:
    """Group changed features into zoom windows.

    Each feature gets a window around itself (with some surrounding context);
    windows that overlap are merged, so features that changed in the same area
    share one panel. Only meant for a small number of features: with many,
    merged windows keep absorbing their neighbors until they cover the map.
    Returns a list of {"window": (xmin, ymin, xmax, ymax), "keys": [...]}.
    """
    full_size = max(full_bounds[2] - full_bounds[0], full_bounds[3] - full_bounds[1])
    min_size = full_size * MIN_ZOOM_FRACTION

    clusters = []
    for key, geometry in zip(changed.index, changed.geometry):
        minx, miny, maxx, maxy = geometry.bounds
        size = max(maxx - minx, maxy - miny, min_size) * ZOOM_CONTEXT_FACTOR
        window = square_window(minx, miny, maxx, maxy, size)
        clusters.append({"window": window, "keys": [key]})

    merged = True
    while merged:
        merged = False
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                if windows_overlap(clusters[i]["window"], clusters[j]["window"]):
                    a, b = clusters[i]["window"], clusters[j]["window"]
                    union = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
                    clusters[i] = {"window": square_window(*union, min_size), "keys": clusters[i]["keys"] + clusters[j]["keys"]}
                    del clusters[j]
                    merged = True
                    break
            if merged:
                break
    return clusters


def touching_groups(cells: set) -> list:
    """Split grid cells into groups of cells that touch (including diagonally)."""
    groups, seen = [], set()
    for start in sorted(cells):
        if start in seen:
            continue
        seen.add(start)
        stack, group = [start], []
        while stack:
            cx, cy = stack.pop()
            group.append((cx, cy))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    neighbor = (cx + dx, cy + dy)
                    if neighbor in cells and neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
        groups.append(group)
    return groups


def hotspot_windows(changed, full_bounds) -> list:
    """Find the few areas holding most of the changes, as square zoom windows.

    Returns an empty list when the changes are spread out rather than
    concentrated (see HOTSPOT_MIN_TOTAL_SHARE).
    """
    minx, miny, maxx, maxy = full_bounds
    cell = max(maxx - minx, maxy - miny) / HOTSPOT_GRID
    points = changed.geometry.representative_point()
    ix = np.clip(((points.x - minx) // cell).astype(int), 0, HOTSPOT_GRID - 1)
    iy = np.clip(((points.y - miny) // cell).astype(int), 0, HOTSPOT_GRID - 1)
    counts = Counter(zip(ix, iy))

    total = len(changed)
    hot_cells = {c for c, n in counts.items() if n >= HOTSPOT_MIN_SHARE * total}

    hotspots = []
    for group in touching_groups(hot_cells):
        xs, ys = [c[0] for c in group], [c[1] for c in group]
        # Pad by a quarter cell so features on the edge are not cut off.
        pad = cell * 0.25
        window = square_window(
            minx + min(xs) * cell - pad,
            miny + min(ys) * cell - pad,
            minx + (max(xs) + 1) * cell + pad,
            miny + (max(ys) + 1) * cell + pad,
            cell,
        )
        hotspots.append({"window": window, "count": sum(counts[c] for c in group)})

    hotspots = sorted(hotspots, key=lambda h: -h["count"])[:MAX_HOTSPOT_PANELS]
    if sum(h["count"] for h in hotspots) < HOTSPOT_MIN_TOTAL_SHARE * total:
        return []
    return hotspots


def add_zoom_panel(fig, spec, overview, window, base, changed, polygons, title_for_count, number=None):
    """Add a zoomed panel for `window`, and mark that window on the overview."""
    from matplotlib.patches import Rectangle

    xmin, ymin, xmax, ymax = window
    area = shapely.box(xmin, ymin, xmax, ymax)
    nearby = base.iloc[base.sindex.query(area, predicate="intersects")]
    nearby_changed = changed.iloc[changed.sindex.query(area, predicate="intersects")]

    panel = fig.add_subplot(spec)
    draw_features(panel, nearby, nearby_changed, polygons, zoomed=True)
    panel.set_xlim(xmin, xmax)
    panel.set_ylim(ymin, ymax)
    panel.set_aspect("equal", adjustable="box")
    panel.set_title(title_for_count(len(nearby_changed)), fontsize=9)
    panel.set_xticks([])
    panel.set_yticks([])

    overview.add_patch(
        Rectangle((xmin, ymin), xmax - xmin, ymax - ymin, fill=False, edgecolor="black", linestyle="--", linewidth=0.8)
    )
    if number is not None:
        overview.annotate(str(number), (xmin, ymax), fontsize=9, weight="bold")


def draw_density(ax, base, changed, polygons: bool, full_bounds, fig) -> None:
    """Draw a hexagon map of how many changed features fall in each area."""
    minx, miny, maxx, maxy = full_bounds
    if polygons:
        base.boundary.plot(ax=ax, color="#e2e2e2", linewidth=0.2)
    else:
        base.plot(ax=ax, color="#e2e2e2", linewidth=0.2, markersize=1)

    points = changed.geometry.representative_point()
    hexes = ax.hexbin(
        points.x, points.y, gridsize=DENSITY_GRIDSIZE, mincnt=1, cmap="Blues", extent=(minx, maxx, miny, maxy)
    )
    fig.colorbar(hexes, ax=ax, shrink=0.6, label="Changed features per cell")
    ax.set_title("Where the changes are concentrated")
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])


def render_changed_features(
    local_gdf,
    reference_gdf,
    key_columns: list,
    changed_keys: list,
    layer: str,
    out_path: Path,
    label_for_key,
) -> int:
    """Draw one layer's changed features to a PNG and return how many were drawn.

    `label_for_key` turns a feature key into the text shown above a zoomed panel.
    """
    # Imported here so the comparison still runs where matplotlib is absent.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D

    local_by_key = local_gdf.set_index(key_columns)
    reference_by_key = reference_gdf.set_index(key_columns)
    changed = select_changed_features(local_by_key, reference_by_key, changed_keys)
    if changed.empty:
        return 0

    polygons = is_polygonal(reference_gdf)
    full_bounds = reference_gdf.total_bounds

    # Decide what to draw next to the overview.
    clusters, hotspots, show_density = [], [], False
    if len(changed) <= MAX_ZOOM_FEATURES:
        found = zoom_clusters(changed, full_bounds)
        if len(found) <= MAX_ZOOM_PANELS:
            clusters = found
    else:
        show_density = True
        hotspots = hotspot_windows(changed, full_bounds)

    if show_density and hotspots:
        fig = plt.figure(figsize=(16, 10))
        grid = fig.add_gridspec(1 + len(hotspots), 2, width_ratios=[2, 1], height_ratios=[2] + [1] * len(hotspots))
        overview = fig.add_subplot(grid[:, 0])
    elif show_density:
        fig = plt.figure(figsize=(16, 8))
        grid = fig.add_gridspec(1, 2)
        overview = fig.add_subplot(grid[0, 0])
    elif clusters:
        fig = plt.figure(figsize=(14, 8))
        grid = fig.add_gridspec(len(clusters), 2, width_ratios=[2, 1])
        overview = fig.add_subplot(grid[:, 0])
    else:
        fig = plt.figure(figsize=(9, 8))
        grid = fig.add_gridspec(1, 1)
        overview = fig.add_subplot(grid[0, 0])

    draw_features(overview, reference_gdf, changed, polygons, zoomed=False)
    overview.set_title(f"{layer}: {len(changed)} changed of {len(reference_gdf)} features")

    for row, cluster in enumerate(clusters):
        keys = cluster["keys"]
        title = label_for_key(keys[0]) if len(keys) == 1 else f"{len(keys)} changed features"
        add_zoom_panel(fig, grid[row, 1], overview, cluster["window"], reference_gdf, changed, polygons, lambda n, t=title: t)

    if show_density:
        draw_density(fig.add_subplot(grid[0, 1]), reference_gdf, changed, polygons, full_bounds, fig)
        for row, hotspot in enumerate(hotspots, start=1):
            add_zoom_panel(
                fig,
                grid[row, 1],
                overview,
                hotspot["window"],
                reference_gdf,
                changed,
                polygons,
                lambda n, i=row: f"Hotspot {i}: {n} changed in this area",
                number=row,
            )

    overview.set_aspect("equal")
    overview.set_xticks([])
    overview.set_yticks([])
    overview.legend(
        handles=[
            Line2D([0], [0], color=POLYGON_GREY if polygons else GREY, linewidth=2, label="Reference feature"),
            Line2D([0], [0], color=BLUE, linewidth=2, label="Changed feature"),
        ],
        loc="lower left",
    )

    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return len(changed)
