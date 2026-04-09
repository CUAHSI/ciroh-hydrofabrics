
# CIROH HydroFabric DVC Integration

This project uses [DVC (Data Version Control)](https://dvc.org/) to manage data pipelines and track changes to large datasets. DVC enables reproducible workflows and seamless collaboration.

## DVC Installation

To use this project, you must have [DVC](https://dvc.org/doc/install) installed. The recommended way is via pip:

```sh
pip install dvc-s3
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
    ```sh
    pip install awscli
    ```
2. Get an access token and key from HydroShare (POST to https://www.hydroshare.org/hsapi/user/service/accounts/s3/ with basic authentication, use the [Swagger page](https://www.hydroshare.org/hsapi/) to do this easily)
3. Run the following command and enter your credentials:
    ```sh
    aws configure --profile hydroshare
    ```
4. Setup the endpoint url to point to HydroShare
    ```sh
    aws configure set profile.hydroshare.endpoint_url https://s3.hydroshare.org
    ```
### Download Data

Running the pipeline will download necessary data lazily. You can also download specific files manually with:

```sh
dvc update <path_to_file.dvc>
```

### DVC repro

Before running the pipeline, you should pull the required data from the configured DVC remote. This ensures all tracked input files are available locally:

```sh
dvc pull
```

This command will download all necessary data files from your configured DVC remote storage (as set in your DVC config). Make sure your credentials and remote configuration are correct.

Once the data is available, you can reproduce the pipeline with:

```sh
dvc repro pipelines/demo/dvc.yaml
```

This will execute all stages defined in `dvc.yaml` in the correct order, rebuilding outputs as necessary. If any required data is missing, DVC will attempt to pull it automatically from the remote during execution.

### Pipeline Parameters


Parameters are defined in `params.yaml` and referenced in the pipeline stages. The following parameters are available:

#### Global
- `vpuid`: Vector Processing Unit ID (01, 02, etc)

#### prepare
Uses vpuid to read input files and write an output file, no other parameters necessary.

#### refactor
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

## Adding Your Own DVC Remote

To use your own remote storage (such as S3, Azure, GCP, or a local directory) for DVC data, you can add and configure a DVC remote as follows:

1. **Add a new remote:**
    ```sh
    dvc remote add -d myremote <remote_url>
    ```
    Replace `myremote` with a name for your remote, and `<remote_url>` with the appropriate URL (e.g., `s3://my-bucket/path`, `azure://container/path`, `gdrive://folderid`, or a local path).

2. **Configure credentials and options:**
    If you are using a HydroShare resource, you should already have credentials stored.

    For other remotes, see the [DVC remote documentation](https://dvc.org/doc/command-reference/remote/modify) for available options.

3. **Verify your remote:**
    ```sh
    dvc remote list
    dvc remote status
    ```

4. **Push or pull data:**
    ```sh
    dvc push
    dvc pull
    ```

You can add multiple remotes and switch the default with:
```sh
dvc remote default myremote
```

For more details, see the [official DVC documentation on remotes](https://dvc.org/doc/command-reference/remote).