# Consistency Checks

Run the same Consistency Checks locally and in CI using Pixi:

```sh
pixi run consistency-check path/to/my-hydrofabric.gpkg --type ngen --vpu 16 --data-model v2.2
pixi run consistency-check path/to/build-directory --data-model v2.2
pixi run consistency-check https://www.hydroshare.org/resource/RESOURCE_ID/
```

For a single local GeoPackage, the filename is unrestricted; supply `--type`
(`ngen` or `reference`) and `--vpu`. The VPU is case-sensitive and may contain
letters and digits (for example `01`, `03S`, or `16`). The default Data Model is
`v2.2`. Other Data Models require a checked-in schema specification; selecting an
unsupported model makes the schema check incomplete and the command exits with
status 2.

A directory is searched recursively for GeoPackages. For directories and
HydroShare resources, each GeoPackage must be named
`reference-hydrofabric-vpu-<VPU>.gpkg` or `ngen-hydrofabric-vpu-<VPU>.gpkg`
so its type and VPU can be inferred separately. Other files are ignored. The
`--type` and `--vpu` flags apply only to a single file and are rejected for batch
inputs.

The HydroShare target is a **public** resource landing URL, not a direct file
link. The command lists its files, downloads each GeoPackage individually, checks
it, verifies its size against the HydroShare listing, and deletes the temporary
copy before downloading the next. Network access and enough temporary disk space
for the largest file are required. The download
redirect allowlist covers HydroShare and the known HydroShare Google Storage
buckets; a new storage backend or bucket requires a code update. Private resources
are not supported.

## Report and gate

The report lists each file and its Data Model, output kind and VPU, followed by
each check's metric, value, recorded count, PASS/FAIL, and advisory/blocking
mode. The default Data Model is `v2.2`; use `--data-model` to select another.
A ratcheted metric passes when its value is no greater than the recorded limit.
Informational values show `INFO` and `-` instead of a recorded limit; they never
influence the gate. Checks measure the Build itself; comparing those measurements
to recorded limits is a separate review policy, not a feature-by-feature
comparison with a baseline.

`counts.yaml` stores recorded limits under Data Model, output kind (`reference`
or `ngen`), VPU, check name, and metric name. Quote VPU keys so YAML preserves
leading zeroes and treats all VPUs as strings. For example:

```yaml
v2.2:
  reference:
    "16":
      geopackage_layers:
        empty_layers: 1
```

The checked-in counts are **not yet populated from official products**; missing
counts are treated as zero (CAM-1603 will record them). Duplicate YAML keys and
non-string VPU keys are rejected instead of silently ignoring recorded values. The initial `geopackage_layers` check is a plumbing
example, not a complete Data Model or quality assessment: it reports whether
there are no layers and how many layers have no features. An empty layer can be
legitimate. Additional checks and official counts are tracked separately.

`checks.yaml` sets each check's `blocking` flag; all checks start advisory. Edit
it in a reviewed change to enable a gate. A missing or malformed flag is an error,
not an implicit advisory setting. A custom configuration must include a flag for
each registered check, including `schema`, `network`, and `geometry`. Optional `--config` and `--counts`
paths allow alternative files, for example when testing a proposed change. The report names
the configuration and counts files actually used; CI must use the checked-in
files rather than untrusted alternatives.

Exit status is `0` for a completed run with no blocking failures (including
advisory failures), `1` for one or more blocking metric failures, and `2` for an
invalid target, configuration, download, or incomplete check. An execution
error takes precedence over a blocking failure. The runner continues with other
files when an individual filename, download, or check fails.

## v2.2 schema check

The checked-in [v2.2 specifications](models/v2.2/README.md) describe the
NextGen and Reference GeoPackage structures, source provenance, observed ID
and terminal conventions, and available attribute rules. The `schema` check
selects a specification by Data Model and output kind; it does not download a
reference product. It reports per-layer counts for missing tables and
registration, incorrect layer type, missing or extra columns, column order and
declared types, and geometry registration, type, and CRS. Extra layers are
allowed. Column order compares the relative order of columns present in both
tables; missing or extra columns can still shift their physical positions. Type
checks exclude `geom`. Geometry registration and CRS are checked even for empty
layers. An empty layer may declare generic `GEOMETRY`; a specific type is also
accepted whenever the specification says `GEOMETRY`. CRS checks compare the
registered SRS IDs and authority/code, not the full spatial-reference definition.

For the NextGen identifier columns covered by the former v2.2 suite, the check
reports the number of distinct prefixes not observed in the two source VPUs and
the number of non-null values without a prefix. It skips all-null columns.
**Observed prefixes are not an exhaustive vocabulary**: a new prefix may be
legitimate, so `unobserved_id_prefixes` is a comparison with observations, not
an authoritative allowlist. Review these advisory findings before enabling a
blocking gate.
Reference identifiers are numeric, so no prefix check applies. Network terminal
conventions are checked separately, as described below. Attribute bounds are
recorded in the specifications but are not yet checked.

Metrics name their category and layer, for example `missing_columns.nexus` or
`unobserved_id_prefixes.nexus.id`. A dependent metric is omitted when its prerequisite is
missing or it is inapplicable; the prerequisite's own metric reports the
problem. Counts for a future ratchet are supplied per metric, e.g.
`schema: {missing_columns.nexus: 1}` under the appropriate model, kind and VPU.

## v2.2 network check

The `network` check reports counts for the selected output kind. It is advisory
by default. It requires no reference download, and reads attributes without
loading geometries into memory. Metrics whose required tables or columns are
missing are omitted; the `schema` check reports missing prerequisites. If no
network metric is applicable at all, `no_applicable_checks` is reported as 1.
The following counts are observations to review, not assertions that every
reported feature is necessarily wrong:

- `duplicate_primary_ids.<layer>` counts extra rows for each repeated non-null
  domain key, not duplicate key groups. The keys are `divide_id` for divides
  and divide-attributes, `id` for flowpaths, nexus and flowpath attribute tables,
  `lake_id` for lakes, `poi_id` for NextGen POIs, and Reference `hl_id` for
  hydrolocations. NextGen hydrolocations have no established unique key here.
  POI uniqueness is an observed convention, not a proven universal constraint.
  The network table is many-rows-per-ID and is excluded.
- `duplicate_network_rows` counts extra rows equal across all columns except
  the GeoPackage surrogate `fid`, including geometry if present. SQLite groups
  nulls together and compares text case-sensitively. Repeated IDs alone are not
  duplicate rows.
- `dangling_toid.<layer>` counts non-null downstream references that do not
  resolve. Reference flowpaths and network resolve within their own layer,
  excluding the observed numeric `0` terminal. NextGen flowpaths, divides and
  flowpath attribute tables resolve to nexus, nexus resolves to flowpaths, and
  network resolves to any flowpath, nexus or network ID; the observed `wb-0`
  terminal is excluded.
  The network metric requires all three target-ID columns. Missing links may
  cross VPU boundaries. `indeterminate_null_toid.<layer>` reports nulls
  separately rather than treating them as dangling or valid terminals.
- `cycle_nodes.<graph>` counts distinct IDs belonging to cycles, including
  self-loops, not paths downstream of cycles. The graphs are Reference
  flowpaths, NextGen flowpaths plus nexus, and each kind's network table.
  Duplicate edges are collapsed; conflicting edges for a repeated ID are all
  retained, so cycles in that union may be ambiguous. The graph must fit in
  memory. Terminal sentinels are excluded.
- `terminal_convention.<layer>` reports NextGen outlet mismatches against the
  observed v2.2 convention: nexus IDs with `tnx-`, `cnx-`, and `inx-` prefixes
  have types `terminal`, `coastal`, and `internal`, respectively, and point to
  `wb-0`. Direct flowpath or divide references to `wb-0`, and untyped/shared
  outlets, are also reported, including direct sentinel targets in flowpath
  attribute tables. Network rows are checked when their IDs are nexus-like or
  they target `wb-0`. These conventions are based on sampled
  products, not an exhaustive specification.
- `divides_without_flowpaths`, `flowpaths_without_divides`,
  `divides_without_attributes`, and `hydrolocations_without_nexus` count source
  rows with null or unmatched references. They use, respectively,
  `divides.id` → `flowpaths.id`, `flowpaths.divide_id` → `divides.divide_id`,
  `divides.divide_id` → `divide-attributes.divide_id`, and
  `hydrolocations.nex_id` → `nexus.id`. The last two apply only to NextGen.
  `divides_without_referencing_flowpaths` checks the other direction, from
  `divides.divide_id` to `flowpaths.divide_id`. Target duplicates do not
  multiply counts. Where flags exist, suffixes `.has_flowline_0` and
  `.has_divide_0` count the subset of orphans with those flags. Some official no-flowline, no-divide and coastal features legitimately
  lack these relationships; the subset metrics, like all metrics, are compared
  to recorded limits and may show `FAIL` even for legitimate cases.
  `reciprocal_divide_flowpath_mismatches` counts directed source rows whose
  uniquely resolved counterpart points back to a different existing source;
  the `_ambiguous` metric counts rows involving duplicate keys. Missing and null
  links are left to the orphan metrics, and one inconsistent association may
  count in both directions.
- `hydroseq_order_violations.flowpaths` counts resolved nonterminal flowpath
  edges whose upstream `hydroseq` is not greater than the downstream value.
  Reference `dnhydroseq_mismatches.flowpaths` compares `dnhydroseq` with the
  actual downstream flowpath's `hydroseq`. For Reference `network` rows with
  `topo = fl-fl`, corresponding `.network` metrics compare each row with the
  downstream flowpath; many network rows can share an ID. NextGen flowpaths
  resolve downstream through the nexus layer, while flowpath-associated network
  rows use network nexus rows and compare against downstream network flowpath
  sequences. Identical repeated nexus destinations and valid downstream
  sequences resolve; conflicting values are ambiguous. Missing network rows
  are indeterminate, including valid coastal or internal outlets omitted from
  the network table. NextGen network nexus rows are excluded; rows that cannot
  be classified are indeterminate. `hydroseq_mismatches.network` compares each
  network flowpath row's sequence to the flowpath layer, including terminal
  rows. NextGen has no `dnhydroseq` field. Companion `_indeterminate` and
  `_ambiguous` metrics count unresolved or unusable values and duplicate-key
  cases separately; edge checks exclude terminal links. Reference network rows
  with another topology label are indeterminate.
  Official NextGen 03S itself has ordering violations, so review this assumption
  before enabling a gate.

Counts for these metrics are not yet seeded from the official products; missing
limits default to zero. Do not enable blocking until maintainers review the
conventions, indeterminate counts, legitimate orphan subsets, and official
limits for the relevant Data Models and VPUs.

## v2.2 geometry check

The `geometry` check is advisory by default and covers every spatial layer in the
GeoPackage, including extra layers, for both output kinds. It reports per-layer
`null_geometries`, `empty_geometries`, `invalid_geometries`, and
`duplicate_geometries` counts. Null and empty geometries are separate from
invalid nonempty geometries. Duplicates count extra rows of topologically equal
valid geometries in the same layer, independent of vertex order and redundant
vertices. Topological equality is not well-defined for invalid geometries; for
those, only exact normalized coordinate duplicates, including reversed geometry,
are counted, so other equivalent invalid shapes may be missed. Nulls are excluded
and all empty geometries are considered equal. Equality is 2D and does not
preserve flowpath direction. Findings are observations, not necessarily defects.
Attribute-only tables are excluded; if there are no spatial layers,
`no_applicable_checks` is 1.

For divides, three independently ratcheted `divide_overlaps` metrics report
`count`, `total_area_m2`, and `largest_area_m2`. An overlap is the intersection
of one unordered pair of divides, including containment and equal polygons;
the area of all disconnected components for that pair is combined. Only pairs
strictly larger than the configured threshold count. An area covered by three
or more divides contributes to multiple pairwise intersections, so total area
is not the unique overlapped area.

Set `geometry.overlap_min_area_m2` in `checks.yaml` to a finite nonnegative
number; it defaults to 100 if omitted and the effective value is reported as
`overlap_min_area_m2` with `INFO`. The threshold is in square metres and must be
held consistent when comparing Builds with recorded limits. Changing it
changes the meaning of all three overlap metrics, so review and regenerate the
corresponding recorded limits before using the ratchet.

The independently ratcheted `divide_gaps` metrics have the same three suffixes.
They describe uncovered components of interior holes in the union of divides,
subtracting islands, and include only components strictly larger than 100 m².
The outer VPU edge and gaps connected to it are not checked without a boundary
layer. Lakes and other intended exclusions may appear as interior gaps.
`divide_union_area_m2` reports the union's area as `INFO`; it is not ratcheted.

Area calculations require the registered v2.2 EPSG:5070 CRS and an equivalent
CRS definition; they do not reproject coordinates. Invalid divides are repaired
in memory for topology calculations, and polygonal components are retained if
repair also produces lines. The invalid count still describes the original
geometries; the input GeoPackage is not modified. A null, empty, nonpolygonal,
or unrecoverable divide, an unsuitable CRS, or a failed geometry operation makes
topology incomplete: the command exits 2 and does not report partial topology
values. Other available geometry findings are still reported. If the divides
layer is absent, topology metrics are omitted and the schema check reports the
missing layer; a nonspatial divides table instead makes topology incomplete. The
geometry check loads each spatial layer into memory and the
divide union may be expensive for large Builds.

## Adding checks

Register a callable in `CHECKS` in `consistency_check.py` and give it a boolean
`blocking` entry in `checks.yaml`. Ordinarily it receives a local GeoPackage
`Path`, the selected Data Model name, and the output kind; it returns a nonempty
mapping of stable metric names to nonnegative finite numbers. The `geometry`
check additionally receives its overlap threshold and returns ratcheted metrics,
informational values, and incomplete-check errors separately. Limits can be
supplied for each ratcheted metric independently. Checks inspect one Build; the
runner owns comparison to recorded limits and gating.

Run the focused tests, which generate small temporary GeoPackages:

```sh
pixi run -e consistency python -m pytest validation/consistency
```
