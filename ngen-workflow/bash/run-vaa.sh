#!/usr/bin/env bash
set -e

if [ $# -lt 5 ]; then
  echo "Usage: $0 <nextgen_geopackage> <soil_dir> <gw_params> <dem> <nwm_slope>"
  exit 1
fi

nextgen_geopackage="$1"
soil_data="$2"
gw_params="$3"
dem="$4"
nwm_slope="$5"

mkdir -p "$(dirname "$output_parquet")"

Rscript R/vaa.r \
  --nextgen_geopackage "$nextgen_geopackage" \
  --soil_data "$soil_data" \
  --gw_params "$gw_params" \
  --dem "$dem" \
  --nwm_slope "$nwm_slope"

#Rscript -e "
#    rmarkdown::render(
#        'R/vaa.Rmd',
#        params = list(
#            nextgen_geopackage = '$nextgen_geopackage',
#            soil_data          = '$soil_data',
#            gw_params          = '$gw_params',
#            dem                = '$dem'
#        )
#    )
#" 2>&1 | cat
