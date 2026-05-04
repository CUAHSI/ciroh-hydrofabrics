#!/usr/bin/env bash
set -e

if [ $# -lt 3 ]; then
  echo "Usage: $0 <ngen_gpkg> <vpu_id> <out_gpkg>"
  exit 1
fi

ngen_gpkg="$1"
vpu_id="$2"
out_gpkg="$3"

mkdir -p "$(dirname "$out_gpkg")"

Rscript -e "
    rmarkdown::render(
        'R/reconcile.Rmd',
        params = list(
            ngen_gpkg = '$ngen_gpkg',
            vpu_id = '$vpu_id',
            out_nextgen = '$out_gpkg'
        )
    )
"
