# OWP and Lynker Spatial hydrofabric validation: what exists, what is reusable, what is missing

- **Ticket:** CAM-1556 (wayfinder research)
- **Researched:** 2026-11-04
- **Feeds:** "Automated checks Epics" decision (CUAHSI proposal output O2)
- **Method:** Read source code, CI configs, READMEs, and docs in the public GitHub
  repositories listed under [Sources](#sources), plus this repository (read-only).
  Each claim below links to the file that supports it. Repositories were read at
  `HEAD` on the date above; commit SHAs/dates are given where they matter.

---

## Question

What automated validation, consistency, and alignment checks do NOAA OWP and
Lynker Spatial already run on NextGen hydrofabric releases (e.g. v2.2, v2.3), and
with what tooling? Which of those checks are public and reusable, and what gaps
remain that CUAHSI's community-contribution checks (output O2: "a collection of
codes that run in the cloud and perform automated consistency and alignment
checks, designed to evaluate community contributions to hydrofabric datasets")
could fill as a *complement*?

---

## Summary

- **No public QA report or release-gate record exists for the v2.2 or v2.3
  releases.** I found no published validation reports, release notes with QA
  results, or CI that runs against the released GeoPackages. Whatever acceptance
  testing OWP or Lynker ran on v2.2/v2.3 is **not public**.
- **Lynker's `hfutils` (R, Apache-2.0, v0.4.4) holds the most complete public
  check suite:** `hf_check_invariants()` for each stage (refactored, reconciled,
  aggregated, ngen), `hf_check_merge_invariants()` for conservation checks after a
  merge, `hf_check_attr_bounds()` with a bounds CSV of about 66 rows,
  `hf_network_is_dag()`, and `hf_break_cycles()`. The functions were added in
  0.3.3 (first commit 2026-06-16). The vignette calls them "the shared QA gate
  used at each stage of the build pipeline," but the build package that calls
  them is not public (see next bullet).
- **The OWP `hydrofabric` meta-package moved.** `NOAA-OWP/hydrofabric` returns
  404 (as of 2026-11-04). The old code is now `NOAA-OWP/hydrofabric_v2.2`, marked
  "DEPRECATED … no longer maintained," and its README points to a "new"
  `NOAA-OWP/hydrofabric` that is not publicly reachable. CUAHSI's
  `ngen-workflow/Dockerfile` still runs
  `remotes::install_github('NOAA-OWP/hydrofabric')`.
- **OWP/NGWPC's `hydrofabric-builds` (Python) has a `validate_hf` pipeline task.**
  It checks attribute ranges and types with Pydantic for divides and flowpaths,
  counts NaNs per attribute, checks domain lat/lon ranges, and checks
  completeness against reference lists (about 1,600 calibration gages, RouteLink
  gages, NWM lakes, and duplicate lake points). It writes a JSON report and
  **does not fail the build**. Topology is enforced *during* the build: a
  rustworkx graph with `check_cycle=True`, a dendritic assert, and a
  lower-triangular assert.
- **The checks target two different data models.** `hydrofabric-builds` targets
  the NGWPC "NHF" model for NWMv4 (`fp_id`, `div_id`, `Divides`/`Flowpaths`
  layers, virtual flowpaths). The `ngen`-stage checks in `hfutils` expect
  `flowpath_id`/`flowpath_toid` with `fp-`/`cat-` prefixes, which is Lynker's
  newer data model. CUAHSI's products and its comparison tool use the **v2.2**
  schema (`id`/`toid`, `divide_id`). None of the public checks run against
  v2.2-schema files without column mapping.
- **Topology and geometry primitives are public and mature:** `hfutils`
  (`hf_network_is_dag`, `hf_break_cycles`), USGS `hydroloom` 1.3.0
  (`check_hy_graph()` for loops and divergence consistency, `check_valid()` for
  geometry repair), and older OWP `hydrofab` (`network_is_dag`,
  `check_network_validity`). In Lynker's `hfaggregate` (mirrored in CUAHSI's
  fork), the "all toIDs present" check always evaluates `TRUE` because of
  operator precedence (`... == 0 | 1`), so it never fires.
- **Public intake for community contributions is issue-form validation only.**
  Lynker's `community.fabric` repo validates **issue form fields** (required
  fields, lat/lon/EPSG via a coordinate transform) and exports CSVs. It does not
  check any submitted geometry or hydrofabric data.
- **Model-run checks downstream of the fabric are shallow.** CIROH
  `datastreamcli` `run_validator.py` checks the run directory: one GPKG, a
  `divides` layer, per-catchment forcing and config files matching `divide_id`,
  a realization schema (ngen-cal Pydantic), and time alignment. NGIAB's
  `validate_hydrofabric()` only checks that the file exists and is current (S3
  ETag/Last-Modified). Neither checks topology or attributes.
- **CUAHSI today has only a diff against an official release.** The diff covers
  schema, row counts, key-matched attributes, geometry within a tolerance, and
  CRS against v2.2 on HydroShare, and it is informational on PRs. CUAHSI runs no
  checks on the product itself (topology, geometry validity, attribute
  completeness or bounds), and its pinned `hfutils` commit (`f74e9a41`,
  2025-11-03) **predates** `hf_check_invariants`.

---

## Findings

Each category lists the tooling, where it runs, whether it is public and
reusable, and the sources. "Public" means the source code is publicly readable
on GitHub. "Reusable" covers licence, language, and data-model fit for CUAHSI's
v2.2-schema products.

### Overview

| Category | Lynker `hfutils` | OWP/NGWPC `hydrofabric-builds` | Other public tooling | Runs on released v2.2/v2.3? |
|---|---|---|---|---|
| Schema / data model | `write_hydrofabric(enforce_dm=)` column presence (needs external `hf_dm`); `validate_metadata()` for GeoParquet | Pydantic `Divides`/`Flowpaths` models (types + ranges) | `hydrofabric_v2.2` `hf_dm`; `icefabric` PyIceberg schemas; `hfdatamodel` docs | Not public / not found |
| Topology / network | `hf_check_invariants` (dup IDs, dangling toids, fp->nexus->fp DAG, flow direction, hydroseq), `hf_network_is_dag`, `hf_break_cycles` | Build-time rustworkx `check_cycle`, dendritic + lower-triangular asserts | `hydroloom::check_hy_graph`, `hydrofab::network_is_dag`, `hfaggregate::check_network_validity`, `hfngen` `stopifnot(network_is_dag)` | Not public / not found |
| ID stability / crosswalks | `mainstem_id` population, ID prefix checks, reconciled-member lineage | Calibration gage, RouteLink gage, NWM lake coverage; lake-duplicate check | — | Not public / not found |
| Geometry | Divide area > 0, interior-ring count, flowpath-in-catchment coverage, CRS consistency, `clean_geometry` | `_validate_and_fix_geometries` (make_valid, raise if still invalid) | `hydroloom::check_valid`, `hydrofab::fast_validity_check` | Not public / not found |
| Attribute completeness / bounds | `hf_check_attr_bounds` + bounds CSV; slope/So > 0; DA populated and accumulating | NaN counts per attribute (by veg type); Pydantic range checks | — | Not public / not found |
| Alignment with reference / official | Merge conservation (counts, area, VPUs) vs inputs | Coverage vs reference gage/lake lists | — | Not public / not found |
| Model-run | slope/So > 0 ("routing requires it") | — | `datastreamcli` `run_validator.py`; NGIAB `validate_hydrofabric()` (presence only) | Runs per model run, not per release |

### 1. Schema / data model

**Lynker Spatial**
- `hfutils::write_hydrofabric(enforce_dm = FALSE)` can check column presence
  against an `hf_dm` object, but "`hf_dm` is not shipped with hfutils, so enable
  this only when a caller (e.g. the `hydrofabric` build package) provides `hf_dm`"
  ([`R/hfio.R`](https://github.com/lynker-spatial/hfutils/blob/main/R/hfio.R),
  NEWS 0.3.4). The check is off by default.
- `validate_metadata()` does "basic checking of key geo metadata columns" for
  GeoParquet. It is internal and adopted from `sfarrow`
  ([`man/validate_metadata.Rd`](https://github.com/lynker-spatial/hfutils/blob/main/man/validate_metadata.Rd)).
- `gpkg_set_version()` / `gpkg_get_version()` write a dataset semver, a packed
  integer version, an SPDX licence, and an optional JSON provenance record into
  the GeoPackage metadata tables. This supports provenance but is not itself a
  check ([NEWS 0.3.3](https://github.com/lynker-spatial/hfutils/blob/main/NEWS.md);
  [vignette](https://github.com/lynker-spatial/hfutils/blob/main/vignettes/cloud-and-versioning.Rmd)).
- The data model is documented, not machine-enforced, in
  [`lynker-spatial/hfdatamodel`](https://github.com/lynker-spatial/hfdatamodel/blob/main/docs/data_model.md)
  (an mkdocs site with an ERD). It states uniqueness rules in prose (for
  example, "`hl_reference` … Unique across the model"). I found no validation
  code in that repository.
- **Where it runs:** in the R session of whoever calls it.
  **Public/reusable:** yes (Apache-2.0), but the `hf_dm` it needs lives
  elsewhere.

**NOAA OWP / NGWPC**
- `hydrofabric-builds` defines Pydantic models `Divides` (about 70 fields with
  types and `gt`/`lt` ranges) and `Flowpaths` (about 30 fields) in
  [`src/hydrofabric_builds/schemas/validate_hydrofabric.py`](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/src/hydrofabric_builds/schemas/validate_hydrofabric.py).
  It applies them row by row with `pandantic` in
  [`pipeline/validate_hf.py`](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/src/hydrofabric_builds/pipeline/validate_hf.py).
  CRS is restricted to one EPSG code per domain (CONUS 5070, AK 3338, HI 32604,
  PRVI 6566).
- The v2.2 data model as an R object lives in `NOAA-OWP/hydrofabric_v2.2`
  ([`data-raw/hf_dm.R`](https://github.com/NOAA-OWP/hydrofabric_v2.2/blob/main/data-raw/hf_dm.R)).
  It defines layer columns and types (for example, `flowpaths`: `id`, `toid`,
  `mainstem`, `order`, `hydroseq`, …). The repository is deprecated.
- [`NOAA-OWP/icefabric`](https://github.com/NOAA-OWP/icefabric) defines typed
  PyIceberg schemas (with `required=` flags) for both the v2.2 layers
  (`docs/schemas/hf_v22/*`) and the NHF layers, plus snapshot tables for
  versioning (`src/icefabric/schemas/iceberg_tables/`). The schema is enforced
  when data is written to Iceberg. It is not a QA report.
- **Where it runs:** `validate_hf` is the last task of the NHF build DAG (its
  docstring describes an Airflow-compatible context). **Public/reusable:** yes
  (repo public; see the repo's `LICENSE`), but the schema is NHF, not v2.2.

### 2. Topology / network

**Lynker Spatial (`hfutils`)**
- `hf_check_invariants(stage, …, strict = TRUE)`
  ([`R/hf_invariants.R`](https://github.com/lynker-spatial/hfutils/blob/main/R/hf_invariants.R)):
  - `refactored` stage: unique `flowpath_id`; no `flowpath_toid` pointing to a
    missing ID; unique reconciled `ID`; every reconciled group has members, and
    those members exist in the refactored set.
  - `reconciled` stage: flow direction. Endpoint-to-startpoint distance over
    100 m to the downstream reach is classified as either "reversed" or
    "disconnected."
  - `aggregated` stage: unique flowpath and divide IDs.
  - `ngen` stage: `fp-` and `cat-`/`lnd-` ID prefixes; the
    **flowpath→nexus→flowpath graph is a DAG**; `hydroseq` is ≤0.5% NA and has
    no duplicates.
- `hf_network_is_dag()`, `hf_assert_network_dag()`, and `hf_break_cycles()`.
  `hf_break_cycles()` finds strongly connected components and points the
  back-edge `toid` to `"0"`
  ([man pages](https://github.com/lynker-spatial/hfutils/tree/main/man)).
- `upstream_index()` / `hf_upstream_index()` flag divergences and cycles
  instead of mis-indexing them (NEWS 0.4.2).
- **Where it runs:** called between pipeline steps. In `hfutils` CI (R-CMD-check
  on 3 OSes and test-coverage), it runs only on synthetic fixtures
  ([`tests/testthat/test-invariants.R`](https://github.com/lynker-spatial/hfutils/blob/main/tests/testthat/test-invariants.R)).
- **Public/reusable:** yes (Apache-2.0, R). The column names follow Lynker's
  newer model (`flowpath_id`/`flowpath_toid`, `fp-` prefix), so v2.2-schema
  files (`id`/`toid`) need a rename shim.

**Lynker build packages**
- `hfaggregate::check_network_validity()` calls
  `hfutils:::network_is_dag()` and is meant to stop on "All toIDs are not
  present in network." As written,
  `CONNECTION <- sum(!(...)) == 0 | 1` always evaluates to `TRUE`, so the
  connectivity half never fires. A code comment says this is meant to allow a
  subset outlet. The same line appears in CUAHSI's fork
  ([lynker `R/network.R` L183–216](https://github.com/lynker-spatial/hfaggregate/blob/main/R/network.R);
  [CUAHSI fork L205](https://github.com/CUAHSI/hfaggregate/blob/main/R/network.R)).
- `hfngen::build_nextgen()` runs
  `stopifnot(hydrofab:::network_is_dag(...))` on the NextGen flowpaths and on the
  flowline topology
  ([`R/build_nextgen.R` L146–157](https://github.com/lynker-spatial/hfngen/blob/main/R/build_nextgen.R)).
  It depends on OWP's `hydrofab` package, which was last committed 2024-12-06.
- `hfsubset/scripts/diag_graph.R` is an ad hoc diagnostic: NA counts in
  `flowpath_toid`/`nexus_toid` and an igraph build. It reads a local
  `v3.0/ls-modeling-fabric.gpkg`, which indicates Lynker is developing v3.0. It
  is not automated.

**NOAA OWP / NGWPC (`hydrofabric-builds`)**
- [`hydrofabric/graph.py`](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/src/hydrofabric_builds/hydrofabric/graph.py)
  builds `rx.PyDiGraph(check_cycle=True)`, so adding an edge that would create a
  cycle raises an error. `_detect_cycles()` asserts that every non-terminal node
  has exactly one successor ("not dendritic" otherwise) and that the
  topologically sorted adjacency matrix is lower-triangular.
- `hydrofabric/anomalies.py` hard-codes about 20 handlers for specific
  reference flowpath IDs that need special treatment during tracing. This is
  manual curation, not a check.
- Tests cover synthetic and real-world trace cases (braided rivers, Hudson,
  Sioux Falls, coastal no-divide) in `tests/data/trace_cases/`. CI
  ([`.github/workflows/cicd.yaml`](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/.github/workflows/cicd.yaml))
  runs `ruff` and `pytest` on push/PR. It does not run on built products.

**USGS / older OWP**
- [`DOI-USGS/hydroloom`](https://github.com/DOI-USGS/hydroloom) 1.3.0:
  `check_hy_graph()` "check[s] that a network graph doesn't contain localized
  loops and, optionally, that its divergence attributes are internally
  consistent." It verifies that divergence is in {0,1,2}, that each node with
  more than one outgoing feature has exactly one primary path, and so on.
  `sort_network()` also detects cycles.
- [`NOAA-OWP/hydrofab`](https://github.com/NOAA-OWP/hydrofab/blob/main/R/hyaggregate_utils.R):
  `network_is_dag()`, `check_network_validity()`, and `describe_hydrofabric()`.
  This is the older OWP R package. Its last commit was 2024-12-06.
- **Public/reusable:** yes (hydroloom is CC0 per USGS policy; verify the
  licence before vendoring).

### 3. ID stability / crosswalks

- **`hfutils`:** `mainstem_id_populated` (at most 5% NULL; mainstem_id "is a
  global reference levelpath id that must propagate intact through every stage")
  and `reconciled_members_exist` (lineage from reconciled groups back to
  refactored/split COMIDs) in
  [`hf_invariants.R`](https://github.com/lynker-spatial/hfutils/blob/main/R/hf_invariants.R).
  `upstream_id`/`num_upstreams` are explicitly "build-specific and … not
  persistent keys" (NEWS 0.4.2).
- **`hydrofabric-builds`:** `validate_calibration_gages()` reports calibration
  gages missing from the `Gages` layer and gages with no `fp_id` or
  `virtual_fp_id`. `validate_routelink_gages()` does the same against NWM
  RouteLink gages. `validate_lakes()` reports NWM/LAKEPARM lakes missing from
  `lakes`, lakes with no flowpath, and **duplicate lake points** inside a
  buffered NWM lake polygon
  ([`validate_hf.py`](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/src/hydrofabric_builds/pipeline/validate_hf.py)).
  The README documents the reference crosswalk columns (`ref_fp_id`, `dam_id`,
  `site_no`, `nhd_feature_id`)
  ([README](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/README.md)).
- **Release-to-release ID stability:** I found **no public tool** from OWP or
  Lynker that compares feature IDs between hydrofabric versions (for example,
  v2.2 → v2.3) or publishes an ID crosswalk between releases. Not found does not
  mean it does not exist privately.

### 4. Geometry

- **`hfutils` (`hf_check_invariants`):**
  - Every reconciled flowline has a network divide.
  - Network divides have an area of at least 1 m².
  - No divide has more than 50 interior rings ("raster artifacts").
  - Optional `coverage = TRUE`: at least 90% of each flowpath's length lies
    inside its assigned divide.
  - `lake_spatial_consistent`: a flowpath tagged with a `lake_id` lies within
    about one lake-extent (minimum 1 km) of that lake.
  - `hf_check_merge_invariants(gpkg=)` checks for a single CRS across *every*
    spatial layer, read from `gpkg_geometry_columns`.

  `clean_geometry()` and `union_polygons()` repair rather than check. In
  0.4.2, `union_polygons()` was changed to an exact dissolve after a measured
  20 km² of overlap between neighbouring groups on one CONUS VPU (NEWS 0.4.2).
- **`hydrofabric-builds`:** `_validate_and_fix_geometries()` runs
  `make_valid(method="structure")` on invalid geometries and raises an error if
  any remain invalid
  ([`graph.py` L13–49](https://github.com/NOAA-OWP/hydrofabric-builds/blob/main/src/hydrofabric_builds/hydrofabric/graph.py)).
- **USGS `hydroloom::check_valid()`** validates and repairs geometry, unifies
  geometry types, and handles GEOMETRYCOLLECTION artifacts.
- **Not found anywhere public:** checks for overlaps or gaps between divides
  (tiling), checks that divides stay inside a VPU or domain boundary, or
  self-intersection reports for the released products.

### 5. Attribute completeness / plausibility

- **`hfutils::hf_check_attr_bounds()`** checks each attribute against physical
  ranges from
  [`inst/extdata/divide_attr_bounds.csv`](https://github.com/lynker-spatial/hfutils/blob/main/inst/extdata/divide_attr_bounds.csv).
  The CSV has 66 data rows with columns
  `layer,domain,attribute,lower,upper,…,caveat,aliases`, plus `lat`/`lon` per
  domain. The `aliases` column maps naming differences (for example, `lengthkm`
  ↔ `length_km`). The check is soft (it warns and never aborts) and is off by
  default inside `hf_check_invariants(attr_bounds = TRUE)`.
  - Its bounds match `hydrofabric-builds`' Pydantic ranges, e.g. `bexp_mode`
    2–15, `dksat_geomean` 1.95e-07–1.41e-03, `psisat_geomean` 0.036–0.955, and
    `cwpvt_mean` 0.09–0.36. *Inference:* one table was derived from the other,
    or both from a shared NGWPC source.
  - The `ngen` stage adds `slope_valid` and `So_valid` (strictly > 0, "routing
    requires it").
  - `hf_check_merge_invariants()` checks that `total_dasqkm` is never NA, is at
    least the flowpath's own area, and is > 0 where the flowpath has a
    catchment. It also flags as informational when drainage area does not
    appear to accumulate.
- **`hydrofabric-builds` `validate_layer()`** reports:
  - total rows;
  - rows with any NaN;
  - NaN counts per attribute;
  - for divides, NaN counts broken down by dominant vegetation type
    (`ivgtyp_mode`);
  - every Pydantic range or type violation.

  The output goes to `nhf_{version}_validation.json`. The README describes it
  as "number of null divide attributes, number of attributes out of defined
  minimum and maximum range, and assertions that necessary lakes and gages are
  present and assigned to flowpaths."
- **Public/reusable:** yes for both. The Pydantic models use NHF column names.
  The `hfutils` CSV is easier to adopt because of its `aliases` column.

### 6. Alignment with reference / official releases

- **Merge conservation (`hfutils::hf_check_merge_invariants`):**
  - all expected VPUs are present;
  - every feature is tagged with a `vpuid`;
  - flowpath and divide counts equal the sum of the per-VPU inputs;
  - divide area is conserved within 0.5%;
  - one CRS is used throughout.

  This aligns a merged product with its *own inputs*, not with an official
  prior release.
- **Coverage against authoritative lists (`hydrofabric-builds`):** see §3
  (calibration gages, RouteLink, NWM lakes).
- **Diff against a prior official release:** I found **no public OWP or Lynker
  tool** that diffs a candidate fabric against the published v2.2/v2.3 product
  (layer/feature/attribute/geometry changes). The closest public artifact is
  CUAHSI's own `validation/hf-comparison/` (see below).
- **v2.3 status:** v2.3 is served through Lynker's authenticated proxy
  (`https://proxy.lynker-spatial.com/hydrofabric/v{version}/…`). `hfsubset`
  explicitly refuses v2.2 ("Subsetting version 2.2 is not supported by this
  implementation")
  ([`R/store-lynker-spatial.R`](https://github.com/lynker-spatial/hfsubset/blob/main/R/store-lynker-spatial.R)).
  I could not find public v2.3 release notes or a QA summary. The Lynker
  hydrofabric site (`hydrofabric.lynker-spatial.com`) is a JavaScript single-page
  app, and I could not extract release information from it.

### 7. Model-run checks

- **CIROH `datastreamcli`**
  ([`src/datastreamcli/run_validator.py`](https://github.com/CIROH-UA/datastreamcli/blob/main/src/datastreamcli/run_validator.py),
  HEAD `d59279e2`, 2026-10-28) checks:
  - exactly one `.gpkg` in the run's config directory;
  - the `divides` layer reads and supplies the `divide_id` list;
  - per-catchment forcing and BMI config files match the realization's
    filename patterns for every `divide_id`;
  - the realization parses against the ngen-cal `NgenRealization` Pydantic
    model and its paths exist;
  - forcing start, end, and timestep match the realization;
  - t-route config times match.

  It checks consistency between the fabric and the model inputs, not the
  fabric's topology or attribute values. Lynker maintains it (commit author
  `@lynker.com`).
- **NGIAB `NGIAB_data_preprocess`**
  ([`modules/data_sources/source_validation.py`](https://github.com/CIROH-UA/NGIAB_data_preprocess/blob/main/modules/data_sources/source_validation.py)):
  `validate_hydrofabric()` only checks that `conus_nextgen.gpkg` exists and
  compares S3 `ETag`/`Last-Modified` against the downloaded copy (bucket
  `communityhydrofabric`). `gpkg_utils.verify_indices()` checks the GPKG
  indices.
- **`hfutils`'s slope/So > 0 checks** (§5) are the only fabric-level checks I
  found that are explicitly motivated by routing.
- **Not found:** any public CI that runs ngen or t-route on a sample of a
  candidate hydrofabric release as a release gate.

---

## What CUAHSI already has

All paths are relative to this repository.

- **Diff against an official release:** `validation/hf-comparison/`
  - `compare_hydrofabric.py` compares a local GPKG with an official one per
    version and VPU. It checks:
    - layer names and geometry types;
    - row counts per layer;
    - attribute values, matched on per-layer key columns;
    - geometry equality at the coordinate level, within a tolerance;
    - CRS.
  - `render_changes.py` maps the changed features. Output is
    `report.json`/`.csv`/`.md`.
  - `reference_sources.yaml` lists **v2.2 only**:
    - ngen hydrofabric: HydroShare resource
      `bbbabc296b65401ca1f4f3985e4b2b00`;
    - reference hydrofabric: HydroShare resource
      `563b75efa7614b358a65a7147124e0d7`;
    - key columns: `id`, `divide_id`, `hl_id`, and `[id, hl_link]` for the
      reference `network` table.
- **CI:**
  - `.github/workflows/hf_comparison.yaml` runs on pull requests. It parses the
    PR body (HydroShare HTTPS links only), runs `fetch_and_compare.sh`, and
    posts a sticky PR comment. It is **informational only**: the
    `--fail-on-diff` flag exists but is not used.
  - `validate_hydrofabric.yaml` is a manual (`workflow_dispatch`) version of
    the same.
- **Topology fixes (applied, not checked):**
  `ngen-workflow/Python/topology_fix.py` applies
  `ngen-workflow/data/corrections/topology.csv`.
- **Model smoke test:** `test/ngen-simulation-test/` is a manual, local
  NGIAB run. It uses `prepare-ngiab.sh` and `run-ngiab.sh` with CFE configs for
  `cat-2861391` and `cat-9475`, has hard-coded local paths, and is not in CI.
- **Not present:**
  - checks on the product itself: DAG/cycles, dangling `toid`, orphan divides,
    duplicate IDs, geometry validity, divide overlap or gaps, attribute
    completeness or bounds;
  - provenance or version stamping in outputs;
  - checks that a contribution keeps IDs stable.
- **Dependency pins** (in `ngen-workflow/Dockerfile`):
  - `hfutils@f74e9a41`, dated 2025-11-03 ("ready for open-source"). This
    predates `hf_check_invariants` (first commit 2026-06-16, released in
    0.3.3) and `hf_check_attr_bounds`, so those functions are **not
    available** in the current image.
  - `remotes::install_github('NOAA-OWP/hydrofabric')` points at a repo that
    returns 404 as of 2026-11-04.

---

## Gaps and implications for the "Automated checks Epics" decision

These are facts and options only. This document does not make the decision.

### Gaps (relative to what O2 needs)

1. **Neither OWP nor Lynker runs a public release gate.** The public checks are
   either unit tests on fixtures (`hfutils`, `hydrofabric-builds` CI) or build
   tasks that write reports (`validate_hf` JSON). Neither runs automatically
   against a *submitted* fabric or a released product. The QA actually applied
   to v2.2/v2.3 is not public.
2. **No public tooling targets the v2.2 schema, which CUAHSI uses.**
   `hydrofabric-builds` targets NHF, and the `hfutils` `ngen` stage targets
   Lynker's `flowpath_id`/`fp-` model. CUAHSI's products and its comparison
   tool use v2.2 `id`/`toid`/`divide_id`.
3. **Contribution-oriented checks are missing everywhere:**
   - ID stability between a contribution and its base release (which IDs were
     added, removed, or re-pointed);
   - checks that changes stay local (edits confined to the declared area of
     interest);
   - a diff that understands topology (upstream and downstream effects of a
     `toid` change).

   `community.fabric` validates only the issue form, not the data.
4. **Some geometry checks exist nowhere public:** gaps or overlaps between
   divides, consistency of the divide boundary with the VPU, and drainage-area
   consistency against an *external* reference (e.g. NLDI/NWIS drainage area
   at gages).
5. **Model-run checks** stop at consistency between files and IDs
   (`datastreamcli`) or at whether the file exists (NGIAB). No public automated
   "does ngen/t-route run on this subset" gate exists, and CUAHSI's smoke test
   is manual.
6. **CUAHSI's own toolchain is behind:** the `hfutils` pin predates the
   invariants, the `NOAA-OWP/hydrofabric` install points at a 404 repo, and the
   PR diff never fails a check.

### Options (not ranked)

- **A. Adopt `hfutils` invariants directly.** Bump the `hfutils` pin to v0.4.4
  or later. Call `hf_check_invariants()` between existing pipeline stages
  (refactor → reconcile → aggregate → hfngen) and add
  `hf_check_merge_invariants()` and `hf_check_attr_bounds()`.
  - *For:* the work is already done, upstream maintains it, and it is R, like
    the pipeline.
  - *Against:* it needs a v2.2 column-rename shim, its behaviour may change
    upstream, and it covers build integrity rather than contribution review.
- **B. Port or vendor selected checks into a Python validator** that sits next
  to `validation/hf-comparison/`. Candidates: DAG/dangling-toid,
  orphan-divide, CRS, NaN/bounds using the `hfutils` CSV or the Pydantic
  ranges, and gage/lake coverage.
  - *For:* it can run in GitHub Actions against any submitted GPKG regardless
    of how the contributor built it, and it matches the existing PR-comment
    workflow.
  - *Against:* it duplicates upstream logic, and the ported checks will drift
    from upstream over time.
- **C. Build contribution-specific checks that complement OWP/Lynker,** where
  §Gaps 3–4 show no public tooling exists:
  - ID-stability or crosswalk diff against the base release;
  - an "edit footprint" check (changes limited to the declared area);
  - an upstream/downstream impact report for a `toid` change;
  - divide tiling (gaps/overlaps);
  - drainage-area comparison against gage or NLDI references.

  These could combine with A or B for the basic integrity layer.
- **D. Add an automated model-run gate.** Automate the existing NGIAB smoke
  test, or call `datastreamcli`'s `run_validator`, on a subset around each
  changed feature in CI or on CUAHSI cloud resources.
  - *Cost:* containers and runtime. It would be the first public run-based
    gate.
- **E. Make existing checks blocking:** use `--fail-on-diff` or severity
  thresholds in `hf_comparison.yaml`, and add v2.3 to `reference_sources.yaml`
  once a public v2.3 download URL exists. (v2.3 is currently behind Lynker's
  authenticated proxy.)
- **F. Coordinate upstream:** ask OWP/NGWPC and Lynker whether their release QA
  (the private `hydrofabric` build package, and `validate_hf` reports for
  released products) can be published, so CUAHSI can align severity levels and
  avoid duplicate work.

### Open questions to resolve before deciding

- Which schema will community contributions target: v2.2, Lynker's v2.3/v3.0
  model, or the NGWPC NHF model? This decides which public checks fit without a
  shim.
- Is the new `NOAA-OWP/hydrofabric` repository private or unpublished, and will
  it be public? Its README presumably shows how OWP uses
  `hf_check_invariants`.
- Will v2.3 (and later releases) be published openly, e.g. on HydroShare, so it
  can serve as a comparison baseline?

---

## Sources

All accessed 2026-11-04. Branch `HEAD` unless noted.

**NOAA OWP / NGWPC**
- `NOAA-OWP/hydrofabric-builds`, HEAD `15d48484` (2026-09-24); `validate_hf.py`
  last changed 2026-08-05 —
  https://github.com/NOAA-OWP/hydrofabric-builds
  - `src/hydrofabric_builds/pipeline/validate_hf.py`
  - `src/hydrofabric_builds/schemas/validate_hydrofabric.py`
  - `src/hydrofabric_builds/hydrofabric/graph.py`,
    `src/hydrofabric_builds/hydrofabric/anomalies.py`
  - `.github/workflows/cicd.yaml`, `README.md` ("Validation" section)
- `NOAA-OWP/hydrofabric_v2.2` (README deprecation notice; `data-raw/hf_dm.R`) —
  https://github.com/NOAA-OWP/hydrofabric_v2.2
- `NOAA-OWP/hydrofabric`: HTTP 404 from both `github.com` and `api.github.com`
  on 2026-11-04.
- `NOAA-OWP/hydrofab` (`R/hyaggregate_utils.R`; last commit 2024-12-06) —
  https://github.com/NOAA-OWP/hydrofab
- `NOAA-OWP/icefabric` (`src/icefabric/schemas/iceberg_tables/*`,
  `docs/schemas/hf_v22/*`, `docs/schemas/nhf/*`) —
  https://github.com/NOAA-OWP/icefabric
- `NOAA-OWP/reference-builds` (only `cicd.yaml`; no validation files found by
  path search) — https://github.com/NOAA-OWP/reference-builds

**Lynker Spatial**
- `lynker-spatial/hfutils` v0.4.4, HEAD `e5319ac3` (2026-09-30);
  `R/hf_invariants.R` first commit 2026-06-16, last 2026-08-28 —
  https://github.com/lynker-spatial/hfutils
  - `R/hf_invariants.R`, `R/hf_attr_bounds.R`,
    `inst/extdata/divide_attr_bounds.csv`, `R/gpkg_metadata.R`, `R/hfio.R`
  - `NEWS.md` (0.3.3, 0.3.4, 0.4.2, 0.4.4),
    `vignettes/cloud-and-versioning.Rmd`, `tests/testthat/test-invariants.R`
  - pkgdown site: https://lynker-spatial.github.io/hfutils/
- `lynker-spatial/hfutils` commit `f74e9a41` (2025-11-03, "ready for
  open-source"), the commit pinned by CUAHSI.
- `lynker-spatial/hfaggregate` `R/network.R` —
  https://github.com/lynker-spatial/hfaggregate
- `lynker-spatial/hfngen` `R/build_nextgen.R` —
  https://github.com/lynker-spatial/hfngen
- `lynker-spatial/hfsubset` (`R/store-lynker-spatial.R`,
  `scripts/diag_graph.R`) — https://github.com/lynker-spatial/hfsubset
- `lynker-spatial/hfdatamodel` (`docs/data_model.md`) —
  https://github.com/lynker-spatial/hfdatamodel
- `lynker-spatial/community.fabric`, HEAD `426fdbc1` (2025-10-24) (`README.md`,
  `.github/workflows/export-hydrofabric-issues.yml`,
  `.github/scripts/export_hydrofabric_issues.py`) —
  https://github.com/lynker-spatial/community.fabric
- `lynker-spatial/docs` (`docs/data-service/hydrofabric.md`; no QA content) —
  https://github.com/lynker-spatial/docs
- https://hydrofabric.lynker-spatial.com/ (JavaScript single-page app; no
  extractable release or QA content).

**USGS**
- `DOI-USGS/hydroloom` v1.3.0 (`R/check_hy_graph.R`, `R/check_valid.R`,
  `NAMESPACE`) — https://github.com/DOI-USGS/hydroloom
- `DOI-USGS/gfv2.0`: HTTP 404 (reference-fabric build QA could not be
  inspected).

**CIROH**
- `CIROH-UA/datastreamcli`, HEAD `d59279e2` (2026-10-28)
  (`src/datastreamcli/run_validator.py`) —
  https://github.com/CIROH-UA/datastreamcli
- `CIROH-UA/NGIAB_data_preprocess`
  (`modules/data_sources/source_validation.py`,
  `modules/data_processing/gpkg_utils.py`) —
  https://github.com/CIROH-UA/NGIAB_data_preprocess
- CIROH DocuHub hydrofabric page: **not located**. The guessed URL and
  `docs.ciroh.org/sitemap.xml` both returned 404.

**This repository (read-only)**
- `validation/hf-comparison/` (`compare_hydrofabric.py`, `render_changes.py`,
  `reference_sources.yaml`, `fetch_and_compare.sh`, `parse_pr_body.py`,
  `build_pr_comment.py`)
- `.github/workflows/hf_comparison.yaml`,
  `.github/workflows/validate_hydrofabric.yaml`
- `ngen-workflow/Dockerfile`, `ngen-workflow/Python/topology_fix.py`,
  `ngen-workflow/data/corrections/topology.csv`
- `test/ngen-simulation-test/`

### Could not verify / not public
- The QA actually run on the v2.2 and v2.3 releases (no public reports or
  release notes with QA content found).
- The successor `NOAA-OWP/hydrofabric` package (404), and therefore how OWP
  wires `hf_check_invariants` into production builds.
- Any `nhf_{version}_validation.json` report for a released NHF product.
- USGS reference-fabric build QA beyond the public `hydroloom` functions.
- The licence of `hydrofabric-builds` and `hydroloom`. Check each repo's
  `LICENSE` before vendoring code.
