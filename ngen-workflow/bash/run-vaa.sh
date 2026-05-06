#!/usr/bin/env bash
set -e

if [ $# -lt 3 ]; then
  echo "Usage: $0 <nextgen_geopackage> <soil_dir> <gw_params>"
  exit 1
fi

nextgen_geopackage="$1"
soil_data="$2"
gw_params="$3"

mkdir -p "$(dirname "$output_parquet")"

Rscript -e "
    rmarkdown::render(
        'R/vaa.Rmd',
        params = list(
            nextgen_geopackage = '$nextgen_geopackage',
            soil_data          = '$soil_data',
            gw_params          = '$gw_params'
        )
    )
"
