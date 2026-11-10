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
each registered check, including `schema`, `network`, `geometry`, and
`attributes`. When migrating an older custom config, add:

```yaml
attributes:
  blocking: false
```

Optional `--config` and `--counts` paths allow alternative files, for example
when testing a proposed change. The report names the configuration and counts
files actually used; CI must use the checked-in files rather than untrusted
alternatives.

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
conventions and specified attribute rules are checked separately, as described
below.

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

## v2.2 attribute check

The `attributes` check reads the selected output kind's rules from the
[v2.2 specifications](models/v2.2/README.md):
[`ngen.json`](models/v2.2/ngen.json) or
[`reference.json`](models/v2.2/reference.json). It inspects the GeoPackage
read-only, without downloading a reference product, and is advisory by default.
The rules are CAM-1602 validation assumptions, not universal physical laws or
promises that official products satisfy them; in particular, do not interpret
bounds as physical limits merely because they describe a distribution. The
current check does not compare attribute distributions with a reference product.
See the [implementation](attributes/attribute_checks.py) and the specifications
for the current rules and their provenance.

The attribute checker selects a trusted `models/<version>/<kind>.json` file by
identifier rather than hardcoding v2.2. A compatible new model can define its own
columns, bounds, and supported rules using specification format 1.0. The checker
validates metadata, column types, rule references and semantics before inspecting
input data; an unsupported rule or policy is an error, not a silently skipped
check. The current evaluator supports range and interval rules, integer-boolean
conditions, and scaled comparisons with a single text join key. Other versions
or policies require additional implementation and tests. The schema, network,
geometry, and CLI checks are still v2.2-specific, so adding a model specification
alone does not enable an end-to-end CLI run for that model.

For both output kinds, the specified rules check positive divide area and
flowpath length, and positive flowpath area when `has_divide` is SQLite integer
`1`. Integer `0` makes the area rule inapplicable; NULL or a nonboolean value
makes applicability indeterminate. NextGen also checks `mean.impervious` in
[0, 100] percent, terrain `mean.slope` in [0, 90] degrees, the NWM drainage
factor `mean.slope_1km` and all eight volumetric soil moisture columns in [0, 1],
and `Length_m > 0`, `So >= 0`, `0 < n <= 1`, and `0 <= MusX <= 0.5` in both
flowpath attribute tables. Their
`Length_m` values are compared with `flowpaths.lengthkm` converted to metres,
with an absolute difference of at most 1 metre for uniquely matched IDs. A
small allowance of four machine epsilons scaled to the larger operand, capped
at 1e-9 metre and one-billionth of the tolerance, avoids roundoff at the
inclusive boundary. A zero tolerance has no allowance. Each attribute table is
compared separately with `flowpaths`.

Ratcheted counts include:

- `violations.<rule>`: finite numeric values outside an applicable rule, or
  uniquely matched length pairs outside the tolerance.
- `invalid_numeric.<table>.<column>`: non-NULL operand values that are not
  finite SQLite `integer` or `real` values. Numeric text is not coerced.
- `sentinel.<table>.<column>`: numeric-storage occurrences of the specification's
  sentinel candidates in present numeric-declared Data Model columns, currently
  including `-9998`. Values stored as text are not identified as sentinels. The
  list is not exhaustive, and the
  meaning and field scope of `-9998` are undetermined. No field-defined missing
  codes are currently known; candidates are reported and still evaluated by
  applicable numeric rules, so a value can also count as a violation.
- `nonfinite_calculation.<rule>`: uniquely matched length pairs whose scaled
  difference is nonfinite, reported separately from tolerance violations.

Operand diagnostics cover present numeric-rule columns independently of row
applicability. NULL operands are counted as `indeterminate_null.<table>.<column>`
`INFO`, not violations; SQLite may expose NaN as NULL. Nonfinite and nonnumeric
operands are reported as `invalid_numeric` rather than range violations. For
conditional rules, `indeterminate_applicability.<rule>` counts rows with NULL or
nonboolean flags as `INFO`, independently of the operand diagnostics. These
counts are not proof that the affected rows are valid or invalid.

Length comparisons use only non-NULL text IDs occurring once on each side and
finite numeric operands. IDs are matched by exact text bytes, independently of
SQLite affinity or collation; non-text IDs are indeterminate rather than coerced.
For these rules, `left` is the attribute table and `right` is `flowpaths`. `indeterminate_duplicate_keys.<rule>` counts distinct key values duplicated on
either side, including unmatched keys, rather than choosing a row or counting a
Cartesian join. `unmatched_left_rows.<rule>` and `unmatched_right_rows.<rule>` count rows
with non-NULL IDs missing on the other side; `null_join_key_left_rows.<rule>`
and `null_join_key_right_rows.<rule>` count rows with NULL IDs. The corresponding
`invalid_join_key_left_rows` and `invalid_join_key_right_rows` count non-text IDs.
`compared_pairs.<rule>` counts pairs compared, excluding nonfinite calculations
and precision-indeterminate pairs. `indeterminate_operands.<rule>` counts unique
matched pairs with NULL or invalid operands, and `indeterminate_precision.<rule>`
counts finite pairs that cannot be compared reliably without losing precision.
These are `INFO`, not length violations; the correct handling of duplicates and
unmatched IDs remains undetermined.

A rule missing a required table, operand, join key, or applicability flag is
reported as `not_evaluated.<rule>` with `INFO`; consult the `schema` check for
missing prerequisites. If no rule can be evaluated, `no_applicable_checks` is a
ratcheted count of 1. A rule can be evaluated when its prerequisites exist even
if no rows can actually be compared, so a zero violation count alone does not
establish coverage. `not_checked.<table>.<column>` is an `INFO` inventory of
columns in the specification without a range or interval rule, even when the
table or column is absent from the input. It does not mean the column is present,
that no other check uses it, or that its values are valid; unspecified constraints
remain undetermined.

Attribute limits are recorded per metric under `attributes` in `counts.yaml`;
missing limits default to zero. A nonzero ratcheted count may therefore report
`FAIL` even while advisory; it affects the exit status only when the check is
blocking. `INFO` values do not affect the gate, including when the check is
blocking. Review the assumptions, indeterminate cases, and product-specific
counts before enabling blocking.

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
informational values, and incomplete-check errors separately. The `attributes`
check returns ratcheted metrics and informational values separately. Limits can
be supplied for each ratcheted metric independently. Checks inspect one Build;
the runner owns comparison to recorded limits and gating.

Run the focused tests, which generate small temporary GeoPackages:

```sh
pixi run -e consistency python -m pytest validation/consistency
```
