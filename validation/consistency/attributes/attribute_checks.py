"""Attribute Consistency Checks for GeoPackage Data Model specifications."""

import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

MODELS = Path(__file__).resolve().parents[1] / "models"


def quote(name):
    """Quote an SQLite identifier, which cannot be supplied as a parameter."""
    return '"' + name.replace('"', '""') + '"'


def finite(column, alias=None):
    """Require numeric SQLite storage and reject infinities without coercing text."""
    col = f"{alias}.{quote(column)}" if alias else quote(column)
    return f"typeof({col}) IN ('integer', 'real') AND {col} BETWEEN {-sys.float_info.max} AND {sys.float_info.max}"


def count(connection, table, condition, parameters=()):
    return connection.execute(f"SELECT COUNT(*) FROM {quote(table)} WHERE {condition}", parameters).fetchone()[0]


def length_comparison(connection, rule, columns, metrics, informational):
    """Compare only unique matched keys; count ambiguous and unmatched cases separately."""
    left, right = rule["left"], rule["right"]
    join = rule["join"][0]
    for side, key in ((left, join["left"]), (right, join["right"])):
        if not {side["column"], key} <= columns.get(side["table"], set()):
            return
    lt, rt = quote(left["table"]), quote(right["table"])
    lk, rk = quote(join["left"]), quote(join["right"])
    lv, rv = quote(left["column"]), quote(right["column"])
    # NextGen IDs are text. Compare their exact bytes regardless of column affinity
    # or collation, and group before joining to avoid arbitrary matches.
    groups = (
        f"WITH l AS (SELECT CAST({lk} AS BLOB) AS key, COUNT(*) AS n, MIN({lv}) AS value FROM {lt} "
        f"WHERE typeof({lk}) = 'text' GROUP BY CAST({lk} AS BLOB)), "
        f"r AS (SELECT CAST({rk} AS BLOB) AS key, COUNT(*) AS n, MIN({rv}) AS value FROM {rt} "
        f"WHERE typeof({rk}) = 'text' GROUP BY CAST({rk} AS BLOB)) "
    )
    identifier = rule["id"]
    for label, table, key in (("left", lt, lk), ("right", rt, rk)):
        informational[f"null_join_key_{label}_rows.{identifier}"] = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {key} IS NULL"
        ).fetchone()[0]
        informational[f"invalid_join_key_{label}_rows.{identifier}"] = connection.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {key} IS NOT NULL AND typeof({key}) != 'text'"
        ).fetchone()[0]
    for side in ("left", "right"):
        first, second = ("l", "r") if side == "left" else ("r", "l")
        informational[f"unmatched_{side}_rows.{identifier}"] = connection.execute(
            groups + f"SELECT COALESCE(SUM({first}.n), 0) FROM {first} LEFT JOIN {second} "
            f"ON {first}.key = {second}.key WHERE {second}.key IS NULL"
        ).fetchone()[0]
    informational[f"indeterminate_duplicate_keys.{identifier}"] = connection.execute(
        groups + "SELECT COUNT(*) FROM (SELECT key FROM l WHERE n > 1 UNION SELECT key FROM r WHERE n > 1)"
    ).fetchone()[0]
    valid = f"{finite('value', 'l')} AND {finite('value', 'r')}"
    diff = "(l.value - r.value * ?)"
    # Permit roundoff at the inclusive boundary without masking metre-scale errors.
    roundoff = f"min(1e-9, {4 * sys.float_info.epsilon} * max(abs(l.value * 1.0), abs(r.value * ?)))"
    result = connection.execute(
        groups + f"SELECT COALESCE(SUM(CASE WHEN {diff} NOT BETWEEN ? AND ? THEN 1 ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN {diff} BETWEEN ? AND ? AND abs({diff} * 1.0) - ? > {roundoff} THEN 1 ELSE 0 END), 0) "
        f"FROM l JOIN r ON l.key = r.key WHERE l.n = 1 AND r.n = 1 AND {valid}",
        (right["scale"], -sys.float_info.max, sys.float_info.max,
         right["scale"], -sys.float_info.max, sys.float_info.max, right["scale"], rule["max_absolute_difference"],
         right["scale"]),
    ).fetchone()
    metrics[f"nonfinite_calculation.{identifier}"], metrics[f"violations.{identifier}"] = result
    total, valid_pairs = connection.execute(
        groups + f"SELECT COUNT(*), COALESCE(SUM(CASE WHEN {valid} THEN 1 ELSE 0 END), 0) "
        "FROM l JOIN r ON l.key = r.key WHERE l.n = 1 AND r.n = 1"
    ).fetchone()
    informational[f"compared_pairs.{identifier}"] = valid_pairs - result[0]
    informational[f"indeterminate_operands.{identifier}"] = total - valid_pairs


def operand_diagnostics(connection, rules, columns, metrics, informational):
    """Report invalid and null values for available numeric rule operands."""
    operands = set()
    for rule in rules:
        if rule["kind"] in {"range", "interval"}:
            operands.add((rule["table"], rule["column"]))
        elif rule["kind"] == "scaled_difference":
            operands.update((rule[side]["table"], rule[side]["column"]) for side in ("left", "right"))
    # Diagnostics cover numeric operands even when the rule itself is inapplicable.
    for table, column in sorted(operands):
        if column not in columns.get(table, set()):
            continue
        col = quote(column)
        metrics[f"invalid_numeric.{table}.{column}"] = count(
            connection, table, f"{col} IS NOT NULL AND NOT ({finite(column)})"
        )
        informational[f"indeterminate_null.{table}.{column}"] = count(connection, table, f"{col} IS NULL")


def sentinel_counts(connection, spec, constraints, columns, metrics):
    """Count sentinel candidates across available numeric model columns."""
    # Sentinel candidates apply to every numeric model column, including
    # columns for which no physical bound has been established.
    candidates = [sentinel["value"] for sentinel in constraints["sentinels"]]
    numeric_types = {"INTEGER", "MEDIUMINT", "REAL", "BOOLEAN"}
    for table, definition in spec["tables"].items():
        present = [column["name"] for column in definition["columns"]
                   if column["type"].upper() in numeric_types and column["name"] in columns.get(table, set())]
        if not present or not candidates:
            continue
        placeholders = ", ".join("?" for _ in candidates)
        expressions = [f"COALESCE(SUM(CASE WHEN {finite(column)} AND {quote(column)} IN ({placeholders}) "
                       f"THEN 1 ELSE 0 END), 0)" for column in present]
        totals = connection.execute(
            f"SELECT {', '.join(expressions)} FROM {quote(table)}", candidates * len(present)
        ).fetchone()
        metrics.update({f"sentinel.{table}.{column}": total for column, total in zip(present, totals)})


def evaluate_rules(connection, rules, columns, metrics, informational):
    """Evaluate applicable rules and return the number evaluated."""
    evaluated = 0
    for rule in rules:
        if rule["kind"] == "scaled_difference":
            length_comparison(connection, rule, columns, metrics, informational)
            if f"violations.{rule['id']}" in metrics:
                evaluated += 1
            else:
                informational[f"not_evaluated.{rule['id']}"] = 1
            continue
        if rule["kind"] not in {"range", "interval"}:
            continue
        table, column = rule["table"], rule["column"]
        if column not in columns.get(table, set()):
            informational[f"not_evaluated.{rule['id']}"] = 1
            continue
        condition = rule["applies_when"]
        where = finite(column)
        if condition["kind"] == "column_equals":
            flag = condition["column"]
            if flag not in columns[table]:
                informational[f"not_evaluated.{rule['id']}"] = 1
                continue
            flag_sql = quote(flag)
            valid = f"typeof({flag_sql}) = 'integer' AND {flag_sql} IN (0, 1)"
            informational[f"indeterminate_applicability.{rule['id']}"] = count(
                connection, table, f"NOT ({valid})"
            )
            where += f" AND {valid} AND {flag_sql} = 1"
        col = quote(column)
        if rule["kind"] == "range":
            operator = {"gt": ">", "ge": ">="}[rule["operator"]]
            expression, parameters = f"{col} {operator} ?", (rule["value"],)
        else:
            lower = ">=" if rule["lower_inclusive"] else ">"
            upper = "<=" if rule["upper_inclusive"] else "<"
            expression, parameters = f"{col} {lower} ? AND {col} {upper} ?", (rule["lower"], rule["upper"])
        metrics[f"violations.{rule['id']}"] = count(connection, table, f"{where} AND NOT ({expression})", parameters)
        evaluated += 1
    return evaluated


def unchecked_inventory(spec, rules, informational):
    """List model columns without range or interval rules."""
    bounded = {(rule["table"], rule["column"]) for rule in rules
               if rule["kind"] in {"range", "interval"}}
    for table, definition in spec["tables"].items():
        for column in definition["columns"]:
            name = column["name"]
            if (table, name) not in bounded:
                informational[f"not_checked.{table}.{name}"] = 1


def attributes(path, model, kind):
    """Evaluate the selected Data Model's attribute rules without changing the file."""
    if model != "v2.2" or kind not in {"ngen", "reference"}:
        raise ValueError(f"no attribute checks for Data Model {model!r}, output kind {kind!r}")
    with (MODELS / model / f"{kind}.json").open(encoding="utf-8") as stream:
        spec = json.load(stream)
    constraints = spec["attribute_constraints"]
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        columns = {table: {row[1] for row in connection.execute("SELECT * FROM pragma_table_info(?)", (table,))}
                   for table in tables}
        metrics, informational = {}, {}
        rules = constraints["rules"]
        operand_diagnostics(connection, rules, columns, metrics, informational)
        sentinel_counts(connection, spec, constraints, columns, metrics)
        if not evaluate_rules(connection, rules, columns, metrics, informational):
            metrics["no_applicable_checks"] = 1
        unchecked_inventory(spec, rules, informational)
        return metrics, informational
