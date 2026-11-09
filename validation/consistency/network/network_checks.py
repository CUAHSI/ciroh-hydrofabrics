"""Network Consistency Checks for v2.2 GeoPackages."""

import sqlite3
from contextlib import closing

from . import network_hydroseq, network_relationships, network_routing


PRIMARY_IDS = {
    "reference": {"divides": "divide_id", "flowpaths": "id", "hydrolocations": "hl_id"},
    "ngen": {
        "divides": "divide_id", "flowpaths": "id", "nexus": "id", "lakes": "lake_id", "pois": "poi_id",
        "divide-attributes": "divide_id", "flowpath-attributes": "id", "flowpath-attributes-ml": "id",
    },
}


def quote(name):
    """Quote an SQLite identifier, which cannot be supplied as a parameter."""
    return '"' + name.replace('"', '""') + '"'


def network(path, model, kind):
    """Report network metrics for one GeoPackage without changing it."""
    if model != "v2.2" or kind not in PRIMARY_IDS:
        raise ValueError(f"no network checks for Data Model {model!r}, output kind {kind!r}")
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {
            name: {row[1] for row in connection.execute("SELECT * FROM pragma_table_info(?)", (name,))}
            for name in tables
        }
        metrics = {}
        for table, key in PRIMARY_IDS[kind].items():
            if key not in columns.get(table, set()):
                continue
            table_sql, key_sql = quote(table), quote(key)
            metrics[f"duplicate_primary_ids.{table}"] = connection.execute(
                f"SELECT COALESCE(SUM(n - 1), 0) FROM "
                f"(SELECT COUNT(*) AS n FROM {table_sql} WHERE {key_sql} IS NOT NULL GROUP BY {key_sql})"
            ).fetchone()[0]
        for check in (network_routing, network_relationships, network_hydroseq):
            metrics.update(check.metrics(connection, kind, columns))
        if not metrics:
            metrics["no_applicable_checks"] = 1
        return metrics
