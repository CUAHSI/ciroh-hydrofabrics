# v2.2 Data Model specifications

- `ngen.json`: NextGen output, based on the official VPU 03S and 16 GeoPackages.
- `reference.json`: Reference output, based on the official VPU 16 GeoPackage.

These are data specifications, not a check implementation. Each file has
`format_version: "1.0"`, `data_model_version: "v2.2"`, and `output_kind`
(`ngen` or `reference`). The HydroShare resource and direct file URLs, local
filenames/paths, and SHA-256 digests are recorded in `sources`. The paths are
provenance, not dependencies: these large files are not checked in and consumers
need not download them to read the specifications. The GeoPackage specifications
were extracted with SQLite read-only connections; the Parquet comparison below
used local files only. No network access was used.

## Consumer contract

- `tables` is keyed by registered `gpkg_contents.table_name`. Its
  `gpkg_contents.data_type` and `srs_id` are the observed registration. Each
  `columns` array is in physical SQLite `PRAGMA table_info` order; `type` is
  the exact declared SQL type, not a runtime storage class. `geometry` is
  `null` for attribute tables; otherwise it gives the registered column,
  geometry type, SRS ID, CRS authority/code/name, and GeoPackage `z` and `m`
  flags (0 = prohibited, 1 = mandatory, 2 = optional). Both NextGen files
  have identical registered structures. Reference structure is known only
  from VPU 16. The EPSG:5070 feature CRS and declarations are observations,
  not evidence that every possible release or VPU has identical metadata.
  In particular, do not interpret a generic `GEOMETRY` declaration as a
  requirement that actual features have no more specific geometry type.
- `identifiers` is an array keyed by each entry's `table` and `column`.
  Observation keys are VPU strings, including leading zeroes. NextGen covers
  the identifier fields in the retired v2.2 schema suite. Each NextGen entry
  has `observed_prefixes`, a sorted
  array containing the union of the keys of its per-VPU `prefix_counts`
  (without the hyphen). This is a convenience summary, **not an allowed-prefix
  rule**; an empty array would mean no prefixes were observed, not that none
  are allowed. The `observations` retain the VPU-specific evidence. For each,
  `row_count`, `null_count`, `unprefixed_count`, and `prefix_counts` were
  calculated over the entire column, not a limited sample. Prefix means
  the text before the first hyphen when that hyphen occurs after at least one
  character; this does not assert anything about the suffix. Nulls and
  unprefixed values are separate from prefixes. Reference observations list
  SQLite runtime storage-class counts and the number of numeric values with a
  fractional part for selected identifiers and topology sequence fields.
  SQLite `REAL` identifiers observed with integral values are not strings or
  necessarily SQL `INTEGER` columns.
- `terminal_observations` records the queries' results, not mandatory or
  exhaustive terminal rules. NextGen groups rows where `toid = "wb-0"` by
  `id` prefix and `type`. Reference counts `toid = 0`, nulls, and nonzero
  downstream IDs not found among IDs in the same table; for `flowpaths` it
  also counts `dnhydroseq = 0` and the intersection with `toid = 0`. Reference
  `network` is a many-row-per-ID table, so its counts are rows, not distinct
  features. A downstream ID absent from a VPU may represent a boundary, and
  the absence of such rows here does not prohibit them elsewhere.
- `attribute_constraints.rules` is an array of individually identified rules.
  `range` uses `gt`/`ge`; `interval` uses explicit lower/upper inclusive
  flags; `scaled_difference` requests an absolute difference, after applying
  `right.scale`, of at most `max_absolute_difference`. The bounds, including
  `0 < n <= 1` and `So >= 0`, and the one-metre length tolerance are
  **CAM-1602 requested validation assumptions**, not universal physical laws
  or guarantees that official data pass. The NextGen `divide-attributes.mean.slope`
  rule uses the physical range [0, 90] degrees: `ngen-workflow/R/vaa.r` derives
  it from a slope raster in degrees. Its inclusive physical endpoints adapt
  the strict (0, 90) plausibility limits in [OWP's validator](https://github.com/NOAA-OWP/hydrofabric-builds/blob/15d48484cfdeb68d32b42d8eb0d95a3cf59b67bd/src/hydrofabric_builds/schemas/validate_hydrofabric.py)
  and [Lynker's bounds](https://github.com/lynker-spatial/hfutils/blob/e5319ac34024af03bc7eee5d4c41e9629514130c/inst/extdata/divide_attr_bounds.csv);
  neither flat nor vertical slope is physically impossible. Field mapping and
  applicability are limited to cases supported by the local data and pipeline definitions.
  The NextGen `divide-attributes.mean.impervious` rule uses [0, 100] percent,
  consistent with the [NOAA OWP v2.2 Data Model](https://github.com/NOAA-OWP/hydrofabric_v2.2/blob/4761e7bf000eec7763a64fd396c3788acaba1472/vignettes/hf_dm.Rmd#L219-L241).
  The newer Lynker `imperv_mean` range is expressed as a fraction and must not
  be copied directly to this percentage field. The `mean.slope_1km` NWM drainage
  factor and the four layers each of `mean.smcmax_soil_layers_stag` and
  `mean.smcwlt_soil_layers_stag` have inclusive [0, 1] envelopes. NOAA's
  [model source](https://github.com/NOAA-OWP/cfe/blob/f9182dfb3d81c407c66c5b782114173893c30cf2/include/cfe.h#L49-L80)
  identifies the drainage factor as dimensionless and the soil-moisture values
  as volumetric fractions. The v2.2 Data Model labels `slope_1km` in degrees
  despite describing it as [0, 1]; the source NetCDF metadata has not been
  independently verified. These bounds are not claims of realistic values for
  every soil or of agreement across soil layers.
- `applies_when` is `all_rows`, `column_equals`, or `matched_rows`. For the
  `has_divide` condition, SQLite integer `1` means the area check applies and
  integer `0` means it does not. NULL or any nonboolean runtime value makes
  applicability indeterminate: report that state, rather than silently
  excluding the row or counting it as an area-rule violation.
- The length rules identify join columns, but `join_cardinality` and
  `duplicate_violation_counting` are `undetermined`. An unambiguous matched
  pair can be compared; report duplicate-key cases as indeterminate, whether
  duplicates occur on either or both sides. Do not select an arbitrary match,
  deduplicate, count the Cartesian join pairs as violations, or assume a
  duplicate is itself an error. Unmatched and NULL-key handling also remain
  undetermined. The official files have duplicate attribute IDs (see below).
- `numeric_value_policy` applies to numeric operand columns of these rules,
  independently of row applicability. SQLite runtime storage must be `integer`
  or `real` and the value must be finite; report nonnumeric values, infinities,
  detectable NaNs, and nonfinite calculation results. A declaration such as
  `REAL` and a SQL range comparison alone do not establish numeric validity.
  Report NULL operands as indeterminate, not necessarily as violations. SQLite
  may convert NaN to NULL; when they cannot be distinguished, report an
  indeterminate NULL rather than treating it as a valid finite value.
- `sentinel_handling` and each rule's `sentinel_policy` require reporting an
  unrecognized sentinel candidate, including `-9998`, in each numeric-declared
  model column unless an authoritative field-specific definition identifies it as missing.
  The candidate list is not exhaustive and does not establish a meaning for
  any value. A field-defined missing value follows the rule's NULL policy,
  which remains undetermined unless separately established; otherwise apply
  numeric checks where applicable. These diagnostics are separate from
  applicability and violation counting. No other constraints are implied.

## Reference Parquet corroboration

The following supplied local Parquet files were inspected with PyArrow 23.0.1.
The DVC metadata and `.dvc/config` associate the v2.2 files with
`s3://ciroh-data/1316cc4c92aa4167bcf47358cdfd5a67/data/contents/{layer}/vpuid_{vpu}.parquet`,
corresponding to the HydroShare resource
https://www.hydroshare.org/resource/1316cc4c92aa4167bcf47358cdfd5a67/.
Hydrolocations use the separate `supporting` remote
`s3://ciroh-data/ad6fc06ca62d4330afdeeb4386e14681/data/contents/hydrolocations/vpuid_{vpu}.parquet`
(resource https://www.hydroshare.org/resource/ad6fc06ca62d4330afdeeb4386e14681/).
These source locations are from local configuration; they were not contacted.
The SHA-256 values below identify the actual local files inspected.

| Local path relative to `ngen-workflow/data/superconus/` | SHA-256 |
| --- | --- |
| `v2.2/divides/vpuid_01.parquet` | `6cb8c5a1103a07f965d53abf0f7cf0dc1d505e974a619fccac8f0d848c014763` |
| `v2.2/divides/vpuid_02.parquet` | `45e86395be01ca0689f91b8762713a9d8b3ee4a821d1d9c367ce1525ae81eb5e` |
| `v2.2/divides/vpuid_03N.parquet` | `364c618e2fb9ab54cb351354720e1cf5e405ab66362a1730efbb9135ec2061a7` |
| `v2.2/flowpaths/vpuid_01.parquet` | `7088acd324bbcede55e40aca5f70f453f3fd7f34d6f05164d26e3167368927ee` |
| `v2.2/flowpaths/vpuid_02.parquet` | `67af5339542fc79475926353db34f44ec11f918f12f523d1fdce6f8a77858b6f` |
| `v2.2/flowpaths/vpuid_03N.parquet` | `24cf265a85f0e1f9f74b0857eea3e7f9c5fb1809cba23d9ae9b2b7cc707f0e6b` |
| `v2.2/network/vpuid_01.parquet` | `06b723fe6fd5d7c6fc9f6fc6ce3a4d91d298b0cf605f9a3a7e92d6f27ff75196` |
| `v2.2/network/vpuid_02.parquet` | `a7214e7c4d97f64d1c121838b41742f0c0fc7f9ee1b663a0e4e259797992dac5` |
| `v2.2/network/vpuid_03N.parquet` | `08ee58f9cc6607dbf13a0e3c08a33300ae75024ea731c4bd64c1b579705d403e` |
| `hydrolocations/vpuid_01.parquet` | `814a9ccd0772c731f47b7cbf19d14c73345a6abaf6cfce1b18c96196f9e8f439` |
| `hydrolocations/vpuid_03N.parquet` | `61092abfffa78c01e4bd4bf8dc1ab5e11dd9d5053f730dc31b8e53175f62c7f0` |

Against the Reference VPU 16 GeoPackage's declared columns, each of the nine
v2.2-path Parquet files has the same base column names and compatible types:
Arrow `double` / SQLite `REAL`, `bool` / `BOOLEAN`, and `string` / `TEXT`;
spatial `geom` is Arrow binary WKB versus a registered GeoPackage geometry.
The GeoPackage additionally has `fid` and `vpuid` in `divides` and `flowpaths`,
and `fid` in `network`. Non-geometry column order agrees, but `geom` is last in
the Parquet files and second in the GeoPackage. The six spatial files' `geo`
metadata specifies WKB, `geo.version = "2.2"`, `schema_version = "0.1.0"`,
and CRS equivalent to the GeoPackage's EPSG:5070 (checked with PyProj). The
three network files have no `geo` metadata or geometry column, so they do not
provide CRS evidence.

The two supporting hydrolocation files also have matching base column names,
compatible types (including Arrow `int32` / SQLite `MEDIUMINT`), an extra
GeoPackage `fid`, different geometry position, WKB metadata, and equivalent
EPSG:5070 CRS. **Their `geo.version` is `"2.3"`, not `"2.2"`**; their
`schema_version` is `"0.1.0"`. This is a metadata observation, not proof of
their content's version. They are not used to establish a v2.2 hydrolocation
schema or treated as v2.2 products.

As a separate value observation, `flowpaths.toid = 0` occurs in 675, 740, and
562 rows in VPUs 01, 02, and 03N respectively; corresponding `network` counts
are 813, 871, and 617. None of those six columns contains nulls or nonzero
`toid` values absent from the same file's `id` column. These observations
corroborate, but do not mandate, the VPU 16 terminal convention. Files cover
different VPUs; this is not a feature-by-feature comparison. Parquet and
GeoPackage have different formats, geometry representations and column order,
so the comparison does not imply they are interchangeable or establish other
VPUs' schemas.

## Interpretation and limitations

The identifier vocabulary is **observed**, not an exhaustive allowlist. VPU
03S has `cnx` in `divides.toid` and `nexus.id`; VPU 16 has no `cnx` in those
fields. This is a difference in observed prefix sets, not evidence that either
product is invalid. All other old-test ID fields have the same observed prefix
sets in these two VPUs. Some columns contain nulls, notably NextGen
`network.id`, `network.divide_id`, and `divides.id`; empty or all-null columns
in other VPUs cannot establish a prefix convention.

In Reference VPU 16, `flowpaths.toid = 0` occurs in 2,680 rows, exactly the
rows with `dnhydroseq = 0`; `network.toid = 0` occurs in 3,103 rows. NextGen
`nexus.toid = "wb-0"` occurs for observed terminal, internal, and (in 03S)
coastal types; do not infer that every such row is type `terminal`.

`flowpaths.areasqkm` positivity applies only where `has_divide = 1`: in the
sample, no-divide flowpaths have zero area (6 rows in NextGen 16, 295 in
Reference 16). NextGen 16's six no-divide flowpaths nevertheless have non-null
`divide_id`, so do not substitute a non-null-ID test for the flag. All observed
flag values in these files are SQLite integers 0 or 1; this does not establish
how NULL or nonboolean flags should be interpreted. Network rows include nexus
or internal rows for which a blanket positive-length/area rule would be
inappropriate. Other length/area fields and hydraulic attributes have not been
assigned rules merely because their names suggest a meaning. The NextGen VPU
16 `flowpath-attributes-ml.n` has five nulls; the rules do not resolve whether
nulls are permitted.

Each NextGen attribute table has 10 duplicated IDs in VPU 03S (20 rows) and 8
in VPU 16 (16 rows); `flowpaths.id` is unique in both sampled files. These are
observations, not a uniqueness guarantee or an instruction to collapse the
attribute rows. The correct comparison cardinality and violation-count unit for
duplicate or many-to-many matches remain undetermined.

The supplied CAM-1602 information mentions `-9998` as a sentinel, but its
field-specific meaning and scope are not established by these sources. The
specified reporting policy does not infer that it means missing. A scan of
registered numeric-declared columns found no `-9998` values in these
three files; this does not establish that it never occurs elsewhere. Additional
VPUs and authoritative field documentation are needed before turning observed
prefixes, terminal values, NULL handling, or sentinel handling into universal
validation rules.
