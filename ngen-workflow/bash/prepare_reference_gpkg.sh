#!/usr/bin/env bash
set -e

if [ $# -lt 1 ]; then
  echo "Usage: $0 <vpuid>"
  exit 1
fi

VPU_ID="$1"
mkdir -p data/prepared

# combine the parquets into a geopackage
ogr2ogr -f "GPKG" data/prepared/reference_hydrofabric.gpkg data/superconus/divides/${VPU_ID}.parquet -nln divides
ogr2ogr -f "GPKG" -append data/prepared/reference_hydrofabric.gpkg data/superconus/flowpaths/${VPU_ID}.parquet -nln flowpaths
ogr2ogr -f "GPKG" -append data/prepared/reference_hydrofabric.gpkg data/superconus/hydrolocations/${VPU_ID}.parquet -nln hydrolocations
ogr2ogr -f "GPKG" -append data/prepared/reference_hydrofabric.gpkg data/superconus/network/${VPU_ID}.parquet -nln network
#ogr2ogr -f "GPKG" -append data/prepared/reference_hydrofabric.gpkg data/superconus/pois/vpuid_${VPU_ID}.parquet -nln pois

# add VPU column to the divides table
ogrinfo data/prepared/reference_hydrofabric.gpkg \
  -sql "ALTER TABLE divides ADD COLUMN vpuid TEXT"
ogrinfo data/prepared/reference_hydrofabric.gpkg \
  -sql "UPDATE divides SET vpuid = '$(echo $VPU_ID | sed 's/^vpuid_//')'"

# add VPU column to the flowpaths table
ogrinfo data/prepared/reference_hydrofabric.gpkg \
  -sql "ALTER TABLE flowpaths ADD COLUMN vpuid TEXT"
ogrinfo data/prepared/reference_hydrofabric.gpkg \
  -sql "UPDATE flowpaths SET vpuid = '$(echo $VPU_ID | sed 's/^vpuid_//')'"

# add VPU column to the pois
#ogrinfo data/prepared/reference_hydrofabric.gpkg \
#  -sql "ALTER TABLE pois ADD COLUMN vpuid TEXT"
#ogrinfo data/prepared/reference_hydrofabric.gpkg \
#  -sql "UPDATE pois SET vpuid = '$VPU_ID'"
