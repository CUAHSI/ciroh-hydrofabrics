# Hydrofabric Output Comparison

Tools to compare two pipeline-produced GeoPackages against their official
HydroShare counterparts, so a pipeline run can be checked for regressions:

- A generated **reference hydrofabric**
  (`ngen-workflow/output/v2.2/corrections/16/reference_hydrofabric_fixed.gpkg`)
  vs. the official reference hydrofabric on HydroShare.
- A generated **ngen hydrofabric**
  (`ngen-workflow/output/v2.2/ngen/16/ngen_hydrofabric.gpkg`) vs. the
  official ngen hydrofabric on HydroShare.

Intended to be run locally during development and, eventually, as a GitHub
Action check.

## What it checks

- **Schema**: layer names and geometry types present in each file.
- **Row counts**: per-layer feature counts.
- **Attribute values**: column-by-column comparison of matched features
  (matched by a per-layer id column, e.g. `divide_id` for `divides`).
- **Geometry equality**: coordinate-level comparison (within a tolerance).
- **CRS**: coordinate reference system of each layer.

## Setup

Reference download URLs are configured per version/VPU in
[`reference_sources.yaml`](./reference_sources.yaml), under two groups:

- `ngen_hydrofabric` — the ngen-ready hydrofabric (HydroShare resource
  `bbbabc296b65401ca1f4f3985e4b2b00`).
- `reference_hydrofabric` — the source reference hydrofabric, pre-refactor/
  aggregation (HydroShare resource `563b75efa7614b358a65a7147124e0d7`).

Add a new version entry there before comparing against it.

Requires `geopandas`, `pyogrio`, `shapely`, and `pyyaml` (already declared in
the repo's `pixi.toml`, or run inside the `hydrofabric` Docker Compose
service).

## Usage

Compare a generated ngen hydrofabric:

```sh
pixi run python validation/hf-comparison/compare_hydrofabric.py \
  ngen-workflow/output/v2.2/ngen/16/ngen_hydrofabric.gpkg \
  --remote-hydrofabric-type ngen_hydrofabric \
  --version v2.2 \
  --vpu 16
```

Compare a generated reference hydrofabric:

```sh
pixi run python validation/hf-comparison/compare_hydrofabric.py \
  ngen-workflow/output/v2.2/corrections/16/reference_hydrofabric_fixed.gpkg \
  --remote-hydrofabric-type reference_hydrofabric \
  --version v2.2 \
  --vpu 16
```

Each run downloads (and caches, under `validation/hf-comparison/.cache/`) the matching
official GeoPackage for that version/VPU/group, compares it against the
local file, and writes `report.json`, `report.csv`, and `report.md` to
`validation/hf-comparison/reports/<group>/<version>/<vpu>/`.

Useful flags:

- `--reference-url <url>` — bypass `reference_sources.yaml` and compare
  against an arbitrary reference GeoPackage URL.
- `--remote-hydrofabric-type reference_hydrofabric` — compare against the reference
  hydrofabric datasets (pre-refactor/aggregation) instead of the ngen
  hydrofabric datasets.
- `--fail-on-diff` — exit non-zero if any differences are found (used by CI;
  left off by default for local, informational runs).
- `--force-download` — re-download the reference file instead of using the
  cache.

## GitHub Actions

### PR comparison (`hf_comparison.yaml`)

[`.github/workflows/hf_comparison.yaml`](../../.github/workflows/hf_comparison.yaml)
posts the comparison as a comment on pull requests, to assist reviewers.

1. When opening a PR, fill in the **Hydrofabric comparison** section of the
   [PR template](../../.github/PULL_REQUEST_TEMPLATE.md): the version, the VPU,
   and a public HydroShare URL (`.gpkg` or `.zip`) for a **reference**
   hydrofabric and/or an **ngen** hydrofabric. At most one of each; leave a
   field blank to skip that comparison. (GeoPackages are too large to attach
   to a PR directly.)
2. The workflow parses the description, downloads each file, and runs
   `compare_hydrofabric.py` against the official file for that version/VPU.
3. It posts one comment on the PR (updated on later runs, not duplicated). If
   the report is too long for a GitHub comment it is truncated, with a link to
   the full `report.md`/`report.csv`/`report.json` in the workflow's
   `hydrofabric-comparison-reports` artifact.

Editing the PR description re-runs the comparison. The check is informational:
differences never fail it, and if a file cannot be downloaded or compared, the
comment says so instead. PRs that leave the section blank get no comment.

The pieces are single-purpose scripts in this directory:

| Script | Role |
|---|---|
| `parse_pr_body.py` | Reads and validates the fields in the PR description (HydroShare `https` URLs only). |
| `fetch_and_compare.sh` | Downloads one file, unzips if needed, runs `compare_hydrofabric.py`. |
| `build_pr_comment.py` | Assembles and truncates the PR comment from the reports. |

### Manual run (`validate_hydrofabric.yaml`)

[`.github/workflows/validate_hydrofabric.yaml`](../../.github/workflows/validate_hydrofabric.yaml)
is `workflow_dispatch` only. Enter a version, a VPU, and a public HydroShare
URL for a reference and/or ngen hydrofabric; it runs the same comparison as the
PR workflow and publishes the result in the job summary and as an artifact. No
credentials are needed, since files are downloaded over https.
