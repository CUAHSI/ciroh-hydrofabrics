# Reading a Consistency Check report

This page explains how to read the report that
`pixi run consistency-check` prints, what PASS, FAIL and INFO mean, and what to
do when a line says FAIL. The per-check pages
([`geopackage_layers`](geopackage-layers.md), [`schema`](schema.md),
[`network`](network.md), [`geometry`](geometry.md),
[`attributes`](attributes.md)) explain each metric.

## A report line

```text
Configuration: validation/consistency/checks.yaml | Recorded counts: validation/consistency/counts.yaml
my-hydrofabric.gpkg | v2.2 | ngen | 01
check | metric | value | recorded count | result | mode
network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory
```

The first line names the configuration and counts files actually used. The
second names the GeoPackage, its Data Model, output kind and VPU. Each later
line is one measurement:

| Field | Meaning |
| --- | --- |
| `check` | The check that took the measurement: `geopackage_layers`, `schema`, `network`, `geometry` or `attributes`. |
| `metric` | The name of the measurement, usually `<category>.<layer>`, for example `dangling_toid.flowpaths` or `violations.divides.areasqkm_positive`. |
| `value` | What the check measured in this GeoPackage. Counts are whole numbers; areas are in square metres (`_m2`). |
| `recorded count` | The limit stored in `counts.yaml` for this Data Model, output kind, VPU, check and metric. `-` for an INFO line, which has no limit. A metric with no recorded count is treated as `0`. |
| `result` | `PASS`, `FAIL` or `INFO` (see below). |
| `mode` | `advisory` or `blocking`, set per check in `checks.yaml`. |

A check measures one Build against itself and its declared Data Model. It does
not compare features with an Official Hydrofabric. The only comparison with
another product is the recorded count, which is a number copied from one.

## Results

| Result | Condition | Effect on the gate |
| --- | --- | --- |
| `PASS` | `value <= recorded count` (a missing count is `0`). | None. |
| `FAIL` | `value > recorded count`. | Fails the run only if the check is `blocking`. |
| `INFO` | The metric is context, not a count that can be limited. | Never affects the gate, even when the check is blocking. |

PASS does not mean the data are correct. A metric with a nonzero recorded
count passes at that value, and also at any lower one (a local run on a NextGen
VPU 03S file printed
`hydroseq_order_indeterminate.network | 33 | 260 | PASS`, where 260 is the
recorded limit and 33 is what that file measured). The
report does not flag an improvement: when a Build lowers a count, the
contributor updates `counts.yaml` (see
[Running and recording](running-and-recording.md#recording-counts)).

FAIL does not mean the feature is wrong. It means the value is above the
limit, which is a different statement; see
[FAIL versus "the data are wrong"](#fail-versus-the-data-are-wrong).

## Advisory and blocking

Every check in `checks.yaml` carries a boolean `blocking` flag, and all are
currently `false`. This follows
[ADR 0001](../adr/0001-consistency-check-gating.md): checks first report to the
reviewer and become required-to-pass only when maintainers switch them on, one
check at a time, in a reviewed change.

- An **advisory** check prints FAIL lines but cannot fail the run. The reviewer
  judges them.
- A **blocking** check makes the run exit `1` when any of its ratcheted metrics
  is above its recorded count.

### Worked example: the same file, advisory and blocking

A GeoPackage has a single flowpath `wb-1` whose `toid` is `nex-9`, a nexus that
does not exist, and a nexus layer with one terminal nexus `tnx-1`. No count is
recorded.

Advisory (the default in `checks.yaml`):

```text
network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory
```

The exit status is `0`.

With `network: {blocking: true}`:

```text
network | dangling_toid.flowpaths | 1 | 0 | FAIL | blocking
```

The exit status is `1`. After recording `dangling_toid.flowpaths: 1` in
`counts.yaml`, the line becomes `1 | 1 | PASS | blocking` and the exit status is
`0`: the Build carries this error forward but does not add to it.

## Exit statuses

| Status | Meaning |
| --- | --- |
| `0` | The run completed and no blocking metric is above its recorded count. FAIL lines in advisory checks, and all INFO lines, do not matter. |
| `1` | The run completed and at least one blocking check has a FAIL. |
| `2` | The run could not complete: an invalid target, configuration, Data Model or download, or a check that could not finish. **An incomplete run is neither a pass nor a fail.** |

Status `2` takes precedence over `1`. An incomplete check prints
`error: <file>: check <name> could not run: <reason>` to standard error and none
of that check's metrics are reported. There is one exception: when divide
topology cannot be calculated, the `geometry` check still prints its other
metrics, omits the `divide_overlaps.*`, `divide_gaps.*` and
`divide_union_area_m2` values, and reports the cause as
`error: <file>: check geometry: <reason>`.
The runner continues with the other files in a batch. Nothing is recorded by
`--record` for a batch with an incomplete file.

### Worked example: an incomplete check

A `divides` layer has two features and the second geometry is NULL. With the
`geometry` check blocking, the report shows:

```text
geometry | null_geometries.divides | 1 | 0 | FAIL | blocking
```

and standard error shows:

```text
error: .../exit2.gpkg: check geometry: divides topology incomplete: null or empty divide geometry
```

The exit status is `2`, not `1`, even though the null count is a blocking FAIL.
The reason is that the overlap and gap values could not be calculated, so the
run says nothing about them.

## FAIL versus "the data are wrong"

A FAIL against the ratchet is not a finding that a feature is defective.
Consider what the line actually states: *this Build has more of the thing than
the limit allows*. The limit is a count recorded from an Official Hydrofabric
(ADR 0001), and the Official Hydrofabrics themselves contain errors that the
checks detect. A Contribution may carry those errors forward but must not add
more.

| The line says | It does not say |
| --- | --- |
| `value > recorded count` | that the extra features are wrong in the real world |
| `FAIL` with no recorded count | that the Build is worse than the official product (the count may not have been recorded yet) |
| `PASS` | that the feature set is correct |

The reverse is also possible. A defect that replaces another one, so the count
does not change, produces PASS. The ADR leaves that case to Alignment Checks
(CAM-1573) and to the reviewer.

## What a reviewer does on a FAIL

1. **Find the metric's definition** on the matching check page and read what it
   counts, including its unit (rows, distinct IDs, square metres).
2. **Compare with the recorded count.** Look at the metric under the same Data
   Model, output kind and VPU in
   [`counts.yaml`](../../validation/consistency/counts.yaml). If there is no
   entry, the limit is `0`, which is the case for a VPU whose official counts
   have not been recorded.
3. **Check the value against known causes** (next section). A value close to
   the recorded count for the same VPU is usually the same inherited feature.
4. **Look at the change.** If the Contribution is meant to leave the metric
   alone, a higher value is a regression to investigate. If it is meant to
   change the pipeline, look for the intended effect.
5. **Decide.** Fix the cause, or explain in the review why the higher value is
   expected. Raising a recorded count needs the same review as any other change
   to the ratchet. The recording tool can raise limits as well as lower them;
   ADR 0001 expects counts to only fall, and that policy is enforced in review,
   not by the tool.

## Known legitimate causes

The checked-in `counts.yaml` records the values measured on the official v2.2
products. The following are nonzero in many official VPUs; the figures live in
[`counts.yaml`](../../validation/consistency/counts.yaml), not here, so they do
not drift.

| Metric family | Why official products have it |
| --- | --- |
| `network`: `duplicate_primary_ids.nexus` (NextGen), `duplicate_primary_ids.flowpath-attributes` and `duplicate_primary_ids.flowpath-attributes-ml` (NextGen) | NextGen output repeats some nexus and attribute IDs. ADR 0001 cites six duplicate nexus IDs in VPU 16. |
| `network`: `duplicate_primary_ids.divides` (Reference) | A few Reference VPUs repeat divide IDs. |
| `geometry`: `divide_overlaps.*`, `divide_gaps.*`, `duplicate_geometries.nexus` | Official divides overlap, leave interior gaps and share nexus points. ADR 0001 cites overlaps of up to 11.7 km² in VPU 16. |
| `geometry`: `duplicate_geometries.hydrolocations` (NextGen) | `hydrolocations` has one row per referenced location (a gage, a HUC12, and so on), and a point of interest can have several, all at one point. In all 21 official VPUs, 96.3% of the extra rows (45,225 of 46,946) are distinct referenced locations sharing a point, and the other 1,721 (3.7%) are exact repeated rows, a minor defect in the official product; the per-VPU counts are in the linked section. See [`geometry`](geometry.md#duplicate-geometries-in-official-nextgen-hydrolocations). |
| `network`: `divides_without_flowpaths` and its `.has_flowline_0` subset, `flowpaths_without_divides` and its `.has_divide_0` subset | Some official features are intentionally without a flowline or a divide, such as coastal and no-flowline divides. These are orphan features. |
| `network`: `hydroseq_order_*` (NextGen and Reference) | The official products contain flowpath edges whose sequence is not ordered as the check expects, or that cannot be compared. |
| `network`: `hydroseq_order_indeterminate.network`, `dnhydroseq_indeterminate.network` (Reference; the first is also nonzero for NextGen) | Network rows that cannot be compared are indeterminate. In Reference, every network row is labelled `fl-fl`; the indeterminate rows are those whose `toid` is not a flowpath in the VPU, the same rows as `dangling_toid.network` (seven VPUs). |
| `geometry`: `duplicate_geometries.hydrolocations` (Reference) | The same cause as in NextGen: `hydrolocations` has one row per referenced location (a gage, a HUC12, a dam, and so on, each with its own `hl_id`), and several referenced locations can be at one point. In all 21 official VPUs the recorded count equals the number of extra rows at a shared point, no two rows are alike apart from `fid` and `hl_id`, and 29,680 of the 29,687 extra rows add an `hl_reference` not yet at their point. The other 7 (VPUs 03W, 07 and 09) repeat an `hl_reference` already at the point, but for a different point of interest on a different flowpath. Of the extra rows, 17,215 are further locations of a point of interest already at the point, and 12,472 belong to a different point of interest, with rows on more than one flowpath at that point. Reference has no `nex_id` column. |
| `network`: `duplicate_primary_ids.flowpaths`, `duplicate_network_rows`, `reciprocal_divide_flowpath_ambiguous` and the `*_ambiguous` metrics (Reference) | A few Reference VPUs repeat flowpath IDs or network rows, which makes the matching ambiguous. |
| `network`: `dangling_toid.*`, `cycle_nodes.*` | A few official VPUs have links that do not resolve within the VPU, or cycles. |
| `schema`: `unobserved_id_prefixes.network.toid` (NextGen) | Observed prefixes are not an allowlist; see [`schema`](schema.md). |
| `attributes`: `violations.divide-attributes.mean.impervious_range` (NextGen) | Some official divides have impervious values outside [0, 100]. |

No official `sentinel.*` count is nonzero at the time of writing, so a nonzero
sentinel count is worth a closer look.
