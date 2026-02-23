#!/usr/bin/env bash

# Check that exactly one argument was provided
if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <directory containing parquet files> <vpu id>"
  exit 1
fi

BASE_DIR="$1"
VPU_ID="$2"

# combine the parquets into a geopackage
ogr2ogr -f "GPKG" "${BASE_DIR}/reference_hydrofabric.gpkg" "${BASE_DIR}/divides.parquet"
ogr2ogr -f "GPKG" -append "${BASE_DIR}/reference_hydrofabric.gpkg" "${BASE_DIR}/flowpaths.parquet"
ogr2ogr -f "GPKG" -append "${BASE_DIR}/reference_hydrofabric.gpkg" "${BASE_DIR}/network.parquet"
ogr2ogr -f "GPKG" -append "${BASE_DIR}/reference_hydrofabric.gpkg" "${BASE_DIR}/hydrolocations.parquet"
#ogr2ogr -f "GPKG" -append "${BASE_DIR}/reference_hydrofabric.gpkg" "${BASE_DIR}/pois.parquet"

# add VPU column to the divides table
ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
  -sql "ALTER TABLE divides ADD COLUMN vpuid TEXT"
ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
  -sql "UPDATE divides SET vpuid = '${VPU_ID}'"

# add VPU column to the flowpaths table
ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
  -sql "ALTER TABLE flowpaths ADD COLUMN vpuid TEXT"
ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
  -sql "UPDATE flowpaths SET vpuid = '${VPU_ID}'"

## create and empty POIs table
#ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
#  -sql "CREATE TABLE pois (
#    fid INTEGER PRIMARY KEY,
#    poi_id INT,
#    flowpath_id REAL,
#    hl_count INTEGER,
#    hl_classes TEXT,
#    hl_types TEXT,
#    pathmeas REAL,
#    pathdist REAL,
#    vpuid TEXT
#    )"
#ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
#  -sql "INSERT INTO gpkg_contents (
#    table_name,
#    data_type,
#    identifier,
#    description,
#    last_change,
#    srs_id
#  ) VALUES (
#    'pois',
#    'attributes',
#    'pois',
#    'Points of Interest',
#    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
#    0
#  )"
#
# this can also be done with CSV file

# echo "fid,poi_id,flowpath_id,hl_count" > temp_pois.csv
# ogr2ogr -f GPKG your_file.gpkg temp_pois.csv -nln pois

## add VPU column to the pois
#ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
#  -sql "ALTER TABLE pois ADD COLUMN vpuid TEXT"
#ogrinfo "${BASE_DIR}/reference_hydrofabric.gpkg" \
#  -sql "UPDATE pois SET vpuid = '${VPU_ID}'"
