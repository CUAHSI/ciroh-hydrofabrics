#!/usr/bin/env bash
set -e

if [ $# -lt 3 ]; then
  echo "Usage: $0 <reference_geopackage> <topology_csv> <out_geopackage>"
  exit 1
fi

reference_geopackage="$1"
topology_csv="$2"
output_geopackage="$3"

mkdir -p "$(dirname "$output_geopackage")"

python Python/fix_topology.py "$reference_geopackage" "$topology_csv" "$output_geopackage"
