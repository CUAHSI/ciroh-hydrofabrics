# Running and recording Consistency Checks

This page is for people who run the Consistency Checks or change them: the
command line, how a run selects its Data Model, VPU and counts, how to record
counts, and how to add a Data Model or a check. For what the checks measure
and how to read a report, see the [index](README.md) and
[reading a report](reading-a-report.md).

## Running the checks

Run the same Consistency Checks locally and in CI using Pixi:

```sh
pixi run consistency-check path/to/my-hydrofabric.gpkg --type ngen --vpu 16 --data-model v2.2
pixi run consistency-check path/to/build-directory --data-model v2.2
pixi run consistency-check https://www.hydroshare.org/resource/RESOURCE_ID/
```

For a single local GeoPackage, the filename is unrestricted; supply `--type`
(an output kind the Data Model specifies, such as `ngen` or `reference` for
v2.2) and `--vpu`. The VPU is case-sensitive and may contain
letters and digits (for example `01`, `03S`, or `16`). The default Data Model is
`v2.2`. A Data Model is the directory `models/<name>/` with one specification
per output kind (see [Adding a Data Model](#adding-a-data-model)).
An unknown Data Model, an output kind it does not specify, or a specification
that is missing, incompatible or declares unsupported semantics stops the command
with status 2 before any file is read; there is no fallback to v2.2.

### Multi-VPU GeoPackages

If a GeoPackage contains multiple VPUs, the runner checks only rows
belonging to the selected VPU in every layer; it does not calculate CONUS-wide
counts under a single VPU key. Unlabelled network rows are assigned through
their unique divide ID. If layer rows cannot be assigned unambiguously, the
run is incomplete and `--record` leaves the counts file unchanged. The selected
rows are copied into a temporary GeoPackage under `.scratch/` and removed after
the checks; allow space for one VPU. Cross-VPU links are checked within the
selected subgraph and may appear unresolved. A filtered CONUS file is not
necessarily identical to a published per-VPU product; record official baselines
from the published per-VPU files. Files with no `vpuid` fields retain the
existing single-VPU-file assumption.

### Directories and HydroShare resources

A directory is searched recursively for GeoPackages. For directories and
HydroShare resources, each GeoPackage must be named
`<kind>-hydrofabric-vpu-<VPU>.gpkg`, where `<kind>` is one of the selected Data
Model's output kinds (for v2.2, `reference` or `ngen`), so its type and VPU can
be inferred separately. Files that are not GeoPackages are ignored; a local
GeoPackage with any other name, including one of another Data Model's kinds, is
an error. The `--type` and `--vpu` flags apply only to a single file and are
rejected for batch inputs.

The HydroShare target is a **public** resource landing URL, not a direct file
link. The command lists its files, downloads each GeoPackage individually, checks
it, verifies its size against the HydroShare listing, and deletes the temporary
copy before downloading the next. Network access and enough temporary disk space
for the largest file are required. The download redirect allowlist covers
HydroShare and the known HydroShare Google Storage buckets; a new storage backend
or bucket requires a code update. Private resources are not supported.

## Configuration and counts files

`checks.yaml` sets each check's `blocking` flag; all checks start advisory. Edit
it in a reviewed change to enable a gate. A missing or malformed flag is an error,
not an implicit advisory setting. A custom configuration must include a flag for
each registered check: `geopackage_layers`, `schema`, `network`, `geometry` and
`attributes`. A configuration written before the `attributes` check existed needs
`attributes: {blocking: false}` added. `checks.yaml` can also set
`geometry.overlap_min_area_m2` to override the Data Model's overlap threshold; see
[`geometry`](geometry.md#thresholds-and-conventions).

`counts.yaml` stores the recorded limits under Data Model, output kind (a kind of
the model, such as `reference` or `ngen`), VPU, check name, and metric name. Quote
VPU keys so YAML preserves leading zeroes and treats all VPUs as strings. For
example:

```yaml
v2.2:
  ngen:
    "16":
      network:
        duplicate_primary_ids.nexus: 6
```

The checked-in counts record each ratcheted metric measured on the official v2.2
products, for both output kinds and for 21 VPUs each (`01`, `02`, `03N`, `03S`,
`03W`, `04` to `09`, `10L`, `10U` and `11` to `18`). A metric or a VPU with no
recorded count is treated as zero. Duplicate YAML keys and non-string VPU keys
are rejected instead of silently ignoring recorded values. See
[ADR 0001](../adr/0001-consistency-check-gating.md) for why the limits are
counts recorded from the official products.

Optional `--config` and `--counts` paths allow alternative files, for example
when testing a proposed change. The report names the configuration and counts
files actually used; CI must use the checked-in files rather than untrusted
alternatives.

## Recording counts

Use `--record` to write the measured ratcheted metrics to the selected counts
file (creating it if necessary). Only metrics actually measured are updated;
other entries are preserved, and informational values are not recorded. YAML
comments and formatting are not preserved when the file is rewritten. The
report and exit status still compare against the **previous** limits, so a
complete run can write counts and exit `1` when a blocking check exceeds its
old limit. If any file, download, listing, or check is incomplete, no counts
are written for the batch. Duplicate Data Model, output kind, and VPU identities
in a batch are rejected. Recording can increase limits as well as lower them;
review the diff against the contribution ratchet policy before committing.
Use the same check configuration, including the geometry overlap threshold,
when recording limits and checking Builds against them.

Multiple `--record` processes can check files concurrently and write to the same
counts file. Each reloads and merges the latest counts under an exclusive lock;
if runs record the same metric, the last completed write wins. Reports compare
against the limits read at the start of each run, which may have changed by the
time the counts are written. A persistent `.<counts-filename>.consistency-check.lock`
file alongside the counts file coordinates cooperating recorders; do not remove
it while any recorder is running or waiting. All writers must use this version of
the runner, have access to the lock file, and use a filesystem that supports
advisory locks and atomic renames. Linux NFS requires write access to the lock
file for an exclusive lock.

The exit statuses are described in
[reading a report](reading-a-report.md#exit-statuses). The runner continues with
other files when an individual filename, download, or check fails.

## Adding a Data Model

A Data Model is the directory `models/<name>/` containing one JSON specification
per output kind, `models/<name>/<kind>.json`. The directory name and file names
are the Data Model and output kind identifiers (letters, digits, `.`, `_` and
`-`, starting with a letter or digit); `--data-model` selects the directory and
`--type` or the batch filename selects the file. Symlinks and duplicate JSON keys
are rejected. Each file must contain `format_version: "1.0"`,
`data_model_version` equal to the directory name and `output_kind` equal to the
file name. All checks load the same file through
[`data_model.py`](../../validation/consistency/data_model.py), which also
validates the whole model up front, before any GeoPackage is opened. Errors name
the Data Model and output kind and exit with status 2; none falls back to v2.2.

Besides the `tables`, `identifiers` and `attribute_constraints` described in
[the v2.2 Data Model](data-model-v2.2.md), each file has a top-level `checks`
section. Its values are the model's conventions, not claims about every product.

- `checks.schema.id_prefix_separator`: the text separating an identifier prefix
  from its suffix (`-` for v2.2).
- `checks.network.primary_ids`: layer to the column whose repeated non-null values
  are counted as `duplicate_primary_ids.<layer>`.
- `checks.network.relationships`: a list of `name`, `source`, `source_key`,
  `target`, `target_key` and an optional `flag`. Each reports the rows of `source`
  whose key is missing from `target` as the metric `<name>`, plus
  `<name>.<flag>_0` for those whose `flag` column is 0.
- `checks.network.reciprocal_links`: `null`, or two `[table, id column, reference
  column]` entries whose reference columns point at each other's ID column.
- `checks.network.routing`: `style` is `direct` or `via_nexus`. Both take a
  `terminal_id`, the value of `toid` that marks a terminal. `direct` takes
  `layers` (each resolves `toid` within itself) and the `topo` label
  (`link_label`) of network rows that link flowpaths; other nonterminal labels are
  reported as indeterminate. `via_nexus` takes `target_layers` (resolve to the
  `nexus` layer), `outlet_types` (a nexus ID prefix to a type name) and
  `nexus_id_prefixes`.
- `checks.geometry`: the `topology_layer`, and the default `overlap_min_area_m2`
  and `gap_min_area_m2` thresholds. The expected CRS is the registration of that
  layer in `tables`.

To add a model:

1. Create `models/<name>/` with a `<kind>.json` for each output kind, using
   `format_version` 1.0 and the metadata above. Copying and editing
   [`models/v2.2/ngen.json`](../../validation/consistency/models/v2.2/ngen.json)
   is the easiest start.
2. Declare the layers and columns in `tables`, the identifiers to check, the
   `attribute_constraints.rules`, and the `checks` section.
3. Run `pixi run consistency-check <file> --type <kind> --vpu <VPU> --data-model <name>`.
   A malformed or unsupported declaration is reported before any check runs.
4. Optionally record limits under `<name>` in `counts.yaml`.

The tests in `tests/test_second_model.py` build such a model, `v9.9`, from the
v2.2 specifications in a temporary directory and run it end to end for both
output kinds, so they serve as a worked example.

The attribute checker selects a trusted `models/<version>/<kind>.json` file by
identifier rather than hardcoding v2.2. It validates metadata, column types, rule
references and semantics before inspecting input data; an unsupported rule or
policy is an error, not a silently skipped check. The current evaluator supports
range and interval rules, integer-boolean conditions, and scaled comparisons with
a single text join key. Other versions or policies require additional
implementation and tests.

The following are implementation extensions, not yet declared in the
specification; a model that differs needs code changes and tests:

- Routing and hydroseq checks use layers named `flowpaths`, `nexus`, `network`
  and `divides` and the columns `id`, `toid`, `hydroseq`, `dnhydroseq` and `topo`;
  nexus outlet types are read from a `type` column.
- The network check always reports `duplicate_network_rows` for a layer named
  `network`, ignoring a `fid` column.
- The two reciprocal metrics are always named `reciprocal_divide_flowpath_*`, and
  the topology metrics `divide_overlaps.*`, `divide_gaps.*` and
  `divide_union_area_m2`, whatever the `topology_layer`.
- The VPU selection assumes a `vpuid` column and treats the `network` and
  `divides` layers specially (via `divide_id`), independently of the
  `topology_layer`.
- Batch filenames always have the form `<kind>-hydrofabric-vpu-<VPU>.gpkg`.
- The hydroseq and cycle algorithms are fixed; only the routing style is selectable.
- Attribute rules are limited to range, interval and scaled-difference kinds.

## Adding a check

Register a callable in `CHECKS` in
[`consistency_check.py`](../../validation/consistency/consistency_check.py) and
give it a boolean `blocking` entry in `checks.yaml`. Ordinarily it receives a
local GeoPackage `Path`, the selected Data Model name, and the output kind; it
returns a nonempty mapping of stable metric names to nonnegative finite numbers.
A check should read its model-specific conventions through `data_model.py`
(`load_spec` and the `*_semantics` functions) rather than hardcoding them. The
`geometry` check additionally receives an optional overlap-threshold override
(`None` means use the model's default) and returns ratcheted metrics,
informational values, and incomplete-check errors separately. The `attributes`
check returns ratcheted metrics and informational values separately. Limits can
be supplied for each ratcheted metric independently. Checks inspect one Build;
the runner owns comparison to recorded limits and gating.

Document every metric a new check can emit on its own page in this directory,
with the pass and fail conditions and a worked example, and link the page from
the [index](README.md).

Run the focused tests, which generate small temporary GeoPackages:

```sh
pixi run -e consistency python -m pytest validation/consistency
```
