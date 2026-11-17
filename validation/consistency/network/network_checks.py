"""Network Consistency Checks for GeoPackages of a selected Data Model.

The Data Model's ``checks.network`` section declares the primary keys, layer
relationships and routing convention (see ``data_model.py``). Routing and
hydrosequence checks identify their layers by the names ``flowpaths``,
``nexus``, ``network`` and ``divides`` and their columns by ``id``, ``toid``,
``hydroseq``, ``dnhydroseq`` and ``topo``; a model must use those names to use
those checks (a documented implementation extension).
"""

import sqlite3
from contextlib import closing

import data_model

from . import network_hydroseq, network_relationships, network_routing


def quote(name):
    """Quote an SQLite identifier, which cannot be supplied as a parameter."""
    return '"' + name.replace('"', '""') + '"'


def network(path, model, kind):
    """Report network metrics for one GeoPackage without changing it."""
    spec = data_model.load_spec(model, kind, "network")
    semantics = data_model.network_semantics(spec)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {
            name: {row[1] for row in connection.execute("SELECT * FROM pragma_table_info(?)", (name,))}
            for name in tables
        }
        metrics = {}
        for table, key in semantics["primary_ids"].items():
            if key not in columns.get(table, set()):
                continue
            table_sql, key_sql = quote(table), quote(key)
            metrics[f"duplicate_primary_ids.{table}"] = connection.execute(
                f"SELECT COALESCE(SUM(n - 1), 0) FROM "
                f"(SELECT COUNT(*) AS n FROM {table_sql} WHERE {key_sql} IS NOT NULL GROUP BY {key_sql})"
            ).fetchone()[0]
        for check in (network_routing, network_relationships, network_hydroseq):
            metrics.update(check.metrics(connection, columns, semantics))
        if not metrics:
            metrics["no_applicable_checks"] = 1
        return metrics
