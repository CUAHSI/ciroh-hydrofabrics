#!/usr/bin/env bash
set -e

if [ $# -lt 7 ]; then
  echo "Usage: $0 <nextgen_gpkg> <soil_tif> <veg_tif> <imperv_tif> <gw_table> <channel_geom_table> <output_gpkg>"
  exit 1
fi

nextgen_gpkg="$1"
soil_tif="$2"
veg_tif="$3"
imperv_tif="$4"
gw_table="$5"
channel_geom_table="$6"
output_gpkg="$7"

mkdir -p "$(dirname "$nextgen_gpkg")"

Rscript -e "
    rmarkdown::render(
        'R/minimal_attributes.Rmd',
        params = list(
            nextgen_geopackage = '$nextgen_gpkg',
            soil_grid = '$soil_tif',
            vegetation_grid = '$veg_tif',
            impervious_grid = '$imperv_tif',
            groundwater_basins_table = '$gw_table',
            channel_geometry_table = '$channel_geom_table',
            output_nextgen_geopackage = '$output_gpkg'
        )
    )
"
