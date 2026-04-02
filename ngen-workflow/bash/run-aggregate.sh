#!/usr/bin/env bash
set -e

if [ $# -lt 6 ]; then
  echo "Usage: $0 <hf_path> <aggregate_outlets_file> <aggregate_distribution_file> <ideal_size_sqkm> <min_length_km> <min_area_sqkm>"
  exit 1
fi

hf_path="$1"
aggregate_outlets_file="$2"
aggregate_distribution_file="$3"
ideal_size_sqkm="$4"
min_length_km="$5"
min_area_sqkm="$6"

Rscript -e "rmarkdown::render('R/aggregate.Rmd', params = list(
  hf_path = '$hf_path',
  aggregate_outlets_file = '$aggregate_outlets_file',
  aggregate_distribution_file = '$aggregate_distribution_file',
  ideal_size_sqkm = as.numeric('$ideal_size_sqkm'),
  min_length_km = as.numeric('$min_length_km'),
  min_area_sqkm = as.numeric('$min_area_sqkm')
))"