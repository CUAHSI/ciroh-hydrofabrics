#!/usr/bin/env bash

# combine the parquets into a geopackage
ogr2ogr -f "GPKG" reference_hydrofabric.gpkg divides.parquet
ogr2ogr -f "GPKG" -append reference_hydrofabric.gpkg flowpaths.parquet
#ogr2ogr -f "GPKG" -append reference_hydrofabric.gpkg hydrolocations.parquet
ogr2ogr -f "GPKG" -append reference_hydrofabric.gpkg network.parquet
ogr2ogr -f "GPKG" -append reference_hydrofabric.gpkg pois.parquet

# add VPU column to the divides table
ogrinfo reference_hydrofabric.gpkg \
  -sql "ALTER TABLE divides ADD COLUMN vpuid TEXT"
ogrinfo reference_hydrofabric.gpkg \
  -sql "UPDATE divides SET vpuid = '01'"

# add VPU column to the flowpaths table
ogrinfo reference_hydrofabric.gpkg \
  -sql "ALTER TABLE flowpaths ADD COLUMN vpuid TEXT"
ogrinfo reference_hydrofabric.gpkg \
  -sql "UPDATE flowpaths SET vpuid = '01'"

# add VPU column to the pois
ogrinfo reference_hydrofabric.gpkg \
  -sql "ALTER TABLE pois ADD COLUMN vpuid TEXT"
ogrinfo reference_hydrofabric.gpkg \
  -sql "UPDATE pois SET vpuid = '01'"
