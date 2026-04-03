
# CIROH HydroFabric DVC Integration

This project uses [DVC (Data Version Control)](https://dvc.org/) to manage data pipelines and track changes to large datasets. DVC enables reproducible workflows and seamless collaboration.

## DVC Installation

To use this project, you must have [DVC](https://dvc.org/doc/install) installed. The recommended way is via pip:

```sh
pip install dvc[s3]
```

Or, with Homebrew on macOS:

```sh
brew install dvc
```

For more installation options, see the [official DVC documentation](https://dvc.org/doc/install).

## Data

The pipeline relies on several key input datasets, organized in the `ngen-workflow/data/superconus` and `ngen-workflow/data/NHDSnapshot` directories and stored in a [HydroShare resource](https://www.hydroshare.org/resource/7056bc5d6de14c5e9fbece9735124ca1/):

### ngen-workflow/data/superconus

- **divides/**: Parquet files containing catchment divide geometries for each VPU (e.g., `vpuid_01.parquet`).
- **flowpaths/**: Parquet files with flowpath (stream/river) geometries for each VPU.
- **hydrolocations/**: Parquet files with hydrologic location points (e.g., gages, outlets) for each VPU.
- **network/**: Parquet files describing the hydrologic network topology for each VPU.
- **pois.parquet**: Parquet file with points of interest (POIs) across the superCONUS domain.
- **reference_hydrofabric.gpkg**: GeoPackage containing the reference hydrofabric for the superCONUS domain.

### ngen-workflow/data/NHDSnapshot

- **FAC/**: Flow Accumulation (FAC) raster files (`*.tif`) for each region, used in hydrologic refactoring.
- **FDR/**: Flow Direction (FDR) raster files (`*.tif`) for each region, used in hydrologic refactoring.

Each subdirectory contains files for multiple regions or VPUs, typically named by region code (e.g., `01a_fac.tif`, `vpuid_01.parquet`). These datasets are tracked with DVC and may require pulling from remote storage before running the pipeline.

For DVC to access the input files on HydroShare, configure your AWS credentials with a profile named `hydroshare`:

1. Install the AWS CLI if not already installed.
2. Get an access token and key from HydroShare (POST to https://www.hydroshare.org/hsapi/user/service/accounts/s3/ with basic authentication, use the [Swagger page](https://www.hydroshare.org/hsapi/) to do this easily)
3. Run the following command and enter your credentials:
    ```sh
    aws configure --profile hydroshare
    ```
### Download Data

Running the pipeline will download necessary data lazily. You can also download specific files manually with:

```sh
dvc update <path_to_file.dvc>
```

## Running the Pipeline

To reproduce the pipeline, use:

```sh
dvc repro
```

This command will download all files needed to execute all stages defined in `dvc.yaml` in the correct order, rebuilding outputs as necessary.

### Pipeline Parameters


Parameters are defined in `params.yaml` and referenced in the pipeline stages. The following parameters are available:

#### Global
- `vpuid`: Vector Processing Unit ID (01, 02, etc)

#### prepare
- `divides_file`: Path to divides parquet file
- `flowpaths_file`: Path to flowpaths parquet file
- `hydrolocations_file`: Path to hydrolocations parquet file
- `network_file`: Path to network parquet file
- `pois_file`: Path to POIs parquet file

#### refactor
- `fac_file`: Path to flow accumulation (FAC) raster file
- `fdr_file`: Path to flow direction (FDR) raster file
- `split_flines_meters`: Split flowlines at this length (meters)
- `collapse_flines_meters`: Collapse flowlines below this length (meters)
- `collapse_flines_main_meters`: Collapse main flowlines below this length (meters)
- `simplify_tolerance_meters`: Simplification tolerance (meters)

#### aggregate
- `ideal_size_sqkm`: Ideal catchment size (sq km)
- `min_length_km`: Minimum flowpath length (km)
- `min_area_sqkm`: Minimum catchment area (sq km)

You can modify these parameters in `params.yaml` to customize pipeline behavior. To see current parameters:

```sh
cat params.yaml
```

## DVC Pipeline Stages

The pipeline is composed of the following stages, as defined in `dvc.yaml`:

### 1. prepare
Prepares the reference hydrofabric for a given VPU by combining divides, flowpaths, hydrolocations, network, and POI data into a single GeoPackage. Output: `ngen-workflow/data/prepared/{vpuid}/reference_hydrofabric.gpkg`.

### 2. refactor
Refactors the prepared hydrofabric using flow accumulation (FAC) and flow direction (FDR) rasters, splitting and simplifying flowlines as specified by parameters. Output: `ngen-workflow/data/refactored/{vpuid}/refactored_reference_hydrofabric.gpkg`.

### 3. aggregate
Aggregates the refactored hydrofabric into larger catchments based on ideal size and minimum thresholds. Outputs: `ngen-workflow/data/aggregated/{vpuid}/aggregate_outlets.gpkg` and `ngen-workflow/data/aggregated/{vpuid}/aggregate_distribution.gpkg`.

Each stage is run in a containerized environment using Docker Compose, and all dependencies and outputs are tracked by DVC for reproducibility.

#### WIP stages:

### 4. Generate a NextGen Network

Runs apply_nexus_topology

### 5. Enriching the Network
