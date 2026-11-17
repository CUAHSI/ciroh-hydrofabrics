"""Small v2.2 GeoPackages with a mix of passing and failing checks.

These fixtures back the golden regression tests: they only need to exercise
the schema, network, geometry and attribute checks for each output kind, not
to be realistic hydrofabrics.
"""

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely.geometry import LineString, Point, box

CRS = "EPSG:5070"


def _spatial(path, layer, data, geometry):
    gpd.GeoDataFrame(data, geometry=geometry, crs=CRS).to_file(path, layer=layer, engine="pyogrio")


def _tabular(path, layer, data):
    # Attribute tables have no geometry column and no spatial registration.
    pyogrio.write_dataframe(pd.DataFrame(data), path, layer=layer, geometry_type=None)


def write_ngen(path):
    """NextGen build: overlapping divides, a dangling link and an out-of-range slope."""
    _spatial(path, "divides", {
        "divide_id": ["cat-1", "cat-2"], "toid": ["nex-1", "nex-2"], "id": ["wb-1", "wb-2"],
        "areasqkm": [1.0, 2.0], "has_flowline": [1, 1], "vpuid": ["01", "01"],
    }, [box(0, 0, 20, 10), box(5, 0, 25, 10)])
    _spatial(path, "flowpaths", {
        "id": ["wb-1", "wb-2"], "toid": ["nex-1", "nex-missing"], "divide_id": ["cat-1", "cat-2"],
        "hydroseq": [20.0, 10.0], "areasqkm": [1.0, 0.0], "has_divide": [1, 0], "lengthkm": [1.0, 2.0],
        "vpuid": ["01", "01"],
    }, [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])])
    _spatial(path, "nexus", {
        "id": ["nex-1", "nex-2"], "toid": ["wb-2", "wb-0"], "type": ["nexus", "terminal"],
        "vpuid": ["01", "01"],
    }, [Point(1, 1), Point(2, 2)])
    _tabular(path, "network", {
        "id": ["wb-1", "nex-1", "wb-2"], "toid": ["nex-1", "wb-2", "wb-0"],
        "hydroseq": [20.0, None, 10.0], "type": ["nexus", "nexus", "terminal"],
        "divide_id": ["cat-1", None, "cat-2"], "vpuid": ["01", "01", "01"],
    })
    _tabular(path, "divide-attributes", {
        "divide_id": ["cat-1", "cat-2"], "mean.slope": [12.0, 95.0], "mean.impervious": [10.0, 50.0],
        "vpuid": ["01", "01"],
    })


def write_reference(path):
    """Reference build: a routing cycle, out-of-order sequences and a divide gap."""
    _spatial(path, "divides", {
        "divide_id": [1.0, 2.0, 3.0, 4.0], "id": [1.0, 2.0, 3.0, 4.0], "areasqkm": [1.0, 2.0, 3.0, 4.0],
        "has_flowline": [1, 1, 1, 1], "vpuid": ["01"] * 4,
        # A ring of four divides encloses a 20 m x 20 m gap.
    }, [box(0, 0, 40, 10), box(0, 30, 40, 40), box(0, 10, 10, 30), box(30, 10, 40, 30)])
    _spatial(path, "flowpaths", {
        "id": [1.0, 2.0], "toid": [2.0, 1.0], "divide_id": [1.0, 2.0],
        "hydroseq": [10.0, 20.0], "dnhydroseq": [10.0, 5.0], "has_divide": [1, 1],
        "lengthkm": [1.0, 2.0], "areasqkm": [1.0, 2.0], "vpuid": ["01", "01"],
    }, [LineString([(0, 0), (1, 1)]), LineString([(1, 1), (2, 2)])])
    _tabular(path, "network", {
        "id": [1.0, 2.0], "toid": [2.0, 0.0], "topo": ["fl-fl", "fl-fl"],
        "hydroseq": [20.0, 10.0], "dnhydroseq": [10.0, 0.0],
    })
