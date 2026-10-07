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

For each layer with geometry, it also renders a map of the changed features
(see [Changed-feature maps](#changed-feature-maps)).

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
service). GitHub Actions installs them from
[`requirements.txt`](./requirements.txt) with pip, because `pixi.toml` only
declares `osx-arm64`; keep that file's version ranges in sync with `pixi.toml`.

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
- `--skip-images` — do not render the changed-feature maps (faster).
- `--fail-on-diff` — exit non-zero if any differences are found (used by CI;
  left off by default for local, informational runs).
- `--force-download` — re-download the reference file instead of using the
  cache.

## Changed-feature maps

For every layer that has geometry (`divides`, `flowpaths`, `hydrolocations`,
...), one PNG is written to
`validation/hf-comparison/reports/<group>/<version>/<vpu>/images/<layer>.png`
and embedded in a **Changed Features** section of `report.md`. Image links in
`report.md` are relative, so keep the `images/` folder next to it.

- **Grey**: every feature of the reference layer.
- **Blue**: features that differ (modified, added, or removed), drawn with the
  new geometry where there is one.
- **Few changes** (50 features or fewer): changes are usually a handful of
  features in a layer of tens of thousands, so when they fall into at most four
  separate areas, a zoomed panel next to the overview shows each area up close
  (changes near each other share a panel). Dashed boxes on the overview mark
  where each panel is. With changes in more areas, only the overview is drawn.
- **Many changes** (more than 50): zoomed panels would be meaningless, so a
  density map (hexagons shaded by the number of changed features) is drawn
  next to the overview. If the changes are concentrated, with a few hotspots
  holding at least half of them (at most four, numbered on the overview),
  each hotspot also gets a zoomed panel. If they are spread out, the density
  map alone describes them.
- Polygon layers (`divides`) use lighter, thinner grey outlines so the blue
  changed polygons stay visible among tens of thousands of neighbours.

Layers without changes get a "No changed features" note instead of an image.
A rendering failure is noted in the report and never stops the comparison.
The maps are in the downloadable report artifact; the PR comment itself only
includes the Schema and Layers tables.

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
3. It posts one comment on the PR (updated on later runs, not duplicated),
   with the time it was created and, for each hydrofabric, the report's
   header details (including the git commit of the PR head being tested) and
   its Schema and Layers tables. The attribute and geometry difference tables
   are not included in the comment. The full `report.md`/`report.csv`/`report.json`
   are in the workflow's `hydrofabric-comparison-reports` artifact, which the
   comment links to.

Editing the PR description re-runs the comparison. The check is informational:
differences never fail it, and if a file cannot be downloaded or compared, the
comment says so instead. PRs that leave the section blank get no comment.

The pieces are single-purpose scripts in this directory:

| Script | Role |
|---|---|
| `parse_pr_body.py` | Reads and validates the fields in the PR description (HydroShare `https` URLs only). |
| `fetch_and_compare.sh` | Downloads one file, unzips if needed, runs `compare_hydrofabric.py`. |
| `build_pr_comment.py` | Builds the PR comment (timestamp, header details, Schema and Layers tables, artifact link) from the reports. |
| `render_changes.py` | Draws the changed-feature map for one layer (used by `compare_hydrofabric.py`). |

### Manual run (`validate_hydrofabric.yaml`)

[`.github/workflows/validate_hydrofabric.yaml`](../../.github/workflows/validate_hydrofabric.yaml)
is `workflow_dispatch` only. Enter a version, a VPU, and a public HydroShare
URL for a reference and/or ngen hydrofabric; it runs the same comparison as the
PR workflow and publishes the result in the job summary and as an artifact. No
credentials are needed, since files are downloaded over https.
