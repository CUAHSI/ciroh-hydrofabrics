"""Validate the attribute-rule semantics supported by this checker."""

import math
import re


def unique_json_object(pairs):
    """Build a JSON object without silently overwriting duplicate keys.

    Parameters
    ----------
    pairs : list of tuple
        Object key/value pairs in their original order.

    Returns
    -------
    dict
        Object containing the unique key/value pairs.

    Raises
    ------
    ValueError
        If a key occurs more than once in an object.
    """
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def numeric_declaration(declaration):
    """Recognize supported SQLite numeric column declarations.

    Parameters
    ----------
    declaration : str
        Type declared for a model column, optionally with precision or scale.

    Returns
    -------
    bool
        Whether the declaration denotes a supported numeric or boolean type.
    """
    return bool(re.fullmatch(
        r"(?:INT|INTEGER|TINYINT|SMALLINT|MEDIUMINT|BIGINT|UNSIGNED BIG INT|INT2|INT8|"
        r"REAL|DOUBLE|DOUBLE PRECISION|FLOAT|NUMERIC|DECIMAL|BOOLEAN|BOOL)(?:\s*\(\d+(?:\s*,\s*\d+)?\))?",
        declaration.strip(), re.IGNORECASE,
    ))


def text_declaration(declaration):
    """Recognize supported SQLite text column declarations.

    Parameters
    ----------
    declaration : str
        Type declared for a model column, optionally with a length.

    Returns
    -------
    bool
        Whether the declaration denotes a supported text type.
    """
    return bool(re.fullmatch(
        r"(?:TEXT|CHAR|CHARACTER|VARCHAR|VARYING CHARACTER|NCHAR|NATIVE CHARACTER|NVARCHAR|CLOB)"
        r"(?:\s*\(\d+\))?", declaration.strip(), re.IGNORECASE,
    ))


def model_columns(spec):
    """Validate model columns and return their declared types by table.

    Parameters
    ----------
    spec : dict
        Data Model specification with a ``tables`` mapping.

    Returns
    -------
    dict of str to dict
        Declared column types, keyed first by table and then by column name.

    Raises
    ------
    ValueError
        If a name, type, or resulting report metric is ambiguous or unsupported.
    """
    tables, metric_names, table_names = {}, set(), set()
    geometries = {"GEOMETRY", "POINT", "LINESTRING", "POLYGON", "MULTIPOINT", "MULTILINESTRING",
                  "MULTIPOLYGON", "GEOMETRYCOLLECTION", "BLOB"}
    for table, definition in spec["tables"].items():
        if (not isinstance(table, str) or not table or "|" in table
                or any(ord(char) < 32 or ord(char) == 127 for char in table)):
            raise ValueError(f"unsupported model table name: {table!r}")
        if table.casefold() in table_names:
            raise ValueError(f"duplicate model table name: {table!r}")
        table_names.add(table.casefold())
        if set(definition) - {"gpkg_contents", "geometry", "columns", "source", "note", "description"}:
            raise ValueError(f"unsupported model table semantics: {table!r}")
        columns, column_names = {}, set()
        for column in definition["columns"]:
            if set(column) - {"name", "type", "source", "note", "description"}:
                raise ValueError(f"unsupported model column semantics: {table!r}.{column.get('name')!r}")
            name, declared = column["name"], column["type"]
            if (not isinstance(name, str) or not name or "|" in name
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)):
                raise ValueError(f"unsupported model column name: {table!r}.{name!r}")
            if name.casefold() in column_names:
                raise ValueError(f"duplicate model column: {table!r}.{name!r}")
            column_names.add(name.casefold())
            if (not isinstance(declared, str) or not
                    (numeric_declaration(declared) or text_declaration(declared) or declared.upper() in geometries)):
                raise ValueError(f"unsupported model column type: {table!r}.{name!r}: {declared!r}")
            metric = f"{table}.{name}"
            if metric in metric_names:
                raise ValueError(f"ambiguous model column metric: {metric!r}")
            metric_names.add(metric)
            columns[name] = declared
        tables[table] = columns
    return tables


def finite_number(value):
    """Check whether a specification value is a finite numeric literal.

    Parameters
    ----------
    value : object
        Candidate numeric value; booleans are not treated as numbers.

    Returns
    -------
    bool
        Whether the value is a finite float or an SQLite-bindable integer.
    """
    if type(value) is int:
        return -(2**63) <= value <= 2**63 - 1
    return type(value) is float and math.isfinite(value)


def validate_attribute_rules(spec):
    """Reject attribute rule semantics the evaluator cannot safely interpret.

    Parameters
    ----------
    spec : dict
        Data Model specification containing ``attribute_constraints.rules``.

    Raises
    ------
    ValueError
        If a rule declares an unsupported kind or applicability condition.
    """
    tables = model_columns(spec)
    constraints = spec["attribute_constraints"]
    known_fields = {"numeric_value_policy", "sentinel_handling", "rules", "sentinels", "unlisted_constraints", "note"}
    if set(constraints) - known_fields or constraints.get("unlisted_constraints") != "undetermined":
        raise ValueError("unsupported attribute constraint semantics")
    numeric_policy = {
        "scope": "numeric operand columns of these rules, independent of row applicability",
        "sqlite_storage_classes": ["integer", "real"], "require_finite": True,
        "invalid_or_nonfinite": "report", "nonfinite_intermediate": "report",
        "null": "undetermined", "null_reporting": "report_indeterminate",
    }
    sentinel_policy = {
        "scope": "all numeric-declared Data Model columns, independent of row applicability",
        "unrecognized_candidate": "report", "field_defined_missing": "apply_null_policy",
        "otherwise_apply_numeric_rules_when_applicable": True,
    }
    for name, supported in (("numeric_value_policy", numeric_policy), ("sentinel_handling", sentinel_policy)):
        actual = constraints[name]
        if (set(actual) - set(supported) - {"note", "source"}
                or any(actual.get(key) != value or type(actual.get(key)) is not type(value)
                       for key, value in supported.items())):
            raise ValueError(f"unsupported attribute {name} policy")
    seen_sentinels = set()
    for sentinel in constraints["sentinels"]:
        value = sentinel["value"]
        if (set(sentinel) - {"value", "source", "note", "meaning", "applicable_fields", "treatment"}
                or not finite_number(value) or value in seen_sentinels or sentinel.get("meaning") != "undetermined"
                or sentinel.get("applicable_fields") != "undetermined"
                or sentinel.get("treatment") != "report_unless_field_defined_missing"):
            raise ValueError(f"unsupported sentinel definition: {sentinel!r}")
        seen_sentinels.add(value)
    seen_rules = set()
    for rule in constraints["rules"]:
        rule_id = rule["id"]
        if not isinstance(rule_id, str) or not rule_id or "|" in rule_id or "\n" in rule_id:
            raise ValueError(f"invalid attribute rule ID: {rule_id!r}")
        if rule_id in seen_rules:
            raise ValueError(f"duplicate attribute rule ID: {rule_id!r}")
        seen_rules.add(rule_id)
        kind = rule["kind"]
        if kind not in {"range", "interval", "scaled_difference"}:
            raise ValueError(f"unsupported attribute rule {rule_id!r}: kind {kind!r}")
        common = {"id", "kind", "source", "note", "applies_when", "null_policy", "sentinel_policy"}
        allowed = {
            "range": {"table", "column", "operator", "value"},
            "interval": {"table", "column", "lower", "lower_inclusive", "upper", "upper_inclusive"},
            "scaled_difference": {"left", "right", "join", "join_cardinality", "duplicate_key_policy",
                                  "duplicate_violation_counting", "max_absolute_difference", "units", "unmatched_policy"},
        }
        if set(rule) - common - allowed[kind]:
            raise ValueError(f"unsupported fields in attribute rule {rule_id!r}: {set(rule) - common - allowed[kind]}")
        if kind in {"range", "interval"}:
            declared = tables.get(rule.get("table"), {}).get(rule.get("column"))
            if declared is None or not numeric_declaration(declared):
                raise ValueError(f"unsupported numeric column in attribute rule {rule_id!r}")
        if kind == "range" and (rule.get("operator") not in {"gt", "ge"} or not finite_number(rule.get("value"))):
            raise ValueError(f"unsupported range in attribute rule {rule_id!r}")
        if kind == "interval" and (
            not finite_number(rule.get("lower")) or not finite_number(rule.get("upper"))
            or rule["lower"] > rule["upper"] or type(rule.get("lower_inclusive")) is not bool
            or type(rule.get("upper_inclusive")) is not bool
        ):
            raise ValueError(f"unsupported interval in attribute rule {rule_id!r}")
        if rule.get("null_policy") != "undetermined" or rule.get("sentinel_policy") != "report_unless_field_defined_missing":
            raise ValueError(f"unsupported attribute rule policy: {rule_id!r}")
        condition = rule["applies_when"]
        applicable = condition["kind"]
        condition_fields = {"kind", "note", "source"}
        if applicable == "column_equals":
            condition_fields |= {"column", "value", "valid_values", "sqlite_boolean_storage_class",
                                 "false_policy", "null_or_nonboolean_policy"}
        if set(condition) - condition_fields:
            raise ValueError(f"unsupported applicability fields in attribute rule {rule_id!r}")
        supported = {"matched_rows"} if kind == "scaled_difference" else {"all_rows", "column_equals"}
        if applicable not in supported:
            raise ValueError(f"unsupported applicability {applicable!r} in attribute rule {rule_id!r}")
        if applicable == "column_equals":
            if condition.get("column") not in tables.get(rule["table"], {}):
                raise ValueError(f"unsupported condition column in attribute rule {rule_id!r}")
            value = condition.get("value")
            if (type(value) is not int or value not in (0, 1)
                    or condition.get("valid_values") != [0, 1]
                    or condition.get("sqlite_boolean_storage_class") != "integer"
                    or condition.get("false_policy") != "not_applicable"
                    or condition.get("null_or_nonboolean_policy") != "report_indeterminate"):
                raise ValueError(f"unsupported boolean condition in attribute rule {rule_id!r}")
        if kind == "scaled_difference":
            if (set(rule["left"]) - {"table", "column", "note", "source"}
                    or set(rule["right"]) - {"table", "column", "scale", "note", "source"}):
                raise ValueError(f"unsupported operand in attribute rule {rule_id!r}")
            if (not finite_number(rule["right"].get("scale")) or rule["right"]["scale"] <= 0
                    or not finite_number(rule.get("max_absolute_difference"))
                    or rule["max_absolute_difference"] < 0):
                raise ValueError(f"unsupported scaled difference in attribute rule {rule_id!r}")
            if len(rule["join"]) != 1 or set(rule["join"][0]) - {"left", "right", "note", "source"}:
                raise ValueError(f"unsupported join in attribute rule {rule_id!r}: exactly one key is required")
            if (rule.get("join_cardinality") != "undetermined"
                    or rule.get("duplicate_key_policy") != "report_indeterminate"
                    or rule.get("duplicate_violation_counting") != "undetermined"
                    or rule.get("unmatched_policy") != "undetermined"):
                raise ValueError(f"unsupported join policy in attribute rule {rule_id!r}")
            for side in ("left", "right"):
                types = tables.get(rule[side].get("table"), {})
                operand_type = types.get(rule[side].get("column"))
                if operand_type is None or not numeric_declaration(operand_type):
                    raise ValueError(f"unsupported {side} operand in attribute rule {rule_id!r}")
                key = rule["join"][0][side]
                key_type = types.get(key)
                if key_type is None or not text_declaration(key_type):
                    raise ValueError(f"unsupported join key {key!r} in attribute rule {rule_id!r}: expected text")
