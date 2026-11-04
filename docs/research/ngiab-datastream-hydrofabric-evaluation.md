# NGIAB and Research DataStream for evaluating hydrofabric changes

- Jira: CAM-1557 (wayfinder research), feeds the "Automated checks Epics" decision
- Researched: 2026-11-04
- Method: I read source code, READMEs and release notes in the CIROH-UA, RTIInternational and JoshCu GitHub repos at the pinned commits listed in [Sources](#sources), and inspected a local community hydrofabric geopackage read-only with `sqlite3`. I did not run NextGen, the preprocessor, DataStreamCLI or TEEHR end to end. Statements marked *(inference)* are reasoned from code and have not been tested.

## Question

What can NextGen In A Box (NGIAB) and the NextGen Research DataStream (NRDS / DataStreamCLI) do **today** to automatically evaluate the effect of a hydrofabric change? That means running NextGen on a modified (community) hydrofabric, comparing the result against a baseline run or observations, and reporting metrics. Which parts are ready, which are University of Alabama (UA)-led and still in progress, and which would CUAHSI have to build?

## Summary

- **No tool evaluates a hydrofabric contribution today.** Nothing in the NGIAB or NRDS ecosystem takes "hydrofabric A vs. hydrofabric B", runs both, and reports the difference. The building blocks exist, but someone would have to put them together, and in places fix them.
- **A custom geopackage can be run.** DataStreamCLI accepts any local, URL or S3 gpkg with `-g` and runs fully headless: it generates BMI configs, computes forcings, validates the run, runs NGIAB, and can optionally run TEEHR. The NGIAB preprocessor added `subset_cli` (`--gpkg_path`) in v4.9.4 to subset an arbitrary gpkg. Its main CLI, however, is still hardcoded to `~/.ngiab/hydrofabric/v2.2/conus_nextgen.gpkg` and prompts interactively.
- **CUAHSI's geopackages already match the v2.2/NGIAB table layout.** The VPU 16 output has the same layers and column order as the preprocessor's `template.sql`, and the `divide-attributes` columns the default CFE + NOAH-OWP realization needs. Run inputs can probably be generated *(inference; not run)*.
- **The gage crosswalk would block evaluation.** In the local CUAHSI gpkg, every one of the 35,255 values in `flowpath-attributes.gage` is an empty string. The NGIAB TEEHR integration finds gages with `SELECT id, gage FROM 'flowpath-attributes' WHERE gage IS NOT NULL`, so it would find no usable USGS gages. The preprocessor's gage-based subsetting and calibrated-parameter lookup need the same field. CUAHSI's pipeline owns this fix whichever way the decision goes.
- **Metrics against observations exist, but are experimental.** `ngiab-teehr` (UA, README says "Warning: This code is experimental!") computes KGE, NSE, relative bias and RMSDR for each USGS gage. It compares the NextGen run against USGS observations and also loads the **NWM v3.0 retrospective as a reference simulation**. Data comes from the TEEHR-Cloud warehouse. It pins `teehr==0.6.2`; the current TEEHR tag is v0.8.0.
- **Run-to-run comparison is only partly built.** `ngiab-teehr` is designed so several runs can write into one TEEHR evaluation as separate configurations, which gives side-by-side metrics. Neither guide script nor DataStreamCLI exposes a shared evaluation directory, and nothing produces a diff report or a pass/fail result.
- **Some integration paths look broken or not ready.** At `ngiab-teehr` main, `teehr_ngen.py` raises an error unless it gets `--data_folder_stem` and `--teehr_evaluation_dir`, but `runTeehr.sh` and DataStreamCLI `-E True` start the container with no arguments. I could not check which code the published `latest` image contains. The preprocessor's `--eval` flag imports `ngiab_eval`, a personal UA prototype whose README says "Please don't use this … don't expect anything other than random numbers".
- **NRDS does not cover community hydrofabric contributions.** NRDS runs daily CONUS forecasts on Lynker Spatial v2.2 only. Its docs say hydrofabric contributions "are made upstream" (`lynker-spatial/community.fabric`, `CIROH-UA/community_hf_patcher`). National-scale performance evaluation is still listed as a planned update, and the docs describe systematic evaluation against observations as "the eventual basis" for accepting contributions.
- **All of this is actively maintained, but not only by UA.** NGIAB-CloudInfra, the preprocessor and ngiab-teehr are UA-staffed. DataStreamCLI and ngen-datastream are in the CIROH-UA org but written by Lynker staff. TEEHR is RTI's. All saw commits in Sept–Oct 2026. None has an open roadmap item for evaluating community hydrofabric contributions (from the READMEs, status pages and docs I read; I did not search issues exhaustively).
- **Name collision.** UA's `community_hf_patcher` publishes a "CIROH Community Hydrofabric" (a patched v2.2 fork in `s3://communityhydrofabric`, which is the preprocessor's default download). This is a different thing from CUAHSI's "Community HydroFabrics". Planning documents should keep the two names apart.

## Findings

### Custom hydrofabric support

**NGIAB_data_preprocess (UA)**, main @ `4088447c` (2026-10-30), release v4.9.4 (2026-10-28):

- `file_paths.py` hardcodes the source hydrofabric as `~/.ngiab/hydrofabric/v2.2/conus_nextgen.gpkg`, plus a precomputed `conus_igraph_network.gpickle`. The main CLI (`python -m ngiab_data_cli`) has no flag for a different hydrofabric.
- `source_validation.py` downloads `s3://communityhydrofabric/hydrofabrics/community/conus_nextgen.tar.gz`. When the remote ETag differs from the local copy, it prompts to re-download. If a user accepts, a gpkg they swapped in is overwritten. A `no_update` sentinel file turns the check off.
- `subset_cli.py` (PR #256, shipped in v4.9.4) takes `--cat_id --gpkg_path --output_path`, so it **can subset an arbitrary gpkg**. For a non-default gpkg it builds or uses `hydrofabric_graph.gpickle` next to that file.
- Subsetting copies tables with positional `INSERT … VALUES (?, …)` into a `template.sql` schema, so the input gpkg's **column order must match v2.2 exactly**.

**DataStreamCLI (CIROH-UA org, Lynker author)**, main @ `d59279e2` (2026-10-28):

- `-g/--GEOPACKAGE` takes a local path, URL or S3 URI to *any* gpkg. That gpkg is used as the run domain as-is.
- The alternative path (`-I/-i/-v`) calls `hfsubset` with a hardcoded `-v "2.1.1"`, and the README says hfsubset "is currently down". That path only serves official Lynker versions anyway.
- The step-by-step docs list the gpkg layers needed: `divides, flowlines, network, nexus, forcing-weights, flowpath-attributes, divide-attributes`. They use `model-attributes` for versions before v2.2. Whether a v2.2-format gpkg without a `forcing-weights` layer works was **not verified**.

**Local evidence (this repo):**

- `test/ngen-simulation-test/` already contains an ad-hoc NGIAB harness. `copy-hydrofabric-to-ngiab-dir.sh` makes NGIAB use a custom hydrofabric by overwriting `~/.ngiab/hydrofabric/v2.2/conus_nextgen.gpkg` with `ngen-workflow/output/v2.2/ngen/16/ngen_hydrofabric_final.gpkg` and deleting the cached igraph pickle. In other words, it swaps out the global CONUS file.
- I inspected `test/ngen-simulation-test/conus_nextgen.gpkg` (VPU 16, 368 MB) read-only:
  - Layers are `divides, flowpaths, nexus, hydrolocations, lakes, network, pois, divide-attributes, flowpath-attributes, flowpath-attributes-ml`. Column order matches the preprocessor's `template.sql`.
  - `divide-attributes` has the columns the default CFE/NOAH-OWP realization reads (`mode.bexp_soil_layers_stag=1`, `mean.slope`, `circ_mean.aspect`, `mean.Zmax`, `centroid_x/y`, …).
  - There are 35,250 divides. All `network.hl_uri` values are NULL.
  - **`flowpath-attributes.gage` is `''` (empty string, not NULL) on all 35,255 rows.**
  - `hydrolocations` has 502 rows with `hl_reference LIKE 'nwis-%'`, but their `id`/`nex_id` are empty. That means the USGS locations exist but are not linked to the flowpath/nexus network in a form the tools read.

### Input preparation (forcings, realization, BMI configs)

- **Forcings.**
  - The preprocessor computes area-weighted means (exactextract) of NWM retrospective v3 or AORC zarr over the subset's `divides` polygons, so it works for any geometry.
  - DataStreamCLI uses `forcingprocessor`, which also computes weights from catchment polygons. Its default `FORCING_SOURCE` is `NWM_RETRO_V3`.
- **Realization / parameters (preprocessor).**
  - The default CFE + NOAH-OWP realization reads parameters from the subset gpkg's **own** `divide-attributes`, so custom attribute values reach the model.
  - Other models are tied to official v2.2 IDs. dHBV2, SNOW17 and SAC-SMA join external parquet keyed by v2.2 `divide_id`. SUMMA reads the hardcoded CONUS file. `--nwm_gw` maps `network.hf_id` to NWM `feature_id`. Gage-calibrated parameters are fetched by gage ID.
  - Multiple/modular realizations are in the v5.0.x prereleases (v5.0.0b1 2026-09-01, v5.0.1b1 2026-10-08).
- **BMI configs (DataStreamCLI).** `ngen_configs_gen.py` and `noahowp_pkl.py` generate per-catchment BMI configs from the gpkg for the models in the realization. `run_validator.py` then checks the run package before NGIAB starts.
- **Attribute-quality feedback relevant to CUAHSI's pipeline.**
  - Preprocessor v4.9.3/v5.0.1b1 release notes say the v2.2 `mean.slope` was effectively 100× too steep (rise stored in cm). They fixed this with a conversion in the preprocessor.
  - The notes also say aspect had been averaged arithmetically instead of circularly, and that this "must be fixed in the hydrofabric itself".
  - If CUAHSI's pipeline copies v2.2 attribute conventions, model output will depend on how these two issues are handled. Any evaluation baseline needs to account for that.

### Automated / headless runs

- **NGIAB container.**
  - `docker run --rm -v <run_dir>:/ngen/ngen/data awiciroh/ciroh-ngen-image:<tag> /ngen/ngen/data/ auto <nprocs> [local]` runs NextGen without prompts.
  - The docs show it with `-it`. DataStreamCLI runs it without `-it`, which shows it works without a TTY.
  - NGIAB-CloudInfra v2.1.0 (2026-10-28) added run-metadata output. An `owp-master` image tag is rebuilt monthly for comparing against upstream ngen.
- **Guide scripts are interactive.**
  - `guide.sh` prompts for a path and a run mode.
  - `runTeehr.sh` has `-d`, `-t` and `-y`, but even with all three it still shows a `select` menu ("Run TEEHR using existing local image / Update / Exit"), so it is not fully headless.
- **Preprocessor CLI.**
  - It can be scripted once the hydrofabric files exist and `no_update` is set.
  - On a first run, `Prompt.ask` asks about downloads.
  - `--run` calls `docker run --rm -it …`, which will probably fail in CI without a TTY *(inference)*.
  - A preprocessor Docker image workflow was added in #261 (2026-10-28).
- **DataStreamCLI** is the most CI-ready path.
  - One command (`./scripts/datastream -s … -e … -g <gpkg> -R <realization> -d <dir> -n <nprocs> [-E True]`) runs these containerized steps in order: config, BMI generation, forcings, validation, NGIAB, troute NetCDF→parquet, merkle hash, and optional TEEHR.
  - Image tags are pinned in `versions_integrations.yml` (`ciroh-ngen-image: v2.0.0`, `forcingprocessor: 2.3.2`, `ngiab-teehr: "latest"`).
  - It needs Docker, bash and (for S3 inputs) the AWS CLI.
- **Compute.** Neither project documents runtimes for a VPU-scale run. CONUS or full-VPU runs are probably too heavy for standard GitHub-hosted runners. Small gauged subsets are probably feasible *(inference)*. NGIAB-HPCInfra (Singularity/HPC) exists and is active (pushed 2026-10-29); I did not evaluate it.

### Evaluation and metrics

- **ngiab-teehr (UA)**, main @ `21f70c8d` (2026-09-28), image `awiciroh/ngiab-teehr`:
  - `utils.get_gages_from_hydrofabric()` finds the gpkg under `<run>/config/`. If a `pois` table exists, it treats the file as v2.2 and reads `flowpath-attributes.gage WHERE gage IS NOT NULL`.
  - It downloads USGS locations, USGS observations and the `nwm30_retrospective` simulation from the TEEHR-Cloud warehouse (`ev.download.*`), so it needs network access to RTI's service.
  - It reads the t-route output (NetCDF, CSV or parquet) for the gaged flowpaths.
  - It computes `RootMeanStandardDeviationRatio`, `RelativeBias`, `NashSutcliffeEfficiency` and `KlingGuptaEfficiency` for each `primary_location_id × configuration_name`, and writes them to an `ngen_metrics` table in a local TEEHR warehouse.
  - It pins `teehr==0.6.2` and needs Java/Spark (`pyspark==4.0.1`, `apache-sedona`).
- **Integration gaps observed in code** (not executed):
  - `teehr_ngen.py` main requires `--data_folder_stem` and `--teehr_evaluation_dir`. The Dockerfile `ENTRYPOINT` passes neither, and both `runTeehr.sh` (CloudInfra v2.1.0) and DataStreamCLI `-E True` run the container without arguments. Either the published `latest` image predates this code or the integration currently fails. I could not determine which.
  - DataStreamCLI converts t-route NetCDF to parquet in `outputs/troute/` and deletes the `.nc`. `ngiab-teehr` detects parquet in `outputs/troute/` but then reads from `outputs/troute_parquet/`. This looks like a path mismatch.
- **With CUAHSI's current gpkg:** the empty-string `gage` values pass `IS NOT NULL`, so all 35,255 flowpaths are returned with USGS id `"usgs-"`. None of them match TEEHR locations. Evaluation would either find zero gages or fail when downloading locations *(inference from code; not run)*.
- **ngiab_eval / preprocessor `--eval`.** `JoshCu/ngiab_eval` (personal repo, no license; last commit 2026-10-29 "swap to dataretrieval") is self-described as a throw-away planning prototype. The preprocessor's `--eval` flag is undocumented and depends on it. The preprocessor README instead tells users to run TEEHR through `guide.sh`.
- **TEEHR itself (RTI)**, tags up to v0.8.0, is a general evaluation framework. It has primary (observed) vs. secondary (simulated) timeseries, location crosswalks, many deterministic metrics, and grouping/filtering. It is the natural engine for any CUAHSI harness. TEEHR-Cloud also ingests public NRDS outputs.

### Run-to-run comparison

- **What exists:**
  - The `teehr_ngen.py` docstring says several NGIAB runs can point to the same TEEHR evaluation directory "so that metrics from different runs can be compared within the same evaluation". Each run becomes a secondary configuration `ngen_<run_folder_stem>` next to `nwm30_retrospective`, and all are scored against USGS.
  - That would support "baseline hydrofabric vs. modified hydrofabric vs. NWM 3.0", gage by gage.
- **What is missing:**
  - Neither guide script nor DataStreamCLI passes a shared `--teehr_evaluation_dir`. Each run's container writes into its own run directory, so the shared evaluation must be orchestrated by hand.
  - There is no direct simulation-vs-simulation comparison (e.g., baseline run as "primary" to measure flow changes at ungauged reaches).
  - There is no diff/delta report (change in KGE etc., per gage or aggregated), no thresholds or pass/fail, and no rendering for PRs or tickets.
  - There is no management of baseline runs (same period, forcings, image tag and realization for both runs).
- **Hydrofabric-specific complication:**
  - Comparisons only work at USGS gages that are mapped in *both* hydrofabrics.
  - If a contribution changes flowpath IDs or the gage→flowpath mapping, the same gage maps to different `wb-`/`ngen-` IDs in each run.
  - Comparing through the USGS primary ID handles this. Comparing simulations directly would need an explicit crosswalk between the old and new IDs.
- **NRDS pattern:** `UPDATE_DATASTREAM.md` notes that running a second datastream pinned to a different image tag "makes the difference between model versions measurable at continental scale". This is a run-to-run pattern for *model versions* on a fixed hydrofabric, not for hydrofabric variants.

### Status and ownership

| Component | Owner / main authors | Recent activity | Maturity signal |
|---|---|---|---|
| NGIAB-CloudInfra (`ciroh-ngen-image`, guide scripts) | UA (CIROH-UA staff) | v2.1.0 2026-10-28 | Production releases; monthly OWP-master image |
| NGIAB_data_preprocess | UA (Quinn Lee, Josh Cunningham et al.) | v4.9.4 2026-10-28; main 2026-10-30 | Stable releases; v5 modular configs in beta |
| ngiab-teehr | UA (CIROH-UA staff) | 2026-09-28 | README: "experimental"; teehr pinned at 0.6.2 |
| ngiab_eval | Josh Cunningham (UA), personal repo | 2026-10-29 | "Please don't use this" prototype |
| DataStreamCLI, forcingprocessor | CIROH-UA org; authored by Jordan Laser (Lynker) | 2026-10-28 / 2026-10-27 | Used to run NRDS in production |
| ngen-datastream (NRDS infra) | CIROH-UA org; Lynker author | 2026-10-22 | Production daily CONUS datastreams on v2.2 |
| community_hf_patcher ("CIROH Community Hydrofabric") | UA | 2026-09-28 | Temporary v2.2 fork until hydrofabric v3 |
| TEEHR, TEEHR-Cloud | RTI International | tag v0.8.0 | Active general-purpose framework |
| NGIAB-HPCInfra, ngiab-cal | UA | 2026-10-29 / 2026-06-18 | Not evaluated in depth |

None of the READMEs, NRDS status pages or contribution docs I read describes planned work on per-contribution hydrofabric evaluation. The nearest items are:

- NRDS "Planned Updates": "Evaluate predictive performance on a national scale".
- NRDS issue #170 (community contribution workflow), which is about parameters.

I did not survey GitHub issues/discussions exhaustively, and I could not see any UA-internal plans.

## Ready vs. in progress vs. would-need-building

| Capability | Status | Where / by whom | Notes for CUAHSI |
|---|---|---|---|
| Run NextGen headless on a prepared run directory | **Ready** | `awiciroh/ciroh-ngen-image` (UA) | Use `auto <n> local`, no `-it` |
| Run an arbitrary gpkg end to end (configs, forcings, validate, run) | **Ready** (not verified with CUAHSI gpkg) | DataStreamCLI `-g` (CIROH-UA / Lynker) | `forcing-weights` layer needed or not: unverified |
| Subset an arbitrary gpkg | **Ready** | Preprocessor `subset_cli` v4.9.4 (UA) | Schema/column order must match v2.2 `template.sql`; CUAHSI VPU 16 output does |
| Forcings for arbitrary catchment geometry | **Ready** | Preprocessor (exactextract), forcingprocessor | NWM retro v3 / AORC |
| Default CFE + NOAH-OWP parameters from the gpkg's own attributes | **Ready** | Preprocessor `create_realization.py`; DataStreamCLI `ngen_configs_gen.py` | Slope-unit and aspect issues flagged by UA |
| Other models (dHBV2, SNOW17, SAC-SMA, SUMMA, NWM GW, calibrated params) on custom gpkg | **Not supported** for non-v2.2 IDs | Preprocessor (UA) | Keyed to official v2.2 IDs / hardcoded CONUS file |
| Preprocessor main CLI with a user-specified hydrofabric, non-interactive | **Missing** (workaround: swap global file + `no_update`) | UA | Natural upstream PR candidate |
| Multiple / modular realizations in preprocessor | **In progress** (v5.0.x beta) | UA | — |
| Gage → flowpath mapping in the hydrofabric (`flowpath-attributes.gage`, hydrolocation links) | **Missing in CUAHSI output** | CUAHSI pipeline | Prerequisite for any gage-based evaluation |
| Metrics vs. USGS observations (KGE, NSE, rel. bias, RMSDR) | **Experimental** | `ngiab-teehr` (UA) + TEEHR-Cloud (RTI) | Container-argument mismatch, parquet path mismatch, teehr 0.6.2 |
| Reference comparison against NWM v3.0 retrospective | **Experimental** (included in ngiab-teehr) | `ngiab-teehr` | — |
| Baseline-vs-modified hydrofabric metrics side by side | **Partial**: designed for it, not wired up | `ngiab-teehr` shared evaluation dir | Needs orchestration |
| Delta report, thresholds, pass/fail, PR/Jira-friendly output | **Would need building** | — | No owner found |
| Baseline run management (fixed period, forcings, tags; caching official v2.2 / previous CUAHSI version) | **Would need building** | — | No owner found |
| Simulation-vs-simulation at ungauged reaches; old↔new ID crosswalk | **Would need building** | — | TEEHR can probably hold it *(inference)*; no tool does it |
| CI/compute to run evaluations automatically on contributions | **Would need building / deciding** | — | GitHub runners vs. CIROH cloud vs. HPC |
| Continental-scale evaluation of hydrofabric versions in NRDS | **Not available** for community contributions | NRDS (Lynker/UA) | NRDS tracks official releases only; national evaluation is "planned" |
| Preprocessor `--eval` / `ngiab_eval` | **Prototype, do not use** | Josh Cunningham (UA), personal | — |

## Implications for the "Automated checks Epics" decision

This section lists facts and options only. It does not make the decision.

### Facts that constrain the decision

1. **No ready-made "evaluate this hydrofabric contribution" capability exists, upstream or in progress.** Under any option, someone has to write the orchestration: run baseline and candidate, put both into one TEEHR evaluation, and report deltas.
2. **Some prerequisites belong to CUAHSI under any option.**
   - Populate the gage/hydrolocation linkage in the pipeline's NextGen output: `flowpath-attributes.gage`, and hydrolocations linked to `id`/`nex_id`.
   - Keep the gpkg schema conformant to v2.2/`template.sql`.
   - Decide how to handle the slope-unit and circular-aspect attribute issues UA has raised.
3. **"Depend on UA" really means depending on three groups.** The run-and-evaluate chain spans UA (NGIAB image, preprocessor, ngiab-teehr), Lynker staff (DataStreamCLI, forcingprocessor, NRDS) and RTI (TEEHR, TEEHR-Cloud). A dependency would need agreements with each of them, or with UA as coordinator.
4. **The upstream parts are moving fast.** Releases landed weekly in Oct 2026, the preprocessor's v5 is in beta, and ngiab-teehr's TEEHR is two minor versions behind. Pinning image tags and versions is necessary for baselines to be reproducible.
5. **NRDS is not where hydrofabric contributions get evaluated.** It sends hydrofabric contributions to `community.fabric` / `community_hf_patcher` and only adopts official versions. So "use Research DataStream" in the proposal can realistically mean DataStreamCLI as a run engine, not NRDS infrastructure.
6. **Execution cost is unknown.** Neither project publishes runtimes for VPU-scale runs. Feasibility in CI (vs. CIROH cloud or HPC) has to be measured before scoping automated checks.

### Options

- **Option A — Dependency on UA.**
  - CUAHSI keeps its gpkg NGIAB-conformant (including gages) and asks UA (and through UA, Lynker/RTI) to deliver hydrofabric-contribution evaluation inside the NGIAB ecosystem.
  - Asks would include: a custom-hydrofabric flag and non-interactive mode in the preprocessor, fixed and argument-driven ngiab-teehr invocation, shared-evaluation/run-to-run support, and a comparison report.
  - Pros: least CUAHSI engineering; matches the proposal's "collaborate with UA" wording.
  - Cons: no public UA roadmap item covers this; CUAHSI does not control the timeline; the automated checks would sit outside CUAHSI's DVC/CI.
- **Option B — CUAHSI Epic: thin harness composed from pinned UA/RTI tools.**
  - CUAHSI builds a DVC stage or CI workflow that runs, for a small set of gauged test domains:
    - candidate gpkg → DataStreamCLI (or preprocessor `subset_cli` + forcings + `ciroh-ngen-image`), and
    - the same against a cached baseline (official v2.2 or the previous CUAHSI release).
  - It then loads both into one TEEHR evaluation (calling TEEHR directly or a fixed fork/invocation of ngiab-teehr) and emits a delta report with thresholds.
  - Pros: CUAHSI controls scope, schedule and integration with `pipelines/`; works today on the ready components.
  - Cons: CUAHSI maintains glue code against fast-moving upstream tools; compute must be provisioned; may duplicate future UA work.
- **Option C — Split: CUAHSI Epic for harness and hydrofabric-side checks, upstream contributions for generic gaps.**
  - Like B, but generic fixes go upstream as PRs or coordinated issues rather than CUAHSI-local workarounds: preprocessor `--hydrofabric`/non-interactive flags, ngiab-teehr argument/path fixes, a shared-evaluation option, possibly a run-comparison mode.
  - Ownership boundaries are agreed with UA up front.
  - Pros: harness stays in CUAHSI's control while the ecosystem gets the fixes, and the "collaborate with UA" commitment is visible.
  - Cons: coordination overhead; upstream acceptance timing is not guaranteed.

Under every option, the gage-linkage fix and schema conformance in `ciroh-hydrofabrics` are CUAHSI work, and they are needed before any NGIAB-based evaluation can produce gage metrics.

### Open questions worth resolving before the decision

- Does UA have planned (non-public) work on hydrofabric-variant evaluation, or on ngiab-teehr run comparison? This needs a conversation with the NGIAB team (CIROH-UA).
- Which image does `awiciroh/ngiab-teehr:latest` currently contain, and does `runTeehr.sh` / DataStreamCLI `-E True` work end to end today?
- Does DataStreamCLI's `forcingprocessor` / `ngen_configs_gen.py` accept CUAHSI's v2.2-format gpkg without a `forcing-weights` layer?
- What does a VPU-16 or small-basin run cost (wall time, memory), and where would automated checks run?
- What counts as the baseline for a contribution: official Lynker v2.2, the UA "CIROH Community Hydrofabric", or the previous CUAHSI release?

## Sources

All accessed 2026-11-04. I pinned commit SHAs or tags where I could get them.

**CIROH-UA / UA**

- NGIAB_data_preprocess, main @ `4088447c` (2026-10-30); release v4.9.4 (2026-10-28); prereleases v5.0.0b1 (2026-09-01), v5.0.1b1 (2026-10-08). Files read: `README.md`, `modules/data_processing/file_paths.py`, `source_validation.py`, `subset.py`, `subset_cli.py`, `create_realization.py`, `forcings.py`, `ngiab_data_cli/__main__.py`, `template.sql`, release notes v4.9.3/v4.9.4/v5.0.1b1. <https://github.com/CIROH-UA/NGIAB_data_preprocess/tree/4088447c>
- NGIAB-CloudInfra, tag v2.1.0 (2026-10-28): `README.md`, `docs/03_01_CONTAINERS.md`, `runTeehr.sh` (v1.4.1 header), release notes v1.9.0/v2.0.0/v2.1.0. <https://github.com/CIROH-UA/NGIAB-CloudInfra/tree/v2.1.0>
- ngiab-teehr, main @ `21f70c8d` (2026-09-28): `README.md`, `scripts/teehr_ngen.py`, `scripts/utils.py`, `Dockerfile`, `entrypoint.sh`, `requirements.txt`. <https://github.com/CIROH-UA/ngiab-teehr/tree/21f70c8db5df6201c14573d64fd1af5cc2dcc6cd>
- community_hf_patcher, main @ `28f74bab` (2026-09-28): `README.md`. <https://github.com/CIROH-UA/community_hf_patcher/tree/28f74bab7ea5aa4f3d2533d8f09b93901967d5e6>
- JoshCu/ngiab_eval, main @ `86a41513` (2026-10-29): `README.md`. <https://github.com/JoshCu/ngiab_eval/tree/86a41513efee723ffbd495c81451426221397d57>
- CIROH-UA org repository listing (GitHub API, `pushed_at` dates for NGIAB-HPCInfra, ngiab-cal, forcingprocessor, etc.). <https://api.github.com/orgs/CIROH-UA/repos>

**DataStream (CIROH-UA org, Lynker-authored)**

- datastreamcli, main @ `d59279e2` (2026-10-28): `README.md`, `docs/DATASTREAM_OPTIONS.md`, `docs/BREAKDOWN.md`, `scripts/datastream`, `versions_integrations.yml`. <https://github.com/CIROH-UA/datastreamcli/tree/d59279e26c530e22d184b081577e3ea6cf73f8a8>
- ngen-datastream (NRDS), main @ `cf8d5fda` (2026-10-22): `README.md`, `docs/nrds/STATUS_AND_METADATA.md` (last status entry 05/2026), `docs/nrds/contribute/README.md`, `docs/nrds/contribute/UPDATE_DATASTREAM.md`. <https://github.com/CIROH-UA/ngen-datastream/tree/cf8d5fda85ca0551cd5c4937501279bdab49f982>

**RTI**

- TEEHR, tags list (latest v0.8.0 @ `447c503f`). <https://github.com/RTIInternational/teehr> · docs <https://rtiinternational.github.io/teehr/>

**Local (this repo, read-only)**

- `test/ngen-simulation-test/copy-hydrofabric-to-ngiab-dir.sh`, `prepare-ngiab.sh`, `run-ngiab.sh`, `readme.md`.
- `test/ngen-simulation-test/conus_nextgen.gpkg`, inspected with `sqlite3 -readonly` (layer list, column order, `flowpath-attributes.gage` counts: 35,255 rows, 0 NULL, 35,255 empty string; `hydrolocations` `hl_reference` prefixes).

**Could not verify**

- The contents and behavior of the published `awiciroh/ngiab-teehr:latest` / `:x86` images, and whether the TEEHR integration works end to end today.
- Whether DataStreamCLI works with a v2.2-format gpkg that has no `forcing-weights` layer, or with CUAHSI's gpkg specifically.
- Runtimes and resource needs for VPU-scale or small-basin NGIAB runs.
- Any UA, Lynker or RTI plans not published in the repos and docs above. GitHub issues and discussions were not searched exhaustively, and CIROH DocuHub / hub.ciroh.org pages were not read separately (the CloudInfra README says repo docs are mirrored there).
- Whether the official Lynker v2.2 gpkg uses the `hl_reference`/`hl_uri` gage conventions I assumed when comparing it with CUAHSI's hydrolocations.
