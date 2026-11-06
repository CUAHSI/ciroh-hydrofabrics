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
A metric passes when its value is no greater than the recorded count. Checks
measure the Build itself; comparing those measurements to recorded counts is a
separate review policy, not a feature-by-feature comparison with a baseline.

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
each registered check, including `schema`. Optional `--config` and `--counts`
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
allowed. Column order is checked only when the column sets agree; type checks
cover columns present in both tables, excluding `geom`. Geometry checks skip
empty layers and accept a specific type when the specification says `GEOMETRY`.

For the NextGen identifier columns covered by the former v2.2 suite, the check
reports distinct prefixes not observed in the two source VPUs, or one violation
if a non-null column has no prefixed values. It skips all-null columns and, as
the old suite did, ignores unprefixed values if at least one prefix exists.
**Observed prefixes are not an exhaustive vocabulary**: a new prefix may be
legitimate. Review these advisory findings before enabling a blocking gate.
Reference identifiers are numeric, so no prefix check applies. Network terminal
conventions and attribute bounds are recorded in the specifications but not
checked here; those checks are separate work.

Metrics name their category and layer, for example `missing_columns.nexus` or
`id_prefixes.nexus.id`. A dependent metric is omitted when its prerequisite is
missing or it is inapplicable; the prerequisite's own metric reports the
problem. Counts for a future ratchet are supplied per metric, e.g.
`schema: {missing_columns.nexus: 1}` under the appropriate model, kind and VPU.

## Adding checks

Register a callable in `CHECKS` in `consistency_check.py` and give it a boolean
`blocking` entry in `checks.yaml`. It receives a local GeoPackage `Path`, the
selected Data Model name, and the output kind; it returns a nonempty mapping of
stable metric names to nonnegative finite numbers. Counts can be supplied for
each metric independently. Checks inspect one Build; the runner owns comparison
to recorded limits and gating.

Run the focused tests, which generate small temporary GeoPackages:

```sh
pixi run -e consistency python -m pytest validation/consistency/tests
```
