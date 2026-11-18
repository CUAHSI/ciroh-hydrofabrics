# `schema` check

The `schema` check compares a GeoPackage's layers, columns, registration and
coordinate reference systems (CRS) with the Data Model's specification for the
file's output kind. It does not read any feature values except to test
identifier prefixes.

The specification is a checked-in JSON file, for v2.2
[`ngen.json`](../../validation/consistency/models/v2.2/ngen.json) or
[`reference.json`](../../validation/consistency/models/v2.2/reference.json); see
[the v2.2 Data Model](data-model-v2.2.md). It describes what was observed in
the official products, not an exhaustive standard. **Extra layers in the file
are allowed**: only layers the specification names are measured.

Every metric is a ratcheted count: it is a PASS when `value <= recorded count`
and a FAIL otherwise. This check has no INFO metrics.

## Per-layer metrics

These apply to each layer the specification names. Each metric name ends with
`.<layer>`, for example `missing_columns.nexus`.

| Metric | What it measures | Value | When the layer is missing |
| --- | --- | --- | --- |
| `missing_layer` | The specification names this layer but the file has no table of that name (looked up in `sqlite_master`). | `1` if missing, else `0` | The metric is `1`; the metrics below are omitted. |
| `missing_registration` | The table exists but is not registered in `gpkg_contents`. | `1` or `0` | n/a |
| `layer_type` | The registered `data_type` differs from the specification (`features` for spatial layers, `attributes` otherwise). Omitted if the layer is unregistered. | `1` or `0` | n/a |
| `contents_crs` | Spatial layers only: the `srs_id` in `gpkg_contents` differs from the specification (EPSG:5070 for v2.2). Omitted if unregistered. | `1` or `0` | n/a |
| `missing_columns` | Number of columns named in the specification and absent from the table. | count | n/a |
| `extra_columns` | Number of columns in the table and absent from the specification. | count | n/a |
| `column_order` | Among the columns present in **both** the table and the specification, the physical order differs. Missing or extra columns can still shift physical positions without changing this value. | `1` or `0` | n/a |
| `column_types` | Number of common columns, excluding `geom`, whose declared SQL type (the exact text of `PRAGMA table_info`, not a runtime storage class) differs. | count | n/a |

A dependent metric is omitted when its prerequisite is missing, so the
prerequisite reports the problem once. For example, a missing layer does not
also report `missing_columns` for every column.

## Per-spatial-layer metrics

These apply to layers the specification registers with geometry (see the table
below). They read `gpkg_geometry_columns` and `gpkg_spatial_ref_sys`, and
apply even to an empty layer.

| Metric | What it measures |
| --- | --- |
| `missing_geometry_registration` | `1` if the layer has no row in `gpkg_geometry_columns`. The metrics below are then omitted. |
| `geometry_column` | `1` if the registered geometry column name differs from the specification (`geom`). |
| `geometry_crs` | `1` if the registered `srs_id` differs from the specification. |
| `crs_authority` | `1` if the CRS authority and code (organization and coordinate-system ID) differ from the specification (EPSG and 5070). The full spatial-reference definition is **not** compared. |
| `geometry_type` | `1` if the registered geometry type differs from the specification. A specification type of `GEOMETRY` accepts any type; an empty layer may declare the generic `GEOMETRY`. |

## Identifier metrics

For each identifier column of the NextGen specification that lists observed
prefixes, the check reports two counts, named `<metric>.<layer>.<column>`:

| Metric | What it measures |
| --- | --- |
| `unobserved_id_prefixes` | The number of distinct prefixes in the column that are not in the specification's `observed_prefixes`. |
| `unprefixed_ids` | The number of non-null values with no prefix. |

A prefix is the text before the first `-`, provided that hyphen is not the
first character; for `wb-123` the prefix is `wb`. An all-null or absent column
is skipped, so the metric is omitted. **The observed prefixes are not an
exhaustive vocabulary.** A new prefix, such as `cnx` in a VPU that did not have
one before, may be legitimate; `unobserved_id_prefixes` is a comparison with
two source VPUs, so review a nonzero value before enabling a blocking gate.
Reference identifiers are numeric, so these two metrics do not apply to
`reference`.

## Layers in each v2.2 output kind

| Output kind | Spatial layers (geometry type, EPSG:5070) | Attribute layers |
| --- | --- | --- |
| `ngen` | `divides` (POLYGON), `flowpaths` (GEOMETRY), `hydrolocations` (POINT), `lakes` (POINT), `nexus` (POINT) | `divide-attributes`, `flowpath-attributes`, `flowpath-attributes-ml`, `network`, `pois` |
| `reference` | `divides` (POLYGON), `flowpaths` (LINESTRING), `hydrolocations` (POINT) | `network` |

**NextGen `hydrolocations` is a feature layer.** The official NextGen files
carry `hydrolocations` as a POINT feature layer in EPSG:5070 in all 21 VPUs,
as the specification describes. Counts recorded earlier from CONUS-scoped
files instead of the per-VPU products had `layer_type`, `contents_crs`,
`missing_columns` and `missing_geometry_registration` for it as `1`; they were
re-recorded from the per-VPU products in CAM-1605 and are now `0`.

## Pass and fail

| Metric | Passes when | Fails when |
| --- | --- | --- |
| Every metric above | The value is no greater than the recorded count (a missing count is `0`). | The value is greater than the recorded count. |

For example, the official Reference GeoPackages have no `hydrolocations` layer
in the recorded VPUs, so `missing_layer.hydrolocations: 1` is recorded. A
Reference Build that omits the layer passes at `1 <= 1`; one that includes it
reports `0` and also passes. The ratchet cannot tell an unchanged inherited
difference from a new one; see [reading a report](reading-a-report.md).

## When the check is incomplete

A file without the GeoPackage metadata the check queries (for example no
`gpkg_contents` table) cannot be inspected. The check raises an error and the
run exits `2`. A specification that is
missing, malformed or uses unsupported semantics stops the run with status `2`
before any file is read; there is no fallback to v2.2.

## Conventions and their source

| Convention | v2.2 value | Source |
| --- | --- | --- |
| Table and column names, declared types, column order | The layers and columns in `tables` | Data Model specific (v2.2): observed from the official NextGen VPU 03S and 16 and Reference VPU 16 GeoPackages. |
| Feature CRS | EPSG:5070 | Data Model specific (v2.2): the observed registration. |
| Identifier separator | `-` | Data Model specific (v2.2), `checks.schema.id_prefix_separator`. |
| Observed prefixes | e.g. `wb`, `cat`, `nex`, `tnx`, `inx`, `cnx` | Data Model specific (v2.2): union over VPU 03S and 16. |
| Meaning of a count against its limit | `value <= recorded count` | Generic: the runner, [ADR 0001](../adr/0001-consistency-check-gating.md). |

## Worked example

A NextGen file's `nexus` layer holds three features, with these IDs:

| `id` | `toid` | `type` |
| --- | --- | --- |
| `nex-1` | `wb-2` | `nexus` |
| `zzz-2` | `wb-0` | `terminal` |
| `plain` | `wb-0` | `terminal` |

The table has the columns `fid`, `geom`, `id`, `toid` and `type` and no
`vpuid` or `poi_id`, which the specification expects. With no recorded counts:

```text
schema | missing_columns.nexus | 2 | 0 | FAIL | advisory
schema | extra_columns.nexus | 0 | 0 | PASS | advisory
schema | column_order.nexus | 0 | 0 | PASS | advisory
schema | unobserved_id_prefixes.nexus.id | 1 | 0 | FAIL | advisory
schema | unprefixed_ids.nexus.id | 1 | 0 | FAIL | advisory
schema | unobserved_id_prefixes.nexus.toid | 0 | 0 | PASS | advisory
schema | unprefixed_ids.nexus.toid | 0 | 0 | PASS | advisory
```

- `missing_columns.nexus` is `2` (`vpuid`, `poi_id`).
- `zzz` is a prefix that no observed product uses, so
  `unobserved_id_prefixes.nexus.id` is `1`.
- `plain` has no hyphen, so `unprefixed_ids.nexus.id` is `1`.
- `wb-2` and `wb-0` both carry the observed `wb` prefix, so the `toid` metrics
  are `0`.

Whether these are real defects depends on the product: `zzz` may be a new,
intended prefix, while a missing column is a structural difference from the
specification.
