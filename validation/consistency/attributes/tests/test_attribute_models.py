"""Data Model selection at the attribute-check interface."""

import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "attribute_checks.py"
REFERENCE_SPEC = MODULE_PATH.parents[1] / "models" / "v2.2" / "reference.json"


@pytest.fixture
def checker(monkeypatch, tmp_path):
    """Load the attribute checker with an isolated Data Model directory.

    Parameters
    ----------
    monkeypatch : pytest.MonkeyPatch
        Fixture used to point the checker at the test's model files.
    tmp_path : pathlib.Path
        Temporary directory for the isolated model directory.

    Returns
    -------
    module
        Attribute checker with its model-file location set to ``tmp_path``.
    """
    monkeypatch.syspath_prepend(str(MODULE_PATH.parents[1]))
    module_spec = importlib.util.spec_from_file_location("attribute_checks_test", MODULE_PATH)
    assert module_spec is not None and module_spec.loader is not None
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    monkeypatch.setattr(module, "MODELS", tmp_path)
    return module


def write_reference_spec(root, model="v9.9", kind="reference"):
    """Load a Reference specification for a selected test model name.

    Parameters
    ----------
    root : pathlib.Path
        Directory containing the test model subdirectory.
    model, kind : str, optional
        Model identifier and output kind to record in the copied specification;
        default to ``v9.9`` and ``reference``, respectively.

    Returns
    -------
    dict
        Mutable specification to customize before saving it in the test.
    """
    spec = json.loads(REFERENCE_SPEC.read_text())
    spec["data_model_version"] = model
    spec["output_kind"] = kind
    (root / model).mkdir(exist_ok=True)
    return spec


@pytest.mark.parametrize("model,kind", [
    ("../outside", "reference"), ("/absolute", "reference"), ("v9.9/..", "reference"),
    ("", "reference"), ("v9.9", "../reference"), ("v9.9", "ref\x00erence"),
])
def test_model_identifiers_cannot_address_arbitrary_paths(checker, tmp_path, model, kind):
    """Reject path traversal, absolute paths, and invalid identifier text.

    Each invalid model or output-kind identifier raises ``ValueError`` before
    the Build is opened.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the unused GeoPackage path.
    model, kind : str
        Parametrized model and output-kind identifiers, one of which is invalid.
    """
    with pytest.raises(ValueError, match="invalid attribute Data Model"):
        checker.attributes(tmp_path / "unused.gpkg", model, kind)


def test_model_metadata_must_match_requested_version(checker, tmp_path):
    """A model file cannot claim to describe a different Data Model version.

    A mismatched ``data_model_version`` raises ``ValueError`` before opening
    the Build.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and unused GeoPackage path.
    """
    spec = write_reference_spec(tmp_path)
    spec["data_model_version"] = "v2.2"
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))

    with pytest.raises(ValueError, match="metadata"):
        checker.attributes(tmp_path / "unused.gpkg", "v9.9", "reference")


def test_model_file_symlinks_are_not_followed(checker, tmp_path):
    """A selected model file cannot be a symbolic link to another location.

    A model file linked to an outside target raises ``ValueError`` rather
    than being followed.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model, link target, and unused GeoPackage path.
    """
    spec = write_reference_spec(tmp_path)
    target = tmp_path / "outside.json"
    target.write_text(json.dumps(spec))
    (tmp_path / "v9.9" / "reference.json").symlink_to(target)

    with pytest.raises(ValueError, match="no attribute specification"):
        checker.attributes(tmp_path / "unused.gpkg", "v9.9", "reference")


def test_compatible_future_model_uses_its_own_attribute_rules(checker, tmp_path):
    """A compatible model evaluates its own bound, not the v2.2 bound.

    A length of 2 km violates the test model's greater-than-5 rule; 6 km
    satisfies it. The attribute interface returns exactly one violation.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["attribute_constraints"]["rules"][1]["value"] = 5
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE flowpaths (lengthkm REAL)")
        connection.executemany("INSERT INTO flowpaths VALUES (?)", [(2,), (6,)])

    metrics, _ = checker.attributes(path, "v9.9", "reference")

    assert metrics["violations.flowpaths.lengthkm_positive"] == 1


def test_unsupported_rule_kind_is_rejected_even_alongside_valid_rules(checker, tmp_path):
    """An unknown rule kind raises an error instead of producing partial results.

    A valid rule precedes the unsupported rule, but the checker raises
    ``ValueError`` instead of reporting a successful partial evaluation.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["attribute_constraints"]["rules"].append({"id": "future", "kind": "unsupported"})
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE flowpaths (lengthkm REAL)")

    with pytest.raises(ValueError, match="unsupported.*future"):
        checker.attributes(path, "v9.9", "reference")


def test_model_controls_conditional_applicability(checker, tmp_path):
    """The condition value in the selected model controls which rows apply.

    Only the zero flag satisfies the test model's condition, so exactly one
    nonpositive area is reported and the row with flag one is excluded. After
    the applicable area is changed to a positive value, no violations remain.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["attribute_constraints"]["rules"][2]["applies_when"]["value"] = 0
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE flowpaths (areasqkm REAL, has_divide INTEGER)")
        connection.executemany("INSERT INTO flowpaths VALUES (?, ?)", [(0, 0), (0, 1)])

    metrics, _ = checker.attributes(path, "v9.9", "reference")

    assert metrics["violations.flowpaths.areasqkm_positive_with_divide"] == 1
    # Distinguish the applicable row by changing its operand only.
    with sqlite3.connect(path) as connection:
        connection.execute("UPDATE flowpaths SET areasqkm = 2 WHERE has_divide = 0")
    metrics, _ = checker.attributes(path, "v9.9", "reference")
    assert metrics["violations.flowpaths.areasqkm_positive_with_divide"] == 0


def test_unsupported_applicability_is_rejected_when_input_is_missing(checker, tmp_path):
    """An unsupported condition is an error even if its input table is absent.

    A Build lacking the rule's input table still produces ``ValueError``,
    rather than silently reporting the incompatible rule as unevaluated.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["attribute_constraints"]["rules"][2]["applies_when"]["kind"] = "future_condition"
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value REAL)")

    with pytest.raises(ValueError, match="unsupported.*applicability"):
        checker.attributes(path, "v9.9", "reference")


def test_unsupported_composite_join_is_rejected(checker, tmp_path):
    """A composite join cannot be silently reduced to its first key.

    Even with a Build that lacks the relevant tables, the checker raises
    ``ValueError`` rather than using only the first join column.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rule = next(rule for rule in spec["attribute_constraints"]["rules"] if rule["kind"] == "scaled_difference")
    rule["join"].append({"left": "toid", "right": "toid"})
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value REAL)")

    with pytest.raises(ValueError, match="unsupported.*join"):
        checker.attributes(path, "v9.9", "ngen")


def test_unsupported_numeric_policy_is_rejected(checker, tmp_path):
    """The checker refuses a model whose NULL policy requires different behavior.

    A model-wide NULL policy requiring violations raises ``ValueError`` even
    when the Build lacks the input table.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["attribute_constraints"]["numeric_value_policy"]["null"] = "violation"
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value REAL)")

    with pytest.raises(ValueError, match="unsupported.*policy"):
        checker.attributes(path, "v9.9", "reference")


def test_field_specific_missing_code_requires_supported_handling(checker, tmp_path):
    """A defined missing code is not incorrectly reported as a sentinel violation.

    A model defining ``-9998`` as missing for a field raises ``ValueError``
    rather than evaluating the code with unsupported semantics.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["attribute_constraints"]["sentinels"][0]["meaning"] = "missing"
    spec["attribute_constraints"]["sentinels"][0]["applicable_fields"] = ["flowpaths.lengthkm"]
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE flowpaths (lengthkm REAL)")
        connection.execute("INSERT INTO flowpaths VALUES (-9998)")

    with pytest.raises(ValueError, match="unsupported.*sentinel"):
        checker.attributes(path, "v9.9", "reference")


@pytest.mark.parametrize("incompatibility", [
    "numeric_join", "duplicate_id", "join_policy", "flag_values", "rule_null_policy",
    "range_operator", "interval_bounds", "unknown_rule_policy", "left_scale",
    "condition_extension", "policy_extension", "range_column", "flag_column", "unknown_column_type",
    "integer_overflow", "sentinel_overflow", "column_missing_policy",
])
def test_incompatible_rule_semantics_are_rejected_before_reading_input(checker, tmp_path, incompatibility):
    """Incompatible future rule semantics cannot produce partial success.

    Each parametrized incompatible change, including numeric join identifiers,
    duplicate IDs, changed policies, and unsupported bounds or columns, raises
    ``ValueError`` before checking the deliberately absent input tables.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    incompatibility : str
        Unsupported change applied to a copied NextGen specification.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rules = spec["attribute_constraints"]["rules"]
    length_rule = next(rule for rule in rules if rule["kind"] == "scaled_difference")
    if incompatibility == "numeric_join":
        table = spec["tables"][length_rule["left"]["table"]]
        key = length_rule["join"][0]["left"]
        next(column for column in table["columns"] if column["name"] == key)["type"] = "REAL"
    elif incompatibility == "duplicate_id":
        rules[0]["id"] = rules[1]["id"]
    elif incompatibility == "join_policy":
        length_rule["join_cardinality"] = "many_to_one"
    elif incompatibility == "flag_values":
        next(rule for rule in rules if rule["applies_when"]["kind"] == "column_equals")["applies_when"]["valid_values"] = [0, 1, 2]
    elif incompatibility == "range_operator":
        next(rule for rule in rules if rule["kind"] == "range")["operator"] = "le"
    elif incompatibility == "interval_bounds":
        rules[0]["lower"] = 2
    elif incompatibility == "unknown_rule_policy":
        rules[0]["future_missing_code_policy"] = "ignore"
    elif incompatibility == "left_scale":
        length_rule["left"]["scale"] = 2
    elif incompatibility == "condition_extension":
        rules[0]["applies_when"]["unknown_policy"] = "ignore"
    elif incompatibility == "policy_extension":
        spec["attribute_constraints"]["numeric_value_policy"]["coerce_text"] = True
    elif incompatibility == "range_column":
        next(rule for rule in rules if rule["kind"] == "range")["column"] = "unknown"
    elif incompatibility == "flag_column":
        next(rule for rule in rules if rule["applies_when"]["kind"] == "column_equals")["applies_when"]["column"] = "unknown"
    elif incompatibility == "unknown_column_type":
        spec["tables"]["flowpaths"]["columns"][0]["type"] = "CUSTOM_TYPE"
    elif incompatibility == "integer_overflow":
        next(rule for rule in rules if rule["kind"] == "range")["value"] = 2**63
    elif incompatibility == "sentinel_overflow":
        spec["attribute_constraints"]["sentinels"][0]["value"] = 2**63
    elif incompatibility == "column_missing_policy":
        spec["tables"]["flowpaths"]["columns"][0]["missing_value"] = -9998
    else:
        rules[0]["null_policy"] = "valid"
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value REAL)")

    with pytest.raises(ValueError, match="unsupported|duplicate"):
        checker.attributes(path, "v9.9", "ngen")


def test_duplicate_json_keys_are_rejected(checker, tmp_path):
    """Duplicate keys cannot silently override Data Model specification fields.

    Repeating the format-version key raises ``ValueError`` even when its values
    agree, rather than allowing ambiguous definitions.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    payload = json.dumps(spec).replace('"format_version": "1.0"', '"format_version": "1.0", "format_version": "1.0"')
    (tmp_path / "v9.9" / "reference.json").write_text(payload)
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE unrelated (value REAL)")

    with pytest.raises(ValueError, match="duplicate.*format_version"):
        checker.attributes(path, "v9.9", "reference")


def test_colliding_report_metric_names_are_rejected(checker, tmp_path):
    """Different model columns cannot overwrite one another's report metrics.

    ``a.b``/``c`` and ``a``/``b.c`` would both produce the metric suffix
    ``a.b.c``. The checker raises ``ValueError`` rather than hiding a count.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    template = spec["tables"]["network"]
    spec["tables"]["a.b"] = {**template, "columns": [{"name": "c", "type": "REAL"}]}
    spec["tables"]["a"] = {**template, "columns": [{"name": "b.c", "type": "REAL"}]}
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "a.b" (c REAL)')
        connection.execute('CREATE TABLE a ("b.c" REAL)')

    with pytest.raises(ValueError, match="duplicate.*metric|ambiguous.*metric"):
        checker.attributes(path, "v9.9", "reference")


def test_future_numeric_declarations_are_included_in_sentinel_scans(checker, tmp_path):
    """A DOUBLE model column is scanned for configured numeric sentinel candidates.

    The unbounded test column contains one ``-9998`` candidate, which must be
    counted even though its declared type is not used in the v2.2 specs.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = write_reference_spec(tmp_path)
    spec["tables"]["flowpaths"]["columns"].append({"name": "new_measure", "type": "DOUBLE"})
    (tmp_path / "v9.9" / "reference.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE flowpaths (new_measure DOUBLE)")
        connection.execute("INSERT INTO flowpaths VALUES (-9998)")

    metrics, _ = checker.attributes(path, "v9.9", "reference")

    assert metrics["sentinel.flowpaths.new_measure"] == 1


@pytest.mark.parametrize("scale,precision,compared,violations", [(1, 0, 1, 1), (1.0, 1, 0, 0)])
def test_large_integer_comparison_reports_precision_as_indeterminate(checker, tmp_path, scale, precision, compared, violations):
    """Large integers are compared exactly or flagged as precision-indeterminate.

    At zero tolerance, adjacent integers at and above 2**53 yield one violation when
    integer arithmetic is exact. A floating-point scale makes that pair
    indeterminate, with no compared pair or violation, rather than allowing a
    rounded, misleading pass.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    scale : int or float
        Representation of unit scale.
    precision, compared, violations : int
        Expected counts for precision-indeterminate and compared pairs, and violations.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rule = next(rule for rule in spec["attribute_constraints"]["rules"] if rule["kind"] == "scaled_difference")
    rule["right"]["scale"] = scale
    rule["max_absolute_difference"] = 0
    spec["attribute_constraints"]["rules"] = [rule]
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m INTEGER)')
        connection.execute('CREATE TABLE flowpaths (id TEXT, lengthkm INTEGER)')
        connection.execute('INSERT INTO "flowpath-attributes" VALUES (?, ?)', ("one", 9007199254740993))
        connection.execute('INSERT INTO flowpaths VALUES (?, ?)', ("one", 9007199254740992))

    metrics, info = checker.attributes(path, "v9.9", "ngen")

    assert info[f"indeterminate_precision.{rule['id']}"] == precision
    assert info[f"compared_pairs.{rule['id']}"] == compared
    assert metrics[f"violations.{rule['id']}"] == violations


def test_zero_tolerance_does_not_hide_a_representable_difference(checker, tmp_path):
    """A zero-tolerance rule reports even a one-ULP difference.

    The rule compares ``1.0000000000000002`` against ``1`` at unit scale;
    their nonzero difference must produce one violation.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rule = next(rule for rule in spec["attribute_constraints"]["rules"] if rule["kind"] == "scaled_difference")
    rule["right"]["scale"] = 1
    rule["max_absolute_difference"] = 0
    spec["attribute_constraints"]["rules"] = [rule]
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m REAL)')
        connection.execute('CREATE TABLE flowpaths (id TEXT, lengthkm REAL)')
        connection.execute('INSERT INTO "flowpath-attributes" VALUES (?, ?)', ("one", 1.0000000000000002))
        connection.execute('INSERT INTO flowpaths VALUES (?, ?)', ("one", 1))

    metrics, _ = checker.attributes(path, "v9.9", "ngen")

    assert metrics[f"violations.{rule['id']}"] == 1


@pytest.mark.parametrize("left,right,scale,tolerance,violations,precision,compared,nonfinite", [
    (1.0000000000000016e17, 100000000000000.16, 1000, 1, 1, 0, 1, 0),
    (1.0000000000000016e17, 100000000000000.16, 1000, 3.75, 0, 0, 1, 0),
    (1.0000000000000016e17, 100000000000000.16, 1000, 3.7499999995, 0, 0, 1, 0),
    (1.0000000000000016e17, 100000000000000.16, 1000, 3.749999998, 1, 0, 1, 0),
    (-1.0000000000000016e17, -100000000000000.16, 1000, 1, 1, 0, 1, 0),
    (9007199254740993, 0, 1, 9007199254740992, 1, 0, 1, 0),
    (9007199254740993, 0, 1, 9007199254740992.0, 1, 0, 1, 0),
    (-9223372036854775808, 0, 1, 9223372036854775807, 1, 0, 1, 0),
    (2006.0, 2.007, 1000, 1, 0, 0, 1, 0),
    (2005.999, 2.007, 1000, 1, 1, 0, 1, 0),
    (10000000000000002.0, 1e13, 1000, 1, 1, 0, 1, 0),
    (1.0000000000000002, 1.0, 1, 0, 1, 0, 1, 0),
    (5e-324, 0.0, 1, 0, 1, 0, 1, 0),
    (0.0, 5e-324, 0.5, 0, 1, 0, 1, 0),
    (0.0, 5e-324, 0.5, 5e-324, 0, 0, 1, 0),
    (1.7976931348623157e308, -1, 1, 1.7976931348623157e308, 1, 0, 1, 0),
    (1.0, 1e308, 1000, 1, 0, 0, 0, 1),
    (-1e308, 1e308, 1, 1, 0, 0, 0, 1),
    (9223372036854775807, -9223372036854775807, 1, 1, 0, 1, 0, 0),
])
def test_scaled_difference_preserves_precision_at_numeric_extremes(
        checker, tmp_path, left, right, scale, tolerance, violations, precision, compared, nonfinite):
    """Classify exact differences, roundoff boundaries, and overflow correctly.

    The fractional large product differs by 3.75 m even though its rounded
    binary64 product equals the left operand. It violates at 1 m tolerance,
    passes at 3.75 m or within the allowance, and violates beyond it. Integer
    differences also retain their low bits, including SQLite's minimum integer.
    A one-ULP difference
    with zero tolerance violates; the documented boundary allowance applies to
    2006 m versus 2.007 km. Subnormal underflow is resolved exactly. An
    overflowing floating-point calculation is nonfinite, while an overflowing
    integer calculation involving large operands is precision-indeterminate.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    left, right : int or float
        Stored operands, with SQLite storage class preserved.
    scale, tolerance : int or float
        Rule's right-side scale and inclusive absolute tolerance.
    violations, precision, compared, nonfinite : int
        Expected counts for violations, precision-indeterminate pairs,
        compared pairs, and nonfinite calculations, respectively.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rule = next(rule for rule in spec["attribute_constraints"]["rules"] if rule["kind"] == "scaled_difference")
    rule["right"]["scale"] = scale
    rule["max_absolute_difference"] = tolerance
    spec["attribute_constraints"]["rules"] = [rule]
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m)')
        connection.execute('CREATE TABLE flowpaths (id TEXT, lengthkm)')
        connection.execute('INSERT INTO "flowpath-attributes" VALUES (?, ?)', ("one", left))
        connection.execute('INSERT INTO flowpaths VALUES (?, ?)', ("one", right))

    metrics, info = checker.attributes(path, "v9.9", "ngen")

    assert metrics[f"violations.{rule['id']}"] == violations
    assert metrics[f"nonfinite_calculation.{rule['id']}"] == nonfinite
    assert info[f"indeterminate_precision.{rule['id']}"] == precision
    assert info[f"compared_pairs.{rule['id']}"] == compared


def test_scaled_difference_aggregates_clear_and_ambiguous_pairs(checker, tmp_path):
    """Count mixed definite, borderline, nonfinite, and invalid pairs together.

    Among eight unique pairs, four violate, two pass, one overflows, and one
    has a null operand. Six are compared, with no precision-indeterminate pairs.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rule = next(rule for rule in spec["attribute_constraints"]["rules"] if rule["kind"] == "scaled_difference")
    spec["attribute_constraints"]["rules"] = [rule]
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    pairs = [
        (1.0000000000000016e17, 100000000000000.16),
        (10000000000000002.0, 1e13),
        (1001.1, 1.0),
        (2005.999, 2.007),
        (1000.0, 1.0),
        (2006.0, 2.007),
        (1.0, 1e308),
        (None, 1.0),
    ]
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE "flowpath-attributes" (id TEXT, Length_m)')
        connection.execute('CREATE TABLE flowpaths (id TEXT, lengthkm)')
        connection.executemany('INSERT INTO "flowpath-attributes" VALUES (?, ?)',
                               [(str(i), left) for i, (left, _) in enumerate(pairs)])
        connection.executemany('INSERT INTO flowpaths VALUES (?, ?)',
                               [(str(i), right) for i, (_, right) in enumerate(pairs)])

    metrics, info = checker.attributes(path, "v9.9", "ngen")

    assert metrics[f"violations.{rule['id']}"] == 4
    assert metrics[f"nonfinite_calculation.{rule['id']}"] == 1
    assert info[f"compared_pairs.{rule['id']}"] == 6
    assert info[f"indeterminate_precision.{rule['id']}"] == 0
    assert info[f"indeterminate_operands.{rule['id']}"] == 1


def test_future_model_may_use_tables_named_like_join_ctes(checker, tmp_path):
    """Model table names ``l`` and ``r`` do not shadow the join's SQL CTEs.

    Two matching text IDs have a 2 m discrepancy, which must be reported as one
    violation instead of causing SQLite to report a circular reference.

    Parameters
    ----------
    checker : module
        Attribute checker with an isolated model directory.
    tmp_path : pathlib.Path
        Temporary directory for the model and GeoPackage.
    """
    spec = json.loads(REFERENCE_SPEC.with_name("ngen.json").read_text())
    spec["data_model_version"] = "v9.9"
    rule = next(rule for rule in spec["attribute_constraints"]["rules"] if rule["kind"] == "scaled_difference")
    spec["tables"] = {"l": spec["tables"][rule["left"]["table"]], "r": spec["tables"][rule["right"]["table"]]}
    rule["left"]["table"], rule["right"]["table"] = "l", "r"
    spec["attribute_constraints"]["rules"] = [rule]
    (tmp_path / "v9.9").mkdir()
    (tmp_path / "v9.9" / "ngen.json").write_text(json.dumps(spec))
    path = tmp_path / "build.gpkg"
    with sqlite3.connect(path) as connection:
        connection.execute('CREATE TABLE l (id TEXT, Length_m REAL)')
        connection.execute('CREATE TABLE r (id TEXT, lengthkm REAL)')
        connection.execute('INSERT INTO l VALUES (?, ?)', ("one", 1002))
        connection.execute('INSERT INTO r VALUES (?, ?)', ("one", 1))

    metrics, _ = checker.attributes(path, "v9.9", "ngen")

    assert metrics[f"violations.{rule['id']}"] == 1
