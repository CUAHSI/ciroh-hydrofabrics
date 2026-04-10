#!/usr/bin/env bash
set -e

if [ $# -lt 8 ]; then
  echo "Usage: $0 <fac_file> <fdr_file> <gpkg_file> <out_file> <split_flines_meters> <collapse_flines_meters> <collapse_flines_main_meters> <simplify_tolerance_m>"
  exit 1
fi

fac_file="$1"
fdr_file="$2"
gpkg_file="$3"
out_file="$4"
split_flines_meters="$5"
collapse_flines_meters="$6"
collapse_flines_main_meters="$7"
simplify_tolerance_m="$8"

mkdir -p "$(dirname "$out_file")"

Rscript -e "
    rmarkdown::render(
        'R/refactor.Rmd',
        params = list(
            fac_file = '$fac_file',
            fdr_file = '$fdr_file',
            gpkg_file = '$gpkg_file',
            out_file = '$out_file',
            split_flines_meters = as.numeric('$split_flines_meters'),
            collapse_flines_meters = as.numeric('$collapse_flines_meters'),
            collapse_flines_main_meters = as.numeric('$collapse_flines_main_meters'),
            simplify_tolerance_m = as.numeric('$simplify_tolerance_m')
        )
    )
"