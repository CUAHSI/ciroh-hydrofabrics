"""Render simulated change scenarios to preview the changed-feature maps.

Simulates changes (few, clustered, scattered, thousands) on the cached VPU 16
reference hydrofabric for the `flowpaths` and `divides` layers and writes one
PNG per scenario to this directory (examples/).

Run from validation/hf-comparison after a comparison has cached the reference:
    python examples/run_render_examples.py
"""
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np

TOOL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOL_DIR))
import render_changes  # noqa: E402

CACHE = TOOL_DIR / ".cache" / "reference-hydrofabric-vpu-16.gpkg"
OUT_DIR = Path(__file__).resolve().parent
rng = np.random.default_rng(7)
LAYERS = {"flowpaths": "id", "divides": "divide_id"}


def nearest(xy, centre, n):
    """Indices of the n features closest to a centre feature."""
    return list(np.argsort(np.hypot(*(xy - xy[centre]).T))[:n])


def scenarios(gdf):
    pts = gdf.geometry.representative_point()
    xy = np.column_stack([pts.x, pts.y])
    pick = lambda n: list(rng.choice(len(gdf), n, replace=False))  # noqa: E731
    centres = pick(5)
    return {
        "1_few_scattered_4": pick(4),
        "2_one_small_cluster_12": nearest(xy, centres[0], 12),
        "3_few_but_many_areas_10": pick(10),
        "4_many_scattered_300": pick(300),
        "5_many_clustered_3_hotspots": sorted(
            set(sum([nearest(xy, c, 90) for c in centres[:3]], []) + pick(30))
        ),
        "6_very_many_2000": pick(2000),
    }


for layer, key in LAYERS.items():
    gdf = gpd.read_file(CACHE, layer=layer)
    for name, idx in scenarios(gdf).items():
        keys = list(gdf.iloc[sorted(set(idx))][key])
        out = OUT_DIR / f"{layer}_{name}.png"
        n = render_changes.render_changed_features(gdf, gdf, [key], keys, layer, out, lambda k: f"{key} {k}")
        print(f"{layer} {name}: {n} drawn")
