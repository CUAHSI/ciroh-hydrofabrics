#!/usr/bin/env Rscript

#title: "Add NOAH OWP Variables to the NGEN HydroFabric"
#date: "2026-05-05"

suppressPackageStartupMessages({
  library(optparse)
  library(sf)
  library(terra)
  library(zonal)
  library(dplyr)
  library(powerjoin)
  library(arrow)
  library(glue)
}) 

# Suppress warnings
options(warn = -1)

option_list <- list(
  make_option("--nextgen_geopackage", type = "character", help = "Path to nextgen geopackage"),
  make_option("--soil_data",          type = "character", help = "Path to soil data"),
  make_option("--gw_params",          type = "character", help = "Path to GW params"),
  make_option("--dem",                type = "character", help = "Path to DEM")
)

params <- parse_args(OptionParser(option_list = option_list))




# define output file paths. These will be saved in the same
# directory as the input nextgen geopackage.
output_basepath <- dirname(params$nextgen_geopackage)
output_parquet <- file.path(output_basepath, "vaa_noahowp.parquet")
output_nextgen_geopackage <- file.path(output_basepath, "ngen_hydrofabric_vaa.gpkg")



# read layers from the input nextgen geopackage
message("reading layers from the input nextgen geopackage")
divides <- read_sf(params$nextgen_geopackage, "divides")

###################
# SOIL PARAMETERS #
###################

nom_vars <- c("bexp", "dksat", "psisat", "smcmax", "smcwlt")
layers <- 1:4
files <- as.vector(glue("{params$soil_data}/{rep(nom_vars, each = 4)}_soil_layers_stag={rep(layers, times= length(nom_vars))}.tif"))

# read the input rasters into memory.
bexp_rasters <- rast(files[1:4])
dksat_rasters <- rast(files[5:8]) 
psisat_rasters <- rast(files[9:12]) 
smcmax_rasters <- rast(files[13:16]) 
smcwlt_rasters <- rast(files[17:20]) 
refkdt_raster <- rast(glue("{params$soil_data}/refkdt.tif"))
mp_raster <- rast(glue("{params$soil_data}/mp.tif"))
mfsno_raster <- rast(glue("{params$soil_data}/mfsno.tif"))
cwpvt_raster <- rast(glue("{params$soil_data}/cwpvt.tif"))
vcmx25_raster <- rast(glue("{params$soil_data}/vcmx25.tif"))

# Get Mode Beta parameter
message("deriving the 'beta' parameter using zonal statistics")
modes = execute_zonal(bexp_rasters,
                    fun = "mode",
                    divides, ID = "divide_id", 
                    join = FALSE)

# Get Geometric Mean of Saturated soil hydraulic conductivity, and matric potential
message("deriving saturated soil hydraulic conductivity using zonal statistics")
gm = execute_zonal(c(dksat_rasters, psisat_rasters), 
                   fun = geometric_mean,
                   divides, ID = "divide_id", 
                   join = FALSE)
gm <- gm %>%
     rename_with(~paste0("geom_mean.", .), -divide_id)

# Get Mean Saturated value of soil moisture and Wilting point soil moisture
message("deriving the saturated soil moisture and wilting point soil moisture parameters")
m = execute_zonal(c(smcmax_rasters, smcwlt_rasters),
                    fun = "mean",
                    divides, ID = "divide_id", 
                    join = FALSE)


# Compute the mean refkdt, mp, mfsno, cwpvt, and vcmx25 for each divide_id
message("deriving mean refkdt, mp, mfsno, cwpvt, and vcmx25 for each divide")
noah_divide_params = execute_zonal(c(refkdt_raster, mp_raster, mfsno_raster, cwpvt_raster, vcmx25_raster),
                    fun = "mean",
                    divides, ID = "divide_id", 
                    join = FALSE)

# Merge all tables into one
message("merging the derived parameters into a single table")
d1 <- power_full_join(list(modes, gm, m, noah_divide_params),  by = "divide_id")
message(paste(names(d1), collapse = ", "))


##################################
# GROUNDWATER ROUTING PARAMETERS #
##################################


# what was once refered to as "conus_routelink" appears to be the
# nwm_gw_basins parquet file. This doesn't have a field called "hf_id",
# but I think this has been renamed "reference_id".
# TODO: Check with Mike that this assumption is correct
message('reading the crosswalk between the nextgen network and the nwm_gw_basins')
crosswalk <- read_sf(params$nextgen_geopackage, "network") |>
    select(reference_id, divide_id) |>
    collect()


# I modified the code here to use the "reference_id" field instead of "hf_id" for
# for the left portion of the join, and changed "hf_id" to "COMID" for the right 
# portion of the join.
# TODO: Check with Mike that this assumption is correct, and that the "reference_id"
# field in the network layer corresponds to the "COMID" field in the nwm_gw_basins table.
#
# Other changes I've made:
#   - removed the "gw_" prefix from setGenericw_Zmax, gw_Area_sqkm, gw_Coeff, and gw_Expon since
#     the nwm_gw_basins does not have these.
#   - added mutations to make sure that both ComID and reference_id are integers before the join
message("computing the mean groundwater routing parameters for each divide_id")
d2 <- open_dataset(params$gw_params) |>
    mutate(ComID = as.integer(ComID)) |>
    select(ComID , Coeff, Area_sqkm, Zmax, Expon) |>
    inner_join(mutate(crosswalk, reference_id = as.integer(reference_id)),
               by = c("ComID" = "reference_id")) |>
    group_by(divide_id) |>
    collect() |>
    summarize(
      mean.Coeff = round(weighted.mean(Coeff, w = Area_sqkm, na.rm = TRUE), 9),
      mean.Zmax  = round(weighted.mean(Zmax,  w = Area_sqkm, na.rm = TRUE), 9),
      mean.Expon = mode(floor(Expon))
    )
message(paste(names(d2), collapse = ", "))


################################
# ELEVATION-DERIVED PARAMETERS #
################################

# centroid of each divide
message("computing the centroid of each divide")
d3 <- st_centroid(divides) |>
  st_coordinates() |>
  data.frame() |>
  rename(centroid_x = X, centroid_y = Y) |>
  mutate(divide_id = divides$divide_id)
message(paste(names(d3), collapse = ", "))

# Load the input DEM and then compute slope and aspect
# rasters using the terra package.
dem_raster <- rast(params$dem)

message("DEM processing requirements:")
message("  DEM size: ", nrow(dem_raster), " x ", ncol(dem_raster))
message("  DEM memory: ", terra::mem_info(dem_raster))
message("  DEM in memory: ", terra::inMemory(dem_raster))

message("computing slope raster from the input DEM, saving to /tmp/slope.tif")
slope_raster <- terrain(dem_raster, v = "slope", unit = "degrees")
writeRaster(slope_raster, "/tmp/slope.tif", overwrite = TRUE)

message("computing aspect raster from the input DEM, saving to /tmp/aspect.tif")
aspect_raster <- terrain(dem_raster, v = "aspect", unit = "degrees")
writeRaster(slope_raster, "/tmp/aspect.tif", overwrite = TRUE)


# terrain() writes to a temp file; force both derived rasters into memory
# so exactextractr's C++ layer can read values without hitting a stale temp path.
#slope_raster <- setValues(rast(dem_raster), values(slope_raster))
#aspect_raster <- setValues(rast(dem_raster), values(aspect_raster))

# compute zonal statistics for elevation, slope, and aspect.
message("computing mean elevation and mean slope for each divide_id")
d4 <- execute_zonal(c(dem_raster, rast('/tmp/slope.tif')),
                    divides, ID = "divide_id",
                    fun = "mean",
                    join = FALSE) |>
    setNames(c("divide_id", "mean.elevation", "mean.slope"))

message(paste(names(d4), collapse = ", "))

message("computing circular mean aspect for each divide_id")
d5 <- execute_zonal(rast('/tmp/aspect.tif'),
                     divides, ID = "divide_id",
                     fun = circular_mean,
                     join = FALSE) |>
    setNames(c("divide_id", "circ_mean.aspect"))
message(paste(names(d5), collapse = ", "))


##################################
# BUILDING FINAL ATTRIBUTE TABLE #
##################################

# Save the attributes to a sidecar parquet file.
message("combining all derived attributes into a single table")
model_attributes <- power_full_join(list(d1, d2, d3, d4, d5), by = "divide_id")

# save the computed model_attributes to a parquet file.
message('saving the derived attributes to a parquet file')
write_parquet(model_attributes, output_parquet)

# Copy the input geopackage to a new file, then add the attributes
message("adding the derived attributes to the nextgen geopackage")
file.copy(params$nextgen_geopackage, output_nextgen_geopackage)

# add the model_attributes to the divide_attributes layer in the nextgen geopackage. 
# drop Zmax if it already exists in the geopackage,
# this may have already been added during the 'calculate minimal attributes'
# stage of the workflow. We want to replace this value with what we've computed here.
gdf <- st_read(output_nextgen_geopackage, layer = "divide-attributes")
gdf <- gdf |> select(-any_of("mean.Zmax"))

# add the model_attributes to the divide_attributes layer in the nextgen
# geopackage, then save the updated geopackage to disk.
gdf_joined <- left_join(gdf, model_attributes, by = "divide_id")
st_write(gdf_joined, output_nextgen_geopackage, layer = "divide-attributes", delete_layer = TRUE)

