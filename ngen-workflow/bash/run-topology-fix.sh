#!/usr/bin/env bash
set -e

if [ $# -lt 3 ]; then
  echo "Usage: $0 <reference_geopackage> <topology_csv> <out_geopackage>"
  exit 1
fi

echo "$@"
reference_geopackage="$1"
topology_csv="$2"
output_geopackage="$3"

echo "Reference GeoPackage: $reference_geopackage"
echo "Topology CSV: $topology_csv"
echo "Output GeoPackage: $output_geopackage"

mkdir -p "$(dirname "$output_geopackage")"

python Python/topology_fix.py "$reference_geopackage" "$topology_csv" "$output_geopackage"
