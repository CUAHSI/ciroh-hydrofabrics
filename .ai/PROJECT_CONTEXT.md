# Project Context: CUAHSI/ciroh-hydrofabrics

## Purpose
This repository builds and manages NOAA/CIROH-style NextGen (ngen) hydrofabrics —
catchment/flowpath datasets used to configure hydrologic models. It combines a
reproducible DVC data pipeline (R + Docker) with a browser-based hydrofabric
subsetting/visualization tool (Vue 3 + MapLibre).

## High-Level Structure

- `ngen-workflow/` — Core hydrofabric build pipeline.
  - `Dockerfile`, `docker-compose.yml` (repo root) — containerized environment
    (`hydrofabric` service, R-based) used to run every pipeline stage; a
    `tippecanoe` service builds vector tiles.
  - `R/`, `Python/`, `bash/` — stage implementation scripts (refactor,
    aggregate, build ngen hydrofabric, attributes, VAA, reconcile, VRT
    mosaics, corrections).
  - `data/` — DVC-tracked inputs: `superconus/` (reference hydrofabric
    divides, flowpaths, hydrolocations, network, POIs, GeoPackage) and
    `NHDSnapshot/` (FAC/FDR rasters by region/VPU).
  - `output/` — Pipeline outputs per run (e.g. `demo/devcon/...`), each stage
    producing an intermediate/final `.gpkg`.
  - `README.md` — Mermaid diagram of the refactor → aggregate → build-ngen
    workflow.
- `pipelines/` — DVC pipeline definitions (`dvc.yaml`, `params.yaml`,
  `dvc.lock`) per scenario, e.g. `pipelines/demo/devcon/`. Stages: reference
  corrections, FAC/FDR VRT builds, refactor, aggregate, hfngen, minimal
  attributes, VAA, reconcile. Also `clean_dvc_cache.py`.
- `subsetter/` — Standalone Vue 3 web app (Vite, no root `package.json` found
  yet — check `subsetter/.pixi`/build config) for interactively viewing and
  subsetting the hydrofabric via PMTiles/parquet served from S3.
  - `src/config.js` — S3 origin, PMTiles URLs, credentials.
  - `src/composables/` — `useMap.js`, `useParquet.js`, `useNetwork.js`.
  - `src/updateMapFilters/` — subsetting logic (`useSubset.js`, `useGpkg.js`)
    and map styling (`light-style.js`, `dark-style.js`).
  - `src/auth.js`, `src/oidc.js` — authentication (OIDC) and S3 request
    signing (SigV4, implemented manually via WebCrypto).
  - Deployed to GitHub Pages via `.github/workflows/deploy_pages.yaml` on
    push to `main` touching `subsetter/`.
- `helpers/` — Data-prep notebooks/scripts, e.g. `S3hsclient.py` and
  `superconus_data.ipynb` for HydroShare S3 data access.
- `scripts/` — One-off analysis/utility scripts (e.g. building GeoPackage
  comparison tables, dumping GeoPackage attribute metadata).
- `subsetter/` (map/parquet dirs), `test/`, `tests/` — sample outputs and
  smoke tests (e.g. `ngen-simulation-test`).
- `.dvc/`, `.dvcignore`, `pixi.toml`/`pixi.lock` — DVC config and a Pixi
  (conda-forge) environment for Python tooling (geopandas, pynhd,
  pygeohydro, jupyterlab, dvc-s3, awscli).

## Data & Reproducibility Workflow
1. Data inputs live in HydroShare-backed S3 storage, tracked via DVC
   (`.dvc` files + `dvc.lock`). Credentials use an AWS profile named
   `hydroshare`.
2. Pipelines are run with `dvc repro pipelines/<scenario>/dvc.yaml`, executing
   stages defined there inside the `hydrofabric` Docker Compose service.
3. Outputs land under `ngen-workflow/output/<output_folder>/...` and are
   checksum-tracked by DVC; `git` stores only lightweight metadata
   (`.dvc`, `dvc.lock`, params/dvc.yaml), while large artifacts live in the
   DVC remote.
4. See root `README.md` for full stage-by-stage documentation and
   `ngen-workflow/README.md` for the pipeline diagram.

## Key External Dependencies
- DVC (+ `dvc-s3`) for data/pipeline versioning.
- R hydrofabric tooling (refactor/aggregate/hydrofabric packages) run inside
  Docker.
- MapLibre GL + PMTiles + DuckDB-WASM (parquet) in the `subsetter` web app.
- Pixi/conda-forge for Python environment management (geopandas stack).

## Notes for Future AI Sessions
- Always check `pipelines/<scenario>/params.yaml` before assuming default
  VPU/output paths.
- `subsetter/` is a separate deployable frontend; changes there trigger a
  GitHub Pages deploy workflow on `main`.
- Root `README.md` is the primary onboarding doc — keep it in sync with any
  pipeline stage changes.
- See `/AGENTS.md` at the repo root for standing instructions to follow in
  this repository.
