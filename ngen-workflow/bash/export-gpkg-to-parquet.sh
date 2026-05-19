#!/usr/bin/env bash
set -eu

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <input_gpkg> <output_dir>"
  exit 1
fi

input_gpkg="$1"
output_dir="$2"

mkdir -p "$output_dir"

if [ ! -f "$input_gpkg" ]; then
  echo "Input geopackage not found: $input_gpkg" >&2
  exit 1
fi

layers=$(ogrinfo "$input_gpkg" | sed -n 's/^[[:space:]]*[0-9]\+:[[:space:]]*\([^[:space:]]\+\).*/\1/p')

has_layer() {
  local target="$1"
  local layer
  for layer in $layers; do
    if [ "$layer" = "$target" ]; then
      return 0
    fi
  done
  return 1
}

export_layer() {
  local layer="$1"
  local outfile="$2"

  if has_layer "$layer"; then
    echo "Exporting $layer -> $outfile"
    rm -f "$outfile"
    ogr2ogr -f Parquet "$outfile" "$input_gpkg" "$layer"
  else
    echo "Skipping missing layer: $layer"
  fi
}

export_layer "divides" "$output_dir/divides.parquet"
export_layer "divide-attributes" "$output_dir/divide-attributes.parquet"
export_layer "flowpaths" "$output_dir/flowpaths.parquet"
export_layer "flowpath-attributes" "$output_dir/flowpath-attributes.parquet"
export_layer "hydrolocations" "$output_dir/hydrolocations.parquet"
export_layer "nexus" "$output_dir/nexus.parquet"
export_layer "network" "$output_dir/network.parquet"
export_layer "lakes" "$output_dir/lakes.parquet"
export_layer "pois" "$output_dir/pois.parquet"

echo "Not generated from this geopackage: flowpath-attributes-ml.parquet"

# ---------------------------------------------------------------------------
# network_graph.json
# Build the adjacency graph used by the subsetter from the exported network.parquet.
# Edge format: [from_type, from_num, to_type, to_num]
# Type codes match subset.html: fp-/wb- = 0, cat- = 2, nex- = 1, tnx- = 4
# ---------------------------------------------------------------------------
network_parquet="$output_dir/network.parquet"
if [ -f "$network_parquet" ]; then
  echo "Building network_graph.json -> $output_dir/network_graph.json"
  Rscript - "$network_parquet" "$output_dir/network_graph.json" <<'REOF'
args   <- commandArgs(trailingOnly = TRUE)
net_pq <- args[1]
out_js <- args[2]

library(arrow)
library(dplyr)

net <- read_parquet(net_pq) |>
  select(flowpath_id, flowpath_toid, divide_id) |>
  distinct()

type_of <- function(id) {
  prefix <- sub("-.*", "", id)
  dplyr::case_when(
    prefix %in% c("fp", "wb") ~ 0L,
    prefix == "cat"            ~ 2L,
    prefix == "nex"            ~ 1L,
    prefix == "tnx"            ~ 4L,
    TRUE                       ~ 3L
  )
}
num_of <- function(id) as.integer(sub("^[^-]+-", "", id))

fp_edges  <- net |> distinct(flowpath_id, flowpath_toid) |>
  transmute(ft = type_of(flowpath_id), fn = num_of(flowpath_id),
            tt = type_of(flowpath_toid), tn = num_of(flowpath_toid))

cat_edges <- net |> distinct(divide_id, flowpath_toid) |>
  transmute(ft = 2L, fn = num_of(divide_id),
            tt = type_of(flowpath_toid), tn = num_of(flowpath_toid))

edges <- bind_rows(fp_edges, cat_edges) |> distinct()
edge_list <- lapply(seq_len(nrow(edges)), \(i) unname(as.list(edges[i, ])))

out <- list(
  meta  = list(total_edges = nrow(edges)),
  edges = edge_list
)
jsonlite::write_json(out, out_js, auto_unbox = TRUE)
cat("  ", nrow(edges), "edges written\n")
REOF
else
  echo "Skipping network_graph.json: network.parquet not found"
fi

# ---------------------------------------------------------------------------
# pmtiles
# Reproject divides + flowpaths from the source GPKG (which retains CRS
# metadata) to WGS84 GeoJSONSeq, then build pmtiles using the tippecanoe
# service defined in docker-compose.yml (built from github.com/felt/tippecanoe).
# ---------------------------------------------------------------------------
for lyr in divides flowpaths; do
  dst="$output_dir/${lyr}.geojsonseq"
  if has_layer "$lyr"; then
    echo "Reprojecting $lyr -> $dst (EPSG:4326)"
    rm -f "$dst"
    PROJ_DATA=/opt/conda/share/proj ogr2ogr -f GeoJSONSeq -t_srs EPSG:4326 "$dst" "$input_gpkg" "$lyr"
  else
    echo "Skipping $lyr.geojsonseq: layer not present in geopackage"
  fi
done

echo ""
echo "GeoJSONSeq files ready. To build pmtiles, run from the repo root:"
out_rel=$(echo "$output_dir" | sed "s|/ngen-workflow/||")
map_rel=$(echo "$out_rel" | sed "s|/parquet$|/map/only_geometry/reference|")
for lyr in divides flowpaths; do
  src="/ngen-workflow/${out_rel}/${lyr}.geojsonseq"
  dst="/ngen-workflow/${map_rel}/${lyr}.pmtiles"
  echo "  docker compose run --rm tippecanoe -o $dst -l $lyr --drop-densest-as-needed --force $src"
done