#!/usr/bin/env python3

import argparse
import csv
import sqlite3
from pathlib import Path


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_contents(conn: sqlite3.Connection):
    if table_exists(conn, "gpkg_contents"):
        return conn.execute(
            """
            SELECT
                table_name,
                data_type,
                identifier,
                description
            FROM gpkg_contents
            ORDER BY table_name
            """
        ).fetchall()

    return conn.execute(
        """
        SELECT name AS table_name, NULL AS data_type, NULL AS identifier, NULL AS description
        FROM sqlite_master
        WHERE type='table'
          AND name NOT LIKE 'sqlite_%'
        ORDER BY name
        """
    ).fetchall()


def get_geometry_metadata(conn: sqlite3.Connection):
    if not table_exists(conn, "gpkg_geometry_columns"):
        return {}

    rows = conn.execute(
        """
        SELECT
            table_name,
            column_name,
            geometry_type_name,
            srs_id,
            z,
            m
        FROM gpkg_geometry_columns
        """
    ).fetchall()

    return {
        (row["table_name"], row["column_name"]): {
            "geometry_type": row["geometry_type_name"],
            "srs_id": row["srs_id"],
            "z": row["z"],
            "m": row["m"],
        }
        for row in rows
    }


def get_data_column_metadata(conn: sqlite3.Connection):
    if not table_exists(conn, "gpkg_data_columns"):
        return {}

    rows = conn.execute(
        """
        SELECT
            table_name,
            column_name,
            name,
            title,
            description,
            mime_type,
            constraint_name
        FROM gpkg_data_columns
        """
    ).fetchall()

    return {
        (row["table_name"], row["column_name"]): {
            "name": row["name"],
            "title": row["title"],
            "description": row["description"],
            "mime_type": row["mime_type"],
            "constraint_name": row["constraint_name"],
        }
        for row in rows
    }


def dump_metadata(gpkg_path: Path, csv_path: Path, include_system: bool = False):
    conn = sqlite3.connect(str(gpkg_path))
    conn.row_factory = sqlite3.Row

    contents = get_contents(conn)
    geom_meta = get_geometry_metadata(conn)
    data_col_meta = get_data_column_metadata(conn)

    fieldnames = [
        "table_name",
        "data_type",
        "identifier",
        "table_description",
        "column_name",
        "ordinal_position",
        "column_type",
        "not_null",
        "default_value",
        "primary_key",
        "geometry_type",
        "srs_id",
        "z",
        "m",
        "data_column_name",
        "column_title",
        "column_description",
        "mime_type",
        "constraint_name",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for item in contents:
            table_name = item["table_name"]

            if not include_system and (
                table_name.startswith("gpkg_") or table_name.startswith("rtree_")
            ):
                continue

            pragma_sql = f"PRAGMA table_info({quote_ident(table_name)})"
            columns = conn.execute(pragma_sql).fetchall()

            for col in columns:
                key = (table_name, col["name"])
                geom = geom_meta.get(key, {})
                data_meta = data_col_meta.get(key, {})

                writer.writerow(
                    {
                        "table_name": table_name,
                        "data_type": item["data_type"],
                        "identifier": item["identifier"],
                        "table_description": item["description"],
                        "column_name": col["name"],
                        "ordinal_position": col["cid"],
                        "column_type": col["type"],
                        "not_null": col["notnull"],
                        "default_value": col["dflt_value"],
                        "primary_key": col["pk"],
                        "geometry_type": geom.get("geometry_type"),
                        "srs_id": geom.get("srs_id"),
                        "z": geom.get("z"),
                        "m": geom.get("m"),
                        "data_column_name": data_meta.get("name"),
                        "column_title": data_meta.get("title"),
                        "column_description": data_meta.get("description"),
                        "mime_type": data_meta.get("mime_type"),
                        "constraint_name": data_meta.get("constraint_name"),
                    }
                )

    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Dump GeoPackage attribute metadata to CSV."
    )
    parser.add_argument("gpkg", type=Path, help="Path to the .gpkg file")
    parser.add_argument("csv", type=Path, help="Path to the output .csv file")
    parser.add_argument(
        "--include-system",
        action="store_true",
        help="Include gpkg_* and rtree_* tables",
    )
    args = parser.parse_args()

    dump_metadata(args.gpkg, args.csv, include_system=args.include_system)
    print(f"Wrote metadata to {args.csv}")


if __name__ == "__main__":
    main()