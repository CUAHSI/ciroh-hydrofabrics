# Consistency summary: NextGen v2.2, VPU 16

A summary of how the project's VPU 16 NextGen Build compares with the limits
recorded from the official NOAA OWP NextGen v2.2 product. It is a summary of
earlier results, not the output of a new run; see [Provenance](#provenance).

## Result

The Build fails the Consistency Checks against the official limits. The checks
are advisory today (every `blocking` flag in
[`checks.yaml`](../../../validation/consistency/checks.yaml) is false), so these
failures do not block a merge. See [reading a report](../reading-a-report.md).

The Build had 22 FAIL lines for NextGen on `main` at commit `0f0e558` (23 in
the original CAM-1605 run; the extra line was
`geometry | duplicate_geometries.hydrolocations`, which failed only because no
recorded count existed yet and was not a pipeline defect).

## Headline findings

Official values are the counts recorded in
[`counts.yaml`](../../../validation/consistency/counts.yaml). A Build may carry
the official product's errors forward but may not add to them.

| Finding | Official v2.2 | Project Build | Traces to |
| --- | --- | --- | --- |
| Largest divide overlap | 11.7 km² | 535.4 km² | `refactor` |
| Divide gap area, total | 28.2 km² | 29,071 km² | `refactor` |
| Duplicate network rows | 0 | 260,278 | `reconcile` |
| Flowpaths routing to missing nexuses | 0 | 10 | `hfngen` |
| Hydrolocations without a nexus | 0 | 6,473 | `aggregate` |

Also flagged:

| Finding | Official v2.2 | Project Build | Traces to |
| --- | --- | --- | --- |
| `Length_m` disagrees with `lengthkm` by more than 1 m | 0 | 10,856 | flowpath attributes |
| Negative slope (`So`) values | 0 | 28 | `So` sentinel averaged |

These are the headline findings only. The remaining FAIL lines are not listed
here.

## Official baseline

The official VPU 16 product is not clean either: 6 duplicate nexus IDs, divide
overlaps up to 11.7 km², and 1,411 duplicate hydrolocation geometries. See
[ADR 0001](../../adr/0001-consistency-check-gating.md) for why the checks use a
count ratchet rather than zero tolerance.

## Provenance

- Source: the figure `presentations/261209-agu-presentation/figures/vpu16-fail-report.png`
  and `presentations/261209-agu-presentation/consistency-vs-alignment-checks.txt`.
- Run: Jira CAM-1605, rerun on `main` at `0f0e558` against the local Builds.
  The numbers have not been re-run for this document.
- The "Traces to" stage for each finding is inferred from stage outputs and
  code, not confirmed. Read it as "traces to", not "is caused by".
- Fix stories CAM-1665 to CAM-1674, grouped under Epic CAM-1675, cover the
  pipeline defects.
- The full report text is not stored in the repository.

To refresh this summary, run the checker on the Build and compare with the
recorded limits:

```sh
pixi run consistency-check path/to/ngen_hydrofabric.gpkg --type ngen --vpu 16 --data-model v2.2
```
