#!/usr/bin/env bash
set -e

if [ $# -lt 5 ]; then
  echo "Usage: $0 <vpuid> <divides_file> <flowpaths_file> <hydrolocations_file> <network_file>"
  exit 1
fi

vpuid="$1"
divides_file="$2"
flowpaths_file="$3"
hydrolocations_file="$4"
network_file="$5"

mkdir -p data/prepared/$vpuid

# combine the parquets into a geopackage
ogr2ogr -f "GPKG" data/prepared/$vpuid/reference_hydrofabric.gpkg "/$divides_file" -nln divides
ogr2ogr -f "GPKG" -append data/prepared/$vpuid/reference_hydrofabric.gpkg "/$flowpaths_file" -nln flowpaths
ogr2ogr -f "GPKG" -append data/prepared/$vpuid/reference_hydrofabric.gpkg "/$hydrolocations_file" -nln hydrolocations
ogr2ogr -f "GPKG" -append data/prepared/$vpuid/reference_hydrofabric.gpkg "/$network_file" -nln network

# add VPU column to the divides table
ogrinfo data/prepared/$vpuid/reference_hydrofabric.gpkg \
  -sql "ALTER TABLE divides ADD COLUMN vpuid TEXT"
ogrinfo data/prepared/$vpuid/reference_hydrofabric.gpkg \
  -sql "UPDATE divides SET vpuid = '$vpuid'"

# add VPU column to the flowpaths table
ogrinfo data/prepared/$vpuid/reference_hydrofabric.gpkg \
  -sql "ALTER TABLE flowpaths ADD COLUMN vpuid TEXT"
ogrinfo data/prepared/$vpuid/reference_hydrofabric.gpkg \
  -sql "UPDATE flowpaths SET vpuid = '$vpuid'"
