#!/usr/bin/env python3

"""
This script performs topology fixing on a given input hydrofabric geodatabase
using a CSV file that describes the corrections to apply.
"""

import shutil
from pathlib import Path

import geopandas as gpd
import pandas as pd
import sqlite3
import typer


app = typer.Typer()


def apply_flowpath_topology_fixes(
    gdf: gpd.GeoDataFrame, corrections: pd.DataFrame
) -> gpd.GeoDataFrame:
    """
    Apply topological corrections to the GeoDataFrame.

    Args:
        gdf: Input GeoDataFrame loaded from the geodatabase.
        corrections: DataFrame containing topology fix instructions.

    Returns:
        Corrected GeoDataFrame.
    """

    # Always skip the first column in the input corrections dataset.
    # This is expected to be the identifier used to match rows in the gdf
    lookup_col = corrections.columns[0]

    for idx, row in corrections.iterrows():
        fpid = row["flowpath_id"]

        # get the row in the gdf corresponding to this flowpath_id
        match = gdf[gdf["flowpath_id"] == row[lookup_col]]

        # loop over the columns in the corrections dataset,
        # skipping the first one (the identifier). Apply
        # changes to the gdf where the value in the corrections
        # dataset is not NaN.
        for col in corrections.columns[1:]:

            # some error handling for missing columns and matches
            if (col not in gdf.columns) or (len(match) == 0) or (len(match) > 1):
                pass
            # apply correction if the value in the corrections dataset is not NaN
            if pd.notna(row[col]):
                gdf.loc[match.index, col] = row[col]

    return gdf


@app.command()
def fix_topology(
    gdb: Path = typer.Argument(
        ...,
        help="Path to the input geodatabase (.gpkg or .gdb).",
    ),
    csv: Path = typer.Argument(
        ...,
        help="Path to the CSV file describing topology corrections.",
    ),
    output: Path = typer.Argument(
        ...,
        help="Path to write the corrected geodatabase. Defaults to <gdb>_fixed.gpkg.",
    ),
) -> None:
    """Apply topological fixes to a hydrofabric geodatabase using a corrections CSV."""

    typer.echo(f"Loading geodatabase: {gdb}")
    flowpaths = gpd.read_file(gdb, layer="flowpaths")

    typer.echo(f"Loading corrections: {csv}")
    corrections = pd.read_csv(
        csv,
        comment="#",
        dtype={
            "flowpath_id": "Int32",
            "flowpath_toid": "Int32",
            "streamorder": "Int32",
        },
    )

    typer.echo(f"  {len(flowpaths)} features loaded")
    typer.echo(f"  {len(corrections)} corrections will be applied")

    typer.echo("Applying topology fixes to flowpaths...")
    corrected_flowpaths = apply_flowpath_topology_fixes(flowpaths, corrections)

    typer.echo("Applying topology fixes to network...")
    corrected_network = apply_flowpath_topology_fixes(
        gpd.read_file(gdb, layer="network"), corrections
    )

    #    breakpoint()
    # copy the input gdf to the output location,
    # then overwrite the layers with the corrected gdf
    typer.echo(f"Writing output: {output}")
    shutil.copy(gdb, output)
    corrected_flowpaths.to_file(output, driver="GPKG", layer="flowpaths")
    with sqlite3.connect(output) as conn:
        corrected_network.to_sql("network", conn, if_exists="replace", index=False)
    #    corrected_network.to_file(output, driver="GPKG", layer="network")

    typer.echo("Done.")


if __name__ == "__main__":
    app()
