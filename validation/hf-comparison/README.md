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

## GitHub Action

[`.github/workflows/validate_hydrofabric.yaml`](../../.github/workflows/validate_hydrofabric.yaml)
runs both comparisons (reference hydrofabric, then ngen hydrofabric). It
supports:

- `workflow_dispatch` — pick a version/VPU to check both outputs on demand.
- `pull_request` — for PRs that touch pipeline code/params, reproduces the
  `pipelines/v2.2` pipeline and runs both comparisons automatically. This
  needs DVC remote credentials to pull input data; it is skipped gracefully
  if those secrets are not configured on the repository.
