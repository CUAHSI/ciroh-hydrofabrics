#!/usr/bin/env bash
set -e

if [ $# -lt 3 ]; then
  echo "Usage: $0 <flowpath_gpkg> <flowline_gpkg> <out_gpkg>"
  exit 1
fi

flowpath_gpkg="$1"
flowline_gpkg="$2"
out_gpkg="$3"

mkdir -p "$(dirname "$out_gpkg")"

Rscript -e "
    rmarkdown::render(
        'R/hfngen.Rmd',
        params = list(
            flowpath_gpkg = '$flowpath_gpkg',
            flowline_gpkg = '$flowline_gpkg',
            out_nextgen = '$out_gpkg'
        )
    )
"
