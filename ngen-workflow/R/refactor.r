#!/usr/bin/env Rscript

# title: "Refactor HF"
# date: "2026-02-06"

suppressPackageStartupMessages({
  library(optparse)
  library(sf)
  library(dplyr)
  library(hfrefactor)
})


# Suppress warnings
options(warn = -1)

# Override R's debugger browser() to a no-op
# There are sections in hfrefactor that have browser
# breakpoints that we want to skip over.
if (!interactive()) {
  assignInNamespace("browser", function(...) invisible(NULL), "base")
}

option_list <- list(
  make_option("--fac_file", type = "character", help = "Path to FAC file"),
  make_option("--fdr_file", type = "character", help = "Path to FDR file"),
  make_option("--nextgen_geopackage", type = "character", help = "Path to nextgen geopackage"),
  make_option("--out_file", type = "character", help = "Path to output geopackage"),
  make_option("--split_flines_meters", type = "numeric", help = "Distance in meters to split flowlines"),
  make_option("--collapse_flines_meters", type = "numeric", help = "Distance in meters to collapse flowlines"),
  make_option("--collapse_flines_main_meters", type = "numeric", help = "Distance in meters to collapse main flowlines"),
  make_option("--simplify_tolerance_m", type = "numeric", help = "Tolerance in meters to simplify flowlines")
)

params <- parse_args(OptionParser(option_list = option_list))


Sys.setenv(GDAL_SQLITE_LOAD_EXTENSIONS = "YES")


## TODO: TC I originally wrote this so that hydrolocations could be included
##       as POIs (events) but I believe this is an incorrect assumption.
##       The hydrolocations are not necessarily POIs, so this code is 
##       commented out for now but could be useful in the future
##       if we allow POIs as in input argument to this function.
##
## Enrich POIs with reach measurement columns needed by split_flowlines.
## The parquet hydrolocation format stores these differently from NHD-style events:
##   reachmeas -> REACH_meas  (already on events)
##   reachcode/frommeas/tomeas -> joined from the flowpath network
#message("Building POIS Dataframe from hydrolocations")
#pois_df <- sf::read_sf(params$nextgen_geopackage, layer = "hydrolocations")
#fp_meas <- sf::read_sf(params$nextgen_geopackage, "flowpaths") |>
#  sf::st_drop_geometry() |>
#  dplyr::select(flowpath_id, REACHCODE = reachcode, FromMeas = frommeas, ToMeas = tomeas) |>
#  dplyr::mutate(flowpath_id = as.character(flowpath_id))
#
#pois_df <- pois_df |>
#  dplyr::mutate(flowpath_id = as.character(flowpath_id),
#                COMID        = flowpath_id,
#                identifier   = as.integer(poi_id)) |>
#  dplyr::left_join(fp_meas, by = "flowpath_id") |>
#  dplyr::rename(REACH_meas = reachmeas)


message("Running Refactor on the NGEN HydroFabric")
refactor(
  gpkg      = params$nextgen_geopackage,
  fac       = params$fac_file,
  fdr       = params$fdr_file,
  outfile   = params$out_file,
  split_flines_meters = params$split_flines_meters,
  collapse_flines_meters      = params$collapse_flines_meters,
  collapse_flines_main_meters = params$collapse_flines_main_meters,
  simplify_tolerance_m        = params$simplify_tolerance_m,
)
