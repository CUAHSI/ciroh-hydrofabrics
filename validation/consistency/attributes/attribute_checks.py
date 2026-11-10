"""Attribute Consistency Checks for GeoPackage Data Model specifications."""

import json
import re
import sqlite3
import sys
from contextlib import closing
from fractions import Fraction
from pathlib import Path

from attributes.specification import (
    numeric_declaration,
    unique_json_object,
    validate_attribute_rules,
)

MODELS = Path(__file__).resolve().parents[1] / "models"


def quote(name):
    """Quote an SQLite identifier, escaping embedded double quotes.

    Parameters
    ----------
    name : str
        Identifier to quote; SQLite parameters cannot stand in for identifiers.

    Returns
    -------
    str
        Double-quoted SQLite identifier.
    """
    return '"' + name.replace('"', '""') + '"'


def finite(column, alias=None):
    """Build a predicate for finite values stored as SQLite numbers.

    The predicate accepts integer and real storage classes within the finite
    floating-point range; it does not coerce text to numbers.

    Parameters
    ----------
    column : str
        Column name to quote in the predicate.
    alias : str, optional
        SQL table alias to prefix to the quoted column name.

    Returns
    -------
    str
        SQLite predicate for a finite numeric value.
    """
    col = f"{alias}.{quote(column)}" if alias else quote(column)
    return f"typeof({col}) IN ('integer', 'real') AND {col} BETWEEN {-sys.float_info.max} AND {sys.float_info.max}"


def count(connection, table, condition, parameters=()):
    """Count rows satisfying a supplied SQLite condition.

    Parameters
    ----------
    connection : sqlite3.Connection
        Connection containing the table.
    table : str
        Table name, quoted as an SQLite identifier.
    condition : str
        SQL expression used as the WHERE clause.
    parameters : sequence, optional
        Values bound to placeholders in ``condition``.

    Returns
    -------
    int
        Number of rows for which the condition is true.
    """
    return connection.execute(f"SELECT COUNT(*) FROM {quote(table)} WHERE {condition}", parameters).fetchone()[0]


def exact_scaled_violation(left, right, scale, tolerance):
    """Resolve a borderline scaled comparison using exact stored values.

    Parameters
    ----------
    left, right : int or float
        Finite SQLite operands, preserving their integer or binary64 values.
    scale, tolerance : int or float
        Finite rule values, with positive scale and nonnegative tolerance.

    Returns
    -------
    bool
        Whether the exact difference exceeds the tolerance plus the documented
        roundoff allowance, evaluated without intermediate rounding or overflow.
    """
    left, right = Fraction(left), Fraction(right)
    scale, tolerance = Fraction(scale), Fraction(tolerance)
    scaled = right * scale
    allowance = min(
        Fraction(1e-9), tolerance * Fraction(1e-9),
        Fraction(4 * sys.float_info.epsilon) * max(abs(left), abs(scaled)),
    )
    return abs(left - scaled) > tolerance + allowance


def length_comparison(connection, rule, columns, metrics, informational):
    """Compare scaled values for uniquely matched text join keys.

    Keys are matched by exact bytes using the rule's single join. Only
    pairs with one row on each side and finite numeric operands are compared.
    The right operand is scaled before calculating the difference; the
    tolerance allows a small adjustment for floating-point roundoff. SQL
    evaluates clear cases in bulk; borderline cases use exact arithmetic on
    the stored values and the rule's numeric literals.

    Parameters
    ----------
    connection : sqlite3.Connection
        Connection containing the operand tables.
    rule : dict
        A ``scaled_difference`` entry from ``attribute_constraints.rules``,
        with an ``id``, ``kind``, left and right table/column operands,
        applicability, join columns, right-side scale, and
        ``max_absolute_difference`` tolerance.
    columns : dict of str to set of str
        Available column names by table.
    metrics : dict
        Updated in place with nonfinite-calculation and violation counts
        keyed by rule ID.
    informational : dict
        Updated in place with null and invalid join-key row counts, unmatched
        row counts, duplicate-key counts, compared-pair counts, and
        indeterminate-operand and precision-indeterminate counts, keyed by
        rule ID.

    Returns
    -------
    None
        If either operand or join column is absent, neither dictionary is
        updated for this rule.
    """
    left, right = rule["left"], rule["right"]
    join = rule["join"][0]
    for side, key in ((left, join["left"]), (right, join["right"])):
        if not {side["column"], key} <= columns.get(side["table"], set()):
            return
    lt, rt = quote(left["table"]), quote(right["table"])
    lk, rk = quote(join["left"]), quote(join["right"])
    lv, rv = quote(left["column"]), quote(right["column"])
    # Supported join keys are text. Compare exact bytes regardless of column
    # affinity or collation, and group before joining to avoid arbitrary matches.
    groups = (
        f"WITH l AS (SELECT CAST({lk} AS BLOB) AS key, COUNT(*) AS n, MIN({lv}) AS value FROM main.{lt} "
        f"WHERE typeof({lk}) = 'text' GROUP BY CAST({lk} AS BLOB)), "
        f"r AS (SELECT CAST({rk} AS BLOB) AS key, COUNT(*) AS n, MIN({rv}) AS value FROM main.{rt} "
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
    finite_operands = f"{finite('value', 'l')} AND {finite('value', 'r')}"
    # Large SQLite integers cannot always be converted to binary64 exactly.
    large_integer = (
        "(typeof(l.value) = 'integer' AND (l.value < -9007199254740992 OR l.value > 9007199254740992)) "
        "OR (typeof(r.value) = 'integer' AND (r.value < -9007199254740992 OR r.value > 9007199254740992))"
    )
    scale = right["scale"]
    exact_integer = (
        f"typeof(l.value) = 'integer' AND typeof(r.value) = 'integer' "
        f"AND typeof(l.value - r.value * {scale}) = 'integer'"
        if type(scale) is int else "0"
    )
    valid = f"({finite_operands}) AND NOT (({large_integer}) AND NOT ({exact_integer}))"

    # SQL handles clearly separated cases in bulk. A conservative error bound
    # covers conversions, multiplication, subtraction, and allowance rounding;
    # only pairs whose classification might change need exact arithmetic. The
    # magnitude floor keeps the bound nonzero for subnormal computations.
    pairs = (
        groups + f", pairs AS (SELECT l.value AS left_value, r.value AS right_value, "
        f"r.value * :scale AS scaled, l.value - r.value * :scale AS diff "
        f"FROM l JOIN r ON l.key = r.key WHERE l.n = 1 AND r.n = 1 AND {valid}) "
    )
    roundoff = (
        f"min(1e-9, :tolerance * 1e-9, {4 * sys.float_info.epsilon} * "
        "max(abs(left_value * 1.0), abs(scaled * 1.0)))"
    )
    uncertainty = (
        f"({8 * sys.float_info.epsilon} * "
        "max(abs(left_value * 1.0), abs(scaled * 1.0), abs(:tolerance * 1.0), 1e-300) + 1e-323)"
    )
    margin = "(abs(diff * 1.0) - :tolerance)"
    violation = f"{margin} > {roundoff} + {uncertainty}"
    passing = f"{margin} < {roundoff} - {uncertainty}"
    ambiguous = f"NOT ({violation} OR {passing})"
    finite_diff = "diff BETWEEN :min_float AND :max_float"
    parameters = {"scale": scale, "tolerance": rule["max_absolute_difference"],
                  "min_float": -sys.float_info.max, "max_float": sys.float_info.max}
    nonfinite, violations, uncertain = connection.execute(
        pairs + f"SELECT COALESCE(SUM(CASE WHEN NOT ({finite_diff}) THEN 1 ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN {finite_diff} AND {violation} THEN 1 ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN {finite_diff} AND {ambiguous} THEN 1 ELSE 0 END), 0) FROM pairs",
        parameters,
    ).fetchone()
    if uncertain:
        for left_value, right_value in connection.execute(
                pairs + f"SELECT left_value, right_value FROM pairs WHERE {finite_diff} AND {ambiguous}",
                parameters):
            violations += exact_scaled_violation(left_value, right_value, scale, rule["max_absolute_difference"])
    metrics[f"nonfinite_calculation.{identifier}"] = nonfinite
    metrics[f"violations.{identifier}"] = violations
    total, finite_pairs, valid_pairs = connection.execute(
        groups + f"SELECT COUNT(*), COALESCE(SUM(CASE WHEN {finite_operands} THEN 1 ELSE 0 END), 0), "
        f"COALESCE(SUM(CASE WHEN {valid} THEN 1 ELSE 0 END), 0) "
        "FROM l JOIN r ON l.key = r.key WHERE l.n = 1 AND r.n = 1"
    ).fetchone()
    informational[f"compared_pairs.{identifier}"] = valid_pairs - nonfinite
    informational[f"indeterminate_operands.{identifier}"] = total - finite_pairs
    informational[f"indeterminate_precision.{identifier}"] = finite_pairs - valid_pairs


def operand_diagnostics(connection, rules, columns, metrics, informational):
    """Report invalid and null values for available numeric rule operands.

    Each distinct operand is diagnosed once, regardless of whether its rule
    can be evaluated or applies to a particular row. Non-null values that are
    not finite SQLite integers or reals are invalid; nulls are indeterminate.

    Parameters
    ----------
    connection : sqlite3.Connection
        Connection containing the operand tables.
    rules : sequence of dict
        Entries from ``attribute_constraints.rules``, each describing an ID,
        kind, operands, applicability, and limits. Scaled-difference entries
        also carry join and tolerance information.
    columns : dict of str to set of str
        Available column names by table.
    metrics : dict
        Updated in place with ``invalid_numeric.<table>.<column>`` counts.
    informational : dict
        Updated in place with ``indeterminate_null.<table>.<column>`` counts.

    Returns
    -------
    None
        Diagnostics for an absent operand column or table are omitted.
    """
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
    """Count candidate numeric sentinel occurrences per model column.

    Candidates such as -9998 are reported as observations, not necessarily
    as missing-value codes. Counts include finite numeric values in available
    model columns with supported numeric or boolean declarations, regardless
    of whether a column has a rule or a row is applicable.

    Parameters
    ----------
    connection : sqlite3.Connection
        Connection containing the model tables.
    spec : dict
        Model specification containing table and column definitions.
    constraints : dict
        The model's ``attribute_constraints``, including sentinel values.
    columns : dict of str to set of str
        Available column names by table.
    metrics : dict
        Updated in place with ``sentinel.<table>.<column>`` counts.

    Returns
    -------
    None
        Counts are omitted for absent columns or tables and when there are no
        configured sentinel candidates.
    """
    # Sentinel candidates apply to every numeric model column, including
    # columns for which no physical bound has been established.
    candidates = [sentinel["value"] for sentinel in constraints["sentinels"]]
    for table, definition in spec["tables"].items():
        present = [column["name"] for column in definition["columns"]
                   if numeric_declaration(column["type"]) and column["name"] in columns.get(table, set())]
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
    """Evaluate supported attribute rules against available columns.

    Range and interval rules count violations among finite numeric operands.
    For conditional rules, only rows with the specified valid SQLite integer
    boolean flag apply; null and nonboolean flags are counted together as
    indeterminate. Scaled-difference rules delegate to ``length_comparison``.

    Parameters
    ----------
    connection : sqlite3.Connection
        Connection containing the rule tables.
    rules : sequence of dict
        Entries from ``attribute_constraints.rules`` with an ID, kind,
        operands, applicability, and limits. Scaled-difference entries also
        specify join columns, a scale, and a tolerance.
    columns : dict of str to set of str
        Available column names by table.
    metrics : dict
        Updated in place with violation counts and, for scaled differences,
        nonfinite-calculation counts.
    informational : dict
        Updated in place with applicability and comparison diagnostics. A
        missing operand, join, or required flag column produces a
        ``not_evaluated.<id>`` entry instead of a new violation metric.

    Returns
    -------
    int
        Number of rules counted as evaluated. For a scaled difference, the
        presence of its violation key in ``metrics`` determines the count,
        including any key already present before this call.

    Raises
    ------
    ValueError
        If a rule kind or a checked applicability condition is unsupported.
    """
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
            raise ValueError(f"unsupported attribute rule {rule['id']!r}: kind {rule['kind']!r}")
        table, column = rule["table"], rule["column"]
        if column not in columns.get(table, set()):
            informational[f"not_evaluated.{rule['id']}"] = 1
            continue
        condition = rule["applies_when"]
        where = finite(column)
        if condition["kind"] not in {"all_rows", "column_equals"}:
            raise ValueError(f"unsupported applicability in attribute rule {rule['id']!r}")
        if condition["kind"] == "column_equals":
            flag_value = condition["value"]
            if (type(flag_value) is not int or flag_value not in (0, 1)
                    or condition.get("sqlite_boolean_storage_class") != "integer"
                    or condition.get("valid_values") != [0, 1]
                    or condition.get("false_policy") != "not_applicable"
                    or condition.get("null_or_nonboolean_policy") != "report_indeterminate"):
                raise ValueError(f"unsupported boolean condition in attribute rule {rule['id']!r}")
            flag = condition["column"]
            if flag not in columns[table]:
                informational[f"not_evaluated.{rule['id']}"] = 1
                continue
            flag_sql = quote(flag)
            valid = f"typeof({flag_sql}) = 'integer' AND {flag_sql} IN (0, 1)"
            informational[f"indeterminate_applicability.{rule['id']}"] = count(
                connection, table, f"NOT ({valid})"
            )
            where += f" AND {valid} AND {flag_sql} = {flag_value}"
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
    """Record model columns without range or interval rules.

    This inventory uses the specification, not the database schema or actual
    evaluation results. A scaled-difference rule alone does not mark its
    operand columns as bounded.

    Parameters
    ----------
    spec : dict
        Model specification containing table and column definitions.
    rules : sequence of dict
        Entries from ``attribute_constraints.rules`` with IDs, kinds,
        operands, applicability, and limits; scaled differences also carry
        join and tolerance information.
    informational : dict
        Updated in place with ``not_checked.<table>.<column>`` entries set
        to 1 for columns without a range or interval rule.

    Returns
    -------
    None
        Entries are based on the model even when a table or column is absent.
    """
    bounded = {(rule["table"], rule["column"]) for rule in rules
               if rule["kind"] in {"range", "interval"}}
    for table, definition in spec["tables"].items():
        for column in definition["columns"]:
            name = column["name"]
            if (table, name) not in bounded:
                informational[f"not_checked.{table}.{name}"] = 1


def load_attribute_spec(model, kind):
    """Load the selected Data Model specification by identifier.

    Read ``<model>/<kind>.json`` under the model directory and check its
    format and identifying metadata. Selection is not restricted to a fixed
    list of versions: a future specification can be loaded if its identifiers
    and metadata match and its rules and policies use supported semantics.
    The model directory is trusted repository content, not an untrusted
    concurrently modified filesystem.

    Parameters
    ----------
    model : str
        Data Model version identifier, not a path.
    kind : str
        Output kind identifier, not a path.

    Returns
    -------
    dict
        Parsed specification with format version ``1.0`` and matching model
        and output kind metadata.

    Raises
    ------
    ValueError
        If an identifier is invalid, the selected file is absent or is a
        symlink, the model directory is a symlink, metadata is incompatible,
        or the model declares unsupported attribute semantics. Invalid JSON also
        raises a ``ValueError`` subclass.
    """
    if any(not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value)
           for value in (model, kind)):
        raise ValueError(f"invalid attribute Data Model or output kind: {model!r}, {kind!r}")
    directory = MODELS / model
    path = directory / f"{kind}.json"
    if directory.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError(f"no attribute specification for Data Model {model!r}, output kind {kind!r}")
    with path.open(encoding="utf-8") as stream:
        spec = json.load(stream, object_pairs_hook=unique_json_object)
    if (not isinstance(spec, dict) or spec.get("format_version") != "1.0" or spec.get("data_model_version") != model
            or spec.get("output_kind") != kind):
        raise ValueError(f"incompatible attribute specification metadata: {path}")
    try:
        validate_attribute_rules(spec)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"invalid attribute specification {path}: {exc}") from exc
    return spec


def attributes(path, model, kind):
    """Evaluate the selected Data Model's attribute rules read-only.

    Load the selected specification, inspect the SQLite schema, and collect
    numeric operand diagnostics, sentinel candidate counts, rule results, and
    an inventory of model columns without range or interval rules. Missing
    prerequisites omit the affected metrics and mark rules not evaluated;
    if no rules are evaluated, ``no_applicable_checks`` is set to 1.

    Parameters
    ----------
    path : pathlib.Path
        Path to the GeoPackage or other SQLite database to open read-only.
    model : str
        Data Model version identifier used to select the specification.
    kind : str
        Output kind identifier used to select the specification.

    Returns
    -------
    metrics : dict
        Counts of invalid numeric values, sentinel candidates, rule
        violations, and nonfinite calculations, plus ``no_applicable_checks``
        when no rules are evaluated.
    informational : dict
        Counts and markers for nulls, applicability, joins, unevaluated rules,
        and model columns without range or interval rules.

    Raises
    ------
    ValueError
        If specification selection or metadata is invalid, a rule kind is
        unsupported, or a checked applicability condition is unsupported.
    """
    spec = load_attribute_spec(model, kind)
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
