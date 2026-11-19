# `geometry` check

The `geometry` check measures the shapes in a GeoPackage: missing, empty,
invalid and repeated geometries in every spatial layer, and the overlaps and
gaps between divide polygons.

It covers **every spatial layer in the file, including extra layers the
Data Model does not name**, for both output kinds. Attribute-only tables are
excluded. If the file has no spatial layers, `no_applicable_checks` is `1`.
Findings are observations, not necessarily defects.

## Per-layer metrics

Each is named `<metric>.<layer>`, for example `invalid_geometries.nexus`, and is
a ratcheted count: PASS when `value <= recorded count`, FAIL otherwise.

| Metric | What it counts |
| --- | --- |
| `null_geometries` | Rows whose geometry is NULL. |
| `empty_geometries` | Rows whose geometry is present but empty. Kept separate from invalid geometries. |
| `invalid_geometries` | Non-empty geometries that are not valid under the OGC Simple Features rules (for example a self-intersecting polygon). |
| `duplicate_geometries` | Extra rows in each group of equal geometries within the layer: a group of three equal shapes adds `2`. |

How equality is decided:

- Equality is 2D and topological for **valid** geometries, so vertex order,
  starting vertex and redundant vertices do not matter. Direction is not
  preserved: a flowpath and its reverse are equal.
- For **invalid** geometries, topological equality is undefined, so only exact
  normalized coordinate repeats (including a reversed copy) are counted.
  Other equivalent invalid shapes can be missed.
- NULL geometries are excluded. All empty geometries are equal to each other,
  so `n` empties add `n - 1`.

## Duplicate geometries in official NextGen `hydrolocations`

`duplicate_geometries.hydrolocations` is nonzero in all 21 official NextGen
v2.2 VPUs recorded in
[`counts.yaml`](../../validation/consistency/counts.yaml), from 661 in VPU 06 to
5,772 in VPU 17. **In the one VPU inspected (03S), 881 of the 889 extra rows are
legitimate: the layer has one row per referenced location, and a point of
interest (POI) can have several, all at one point. The other 8 are exact repeated
rows, a minor data defect in the official product.**

The metric counts extra rows at a point, so a POI that has a `huc12` row, a
`gages` row and a `LAKEPARM` row adds `2`, even though each row is a different
referenced location. It
cannot tell that case from a repeated row.

### Why the points are shared

`hydrolocations` has one row per referenced location, not one per place. Each
row carries a `poi_id`, the flowpath (`id`) and nexus (`nex_id`) of that POI, and
the referenced location in `hl_reference`, `hl_link` and `hl_uri` (for example
`gages-02234500` or `huc12-030801011303`). One POI can have several referenced
locations, and every row of a POI has the same point. For example, POI 2656 in
VPU 03S has four rows, all at the point of `nex-420410` on `wb-420409`:
`huc12-030801011303` and `gages-02234500` and `te-620` (`ref-fab`), and
`LAKEPARM-10996865` (`NOAA-OWP`).

Observed read-only in `tests/v2.2/assets/ngen-hydrofabric-vpu-03S.gpkg`
(SQLite and geopandas; equal points are equal geometry values):

| Observation | VPU 03S |
| --- | --- |
| `hydrolocations` rows | 3,159 `POINT`s in EPSG:5070, none NULL or empty |
| Distinct points | 2,270, so **889** extra rows, equal to the recorded count |
| Distinct `poi_id` (equal to the rows of `pois`) | 2,286 |
| Extra rows inside a POI (3,159 - 2,286) | 873 |
| Extra POIs on a point another POI already uses (2,286 - 2,270) | 16 |
| Rows per POI | 1 for 1,614 POIs; 2 for 539; 3 for 97; 4 for 23; 5 for 7; 6 for 3; 9 for 1; 11 for 2 |
| POIs on more than one point, or on more than one `nex_id` | 0 |
| Points with more than one row | 683 of 2,270 (30%), holding 1,572 of 3,159 rows (50%) |
| Rows at those 683 points | 2 at 545 points, 3 at 102, 4 at 23, 5 at 7, 6 at 3, 9 at 1, 11 at 2 |
| Shared points with one `nex_id` | all 683 |
| Shared points with rows on two flowpath `id`s | 56 (132 rows) |
| Extra rows that add a new `hl_uri` to their point | 881 of the 889 |
| Rows where `geom` differs from (`hl_x`, `hl_y`) by more than 1e-6 m | 0 |
| Rows whose point is exactly the point of the nexus named in `nex_id` | 3,088 of 3,159; the other 71 are 33 m to 4.7 km away |

So 873 + 16 = 889. The 16 are POIs that sit on the same point as a different POI
on the same nexus (14 of the 16 on different flowpaths). At shared points, the
rows by `hl_reference` are `huc12` 558, `gages` 205, `wbout` 176, `coastal` 170,
`LAKEPARM` 161, `nid` 117, `wbin` 67, `resops` 41 and `term` 37, with 21 `te`
and 19 rows of five other values. Among the 545 points with exactly two rows,
the commonest pairs are `huc12` + `huc12` (123), `LAKEPARM` + `wbout` (118),
`gages` + `huc12` (91) and `coastal` + `coastal` (47). Both sources take part:
`hl_source` is `ref-fab` only at 435 shared points, `NOAA-OWP` only at 62 and
both at 186. This repository does not define the `hl_reference` values, so they
are named here, not interpreted.

### The eight repeated rows are a defect

Four groups of rows in VPU 03S repeat every column except `fid`. Each group is
inside one POI, and together they add 8 of the 889 extra rows (under 1%):

| `hl_uri` | `poi_id` | `nex_id` | Rows | Extra rows |
| --- | --- | --- | --- | --- |
| `reservoir-222` | 2664 | `nex-420367` | 4 | 3 |
| `reservoir-462` | 5128 | `nex-421372` | 4 | 3 |
| `wbin-295793` | 13520 | `nex-421207` | 2 | 1 |
| `wbin-306146` | 73345 | `nex-421378` | 2 | 1 |

They carry no information that another row does not, so they are a minor defect
in the official product. No other check finds them: no primary key is
established for NextGen `hydrolocations` (see [`network`](network.md)), so they
appear only inside this count.

To split a GeoPackage's count into the two cases, compare distinct points with
distinct point-and-`hl_uri` pairs. In VPU 03S the first is 889 and the second 8:

```sql
SELECT COUNT(*) - COUNT(DISTINCT geom) AS extra_rows_at_a_point,
       COUNT(*) - (SELECT COUNT(*)
                   FROM (SELECT DISTINCT geom, hl_uri FROM hydrolocations))
         AS repeated_rows
FROM hydrolocations;
```

The second value equals the number of exactly repeated rows only if no point
holds two rows with the same `hl_uri` and different other columns; none does in
VPU 03S.

### Limits of this evidence

Only VPU 03S was inspected. The other 20 NextGen VPUs are known only through
their recorded counts, so the composition above is not verified for them. Their
rows have the same structure, so the same cause is expected (an inference), but a
VPU may hold more repeated rows. Reference VPU 16 also records a nonzero
`duplicate_geometries.hydrolocations` (1,109); no Reference GeoPackage was
inspected, so that count is not explained here. The metric and its recorded
counts are unchanged: a Build may carry the official count forward but must not
exceed it.

## Divide topology metrics

Topology is calculated on the Data Model's `topology_layer` (`divides` for
v2.2). All six metrics below are ratcheted; the two INFO values are not.

| Metric | What it measures |
| --- | --- |
| `divide_overlaps.count` | The number of **unordered pairs** of divides whose intersection area is **strictly greater** than the overlap threshold. Containment and equal polygons count. The area of all disconnected pieces for one pair is combined. |
| `divide_overlaps.total_area_m2` | The summed intersection area of those pairs, in m². |
| `divide_overlaps.largest_area_m2` | The largest single-pair intersection area, in m². |
| `divide_gaps.count` | The number of uncovered interior components strictly larger than the gap threshold. |
| `divide_gaps.total_area_m2` | Their summed area, in m². |
| `divide_gaps.largest_area_m2` | The largest, in m². |
| `overlap_min_area_m2` (INFO) | The overlap threshold used in this run. |
| `divide_union_area_m2` (INFO) | The area of the union of all divides, in m². |

An area covered by three or more divides contributes to several pairs, so
`divide_overlaps.total_area_m2` is **not** the area of unique overlapped ground.

A **gap** is a hole in the union of the divides, with islands inside the hole
subtracted. Only interior holes are measured: the outer edge of the VPU, and
any gap connected to it, is not checked because there is no boundary layer to
compare with. A lake or other intended exclusion can appear as an interior gap.

### Thresholds and conventions

| Item | v2.2 value | Source and scope |
| --- | --- | --- |
| Overlap minimum area | 100 m², strictly greater | Data Model specific (v2.2), `checks.geometry.overlap_min_area_m2`. A run can override it with `geometry.overlap_min_area_m2` in `checks.yaml` (a finite nonnegative number), which applies to every Data Model in that run. The value used is printed as the INFO line `overlap_min_area_m2`. |
| Gap minimum area | 100 m², strictly greater | Data Model specific (v2.2), `checks.geometry.gap_min_area_m2`. It has **no** `checks.yaml` override. |
| Topology layer | `divides` | Data Model specific (v2.2), `checks.geometry.topology_layer`. |
| Required CRS | EPSG:5070 (a projected CRS in metres) | Data Model specific (v2.2): the registration of the topology layer. |
| Comparison with the threshold | strictly greater than | Generic: the implementation. |

Areas are in the CRS's units; the check does not verify that they are metres
and does not reproject. Changing the overlap threshold changes the meaning of
all three overlap metrics, so regenerate recorded counts with the same
threshold you check against.

### Repair and incomplete topology

Invalid divides are repaired in memory (`make_valid`) before topology is
calculated; polygonal parts are kept if repair also produces lines. The
`invalid_geometries` count still describes the **original** geometries, and the
input file is not modified.

Topology is **incomplete** (the run exits `2` and **no overlap, gap or union
values are reported**) when:

- a divide geometry is NULL, empty or not polygonal, or cannot be repaired;
- the divides layer's CRS is not the registered one (or an equivalent
  definition);
- a geometry operation fails.

The other geometry metrics are still printed, including the INFO line
`overlap_min_area_m2`. If the divides layer is absent,
the topology metrics are omitted and `schema` reports the missing layer; a
non-spatial divides table makes the topology incomplete. The layer is loaded
into memory, and the union can be expensive for large Builds.

## Pass and fail

| Metric | A value of `0` means |
| --- | --- |
| `null_geometries.*`, `empty_geometries.*` | every feature has a shape |
| `invalid_geometries.*` | every shape is valid |
| `duplicate_geometries.*` | no repeated shape |
| `divide_overlaps.*` | no pair overlaps by more than the threshold |
| `divide_gaps.*` | no interior gap larger than the threshold |

Every metric in this table is PASS when `value <= recorded count` and FAIL when
`value > recorded count`. A metric with no recorded count is held to `0`. The
`_m2` area values compare as numbers, so `200.0 > 0` is a FAIL.

`overlap_min_area_m2` and `divide_union_area_m2` are **always INFO**: context
only, never gated, and never recorded. When topology is incomplete,
`divide_union_area_m2` is not printed, but `overlap_min_area_m2` still is.
`no_applicable_checks` (`1` when the file has no spatial layers) is ratcheted
like the others.

## Worked examples

Every example is a NextGen `divides` layer in EPSG:5070, run with no recorded
counts and the check advisory. Only the relevant report lines are shown, with
`divide_union_area_m2` as the INFO line.

### Overlaps above and below the threshold

| Input (rectangles `box(xmin, ymin, xmax, ymax)`, metres) | Intersection |
| --- | --- |
| `box(0, 0, 10, 30)` and `box(0, 10, 10, 40)` | 10 × 20 = **200 m²** |
| `box(0, 0, 10, 20)` and `box(0, 10, 10, 30)` | 10 × 10 = **100 m²** |
| `box(0, 0, 10, 20)` and `box(0, 15, 10, 35)` | 10 × 5 = **50 m²** |

The first pair is above the threshold:

```text
geometry | divide_overlaps.count | 1 | 0 | FAIL | advisory
geometry | divide_overlaps.total_area_m2 | 200.0 | 0 | FAIL | advisory
geometry | divide_overlaps.largest_area_m2 | 200.0 | 0 | FAIL | advisory
geometry | overlap_min_area_m2 | 100.0 | - | INFO | advisory
geometry | divide_union_area_m2 | 400.0 | - | INFO | advisory
```

The second pair overlaps by exactly 100 m², which is not **strictly greater**
than the threshold, and the third by 50 m²; both report
`divide_overlaps.count | 0 | 0 | PASS`, with union areas of 300 and 350.

### A gap

Four rectangles surround a hole:

- `box(0, 0, 30, 10)` below;
- `box(0, 10, 10, 30)` on the left;
- `box(20, 10, 30, 30)` on the right;
- `box(0, 30, 30, 40)` above.

The hole is `x` 10 to 20 and `y` 10 to 30, which is 10 × 20 = 200 m²:

```text
geometry | divide_gaps.count | 1 | 0 | FAIL | advisory
geometry | divide_gaps.total_area_m2 | 200.0 | 0 | FAIL | advisory
geometry | divide_gaps.largest_area_m2 | 200.0 | 0 | FAIL | advisory
geometry | divide_union_area_m2 | 1000.0 | - | INFO | advisory
```

Moving the two side rectangles so the hole is 5 × 20 = 100 m² reports a gap
count of `0` (PASS), because 100 is not strictly greater than the threshold; the
union area is then 900.

### Duplicate and invalid geometries

Two identical `box(0, 0, 20, 20)` divides report:

```text
geometry | duplicate_geometries.divides | 1 | 0 | FAIL | advisory
geometry | divide_overlaps.count | 1 | 0 | FAIL | advisory
geometry | divide_overlaps.total_area_m2 | 400.0 | 0 | FAIL | advisory
geometry | divide_overlaps.largest_area_m2 | 400.0 | 0 | FAIL | advisory
```

One extra row is a duplicate, and the two polygons overlap by their whole
400 m² area.

A single bow-tie polygon `(0,0) (10,10) (10,0) (0,10) (0,0)` is a
self-intersecting, invalid shape:

```text
geometry | invalid_geometries.divides | 1 | 0 | FAIL | advisory
geometry | divide_union_area_m2 | 50.0 | - | INFO | advisory
```

The repaired polygons have a union area of 50 m², which topology uses.

### An incomplete check

When one of two divides has a NULL geometry and `geometry` is blocking, the
report has `null_geometries.divides | 1 | 0 | FAIL | blocking`, but no
overlap, gap or union values. The command prints
`check geometry: divides topology incomplete: null or empty divide geometry`
and exits `2`, because the topology could not be measured; see
[reading a report](reading-a-report.md#exit-statuses).
