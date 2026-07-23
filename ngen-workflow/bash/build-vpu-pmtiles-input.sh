#!/bin/sh

set -eu

output_root=$1

out_gpkg="$output_root/vpu.gpkg"
out_geo="$output_root/vpu.geojsonseq"

rm -f "$out_gpkg" "$out_geo"

export PROJ_DATA=/opt/conda/share/proj

first=1
for src in /ngen-workflow/data/superconus/divides/vpuid_*.parquet; do
  name=$(basename "$src" .parquet)
  vpuid=$(printf "%s" "$name" | sed 's/^vpuid_//')
  sql="SELECT ST_Boundary(ST_Union(ST_MakeValid(geom))) AS geom, '$vpuid' AS vpuid FROM $name"

  if [ "$first" -eq 1 ]; then
    ogr2ogr -f GPKG "$out_gpkg" "$src" -nln vpu -dialect sqlite -sql "$sql"
    first=0
  else
    ogr2ogr -f GPKG -append "$out_gpkg" "$src" -nln vpu -dialect sqlite -sql "$sql"
  fi
done

ogr2ogr -f GeoJSONSeq -t_srs EPSG:4326 "$out_geo" "$out_gpkg" vpu