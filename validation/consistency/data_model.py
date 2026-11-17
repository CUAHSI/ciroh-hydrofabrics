"""Select a Data Model specification and validate what the checks may assume.

A Data Model is a directory ``models/<model>/`` holding one JSON specification
per output kind (``<kind>.json``). Adding a directory adds a model; nothing here
or in the checks lists supported versions or kinds.

Each specification describes its structure (``tables``, ``identifiers``), its
attribute rules (``attribute_constraints``) and the conventions the other
checks apply (``checks``). Every check calls the matching ``*_semantics``
function, which rejects an unsupported or inconsistent declaration with a
``ValueError`` instead of applying a v2.2 default. The model directory is
trusted repository content.
"""

import functools
import json
import re
from pathlib import Path

from attributes.specification import (
    finite_number,
    model_columns,
    unique_json_object,
    validate_attribute_rules,
)

MODELS = Path(__file__).resolve().parent / "models"
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
FORMAT_VERSION = "1.0"
ROUTING_STYLES = {"direct", "via_nexus"}
POLYGON_TYPES = {"POLYGON", "MULTIPOLYGON"}


def available_models():
    """List the Data Models that have a specification directory.

    Returns
    -------
    list of str
        Names of model directories (symlinks excluded), sorted.
    """
    if not MODELS.is_dir():
        return []
    return sorted(
        path.name for path in MODELS.iterdir()
        if path.is_dir() and not path.is_symlink() and IDENTIFIER.fullmatch(path.name)
    )


def _model_directory(model):
    """Return the directory of a model, rejecting unsafe or unknown names."""
    available = ", ".join(available_models()) or "none"
    if not isinstance(model, str) or not IDENTIFIER.fullmatch(model):
        raise ValueError(f"invalid Data Model identifier {model!r}; available: {available}")
    directory = MODELS / model
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"no Data Model {model!r}; available: {available}")
    return directory


def output_kinds(model):
    """List the output kinds a Data Model specifies.

    Parameters
    ----------
    model : str
        Data Model identifier, not a path.

    Returns
    -------
    list of str
        Kinds with a ``<kind>.json`` specification, sorted.

    Raises
    ------
    ValueError
        If the model is unsafe, unknown or has no specifications.
    """
    directory = _model_directory(model)
    kinds = sorted(
        path.stem for path in directory.glob("*.json")
        if path.is_file() and not path.is_symlink() and IDENTIFIER.fullmatch(path.stem)
    )
    if not kinds:
        raise ValueError(f"Data Model {model!r} has no output kinds")
    return kinds


def load_spec(model, kind, purpose="consistency check"):
    """Load one Data Model specification and check its identifying metadata.

    Parameters
    ----------
    model, kind : str
        Data Model and output kind identifiers, not paths.
    purpose : str, optional
        Name of the caller's use, included in error messages.

    Returns
    -------
    dict
        Parsed specification whose ``format_version`` is supported and whose
        ``data_model_version`` and ``output_kind`` match the request.

    Raises
    ------
    ValueError
        If an identifier is unsafe, the specification is absent or a symlink,
        the JSON is invalid or has duplicate keys, or the metadata is
        incompatible.
    """
    if any(not isinstance(value, str) or not IDENTIFIER.fullmatch(value) for value in (model, kind)):
        raise ValueError(f"invalid {purpose} Data Model or output kind: {model!r}, {kind!r}")
    directory = _model_directory(model)
    path = directory / f"{kind}.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"no {purpose} specification for Data Model {model!r}, output kind {kind!r}")
    with path.open(encoding="utf-8") as stream:
        spec = json.load(stream, object_pairs_hook=unique_json_object)
    if (not isinstance(spec, dict) or spec.get("format_version") != FORMAT_VERSION
            or spec.get("data_model_version") != model or spec.get("output_kind") != kind):
        raise ValueError(f"incompatible {purpose} specification metadata: {path}")
    return spec


def _semantics(function):
    """Report a malformed specification as ``ValueError`` rather than a lookup error."""
    @functools.wraps(function)
    def call(spec):
        try:
            return function(spec)
        except (KeyError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError(f"invalid {function.__name__.removesuffix('_semantics')} specification: {exc!r}") from exc
    return call


def _section(spec, name):
    """Return a ``checks`` section or explain that the model does not declare it."""
    checks = spec.get("checks")
    if not isinstance(checks, dict):
        raise ValueError("specification has no checks section")
    section = checks.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"specification declares no {name} check semantics")
    return section


def _reject_unknown(section, allowed, label):
    unknown = set(section) - allowed - {"note", "source"}
    if unknown:
        raise ValueError(f"unsupported {label} semantics: {sorted(unknown)}")


def _nonnegative_number(value, label):
    if not finite_number(value) or value < 0:
        raise ValueError(f"{label} must be a finite nonnegative number")


@_semantics
def schema_semantics(spec):
    """Validate and return the schema check's conventions.

    Returns
    -------
    dict
        ``id_prefix_separator``: the text separating an identifier prefix from
        its suffix.
    """
    columns = model_columns(spec)
    for name, definition in spec["tables"].items():
        if not isinstance(definition["gpkg_contents"]["data_type"], str):
            raise ValueError(f"table {name!r} has no registered data type")
        geometry = definition["geometry"]
        if geometry is not None:
            crs = geometry["crs"]
            if (geometry["column"] not in columns[name] or type(geometry["srs_id"]) is not int
                    or not isinstance(geometry["type"], str) or not isinstance(crs["authority"], str)
                    or type(crs["code"]) is not int):
                raise ValueError(f"table {name!r} has an unsupported geometry declaration")
    for identifier in spec["identifiers"]:
        if identifier["column"] not in columns.get(identifier["table"], {}):
            raise ValueError(f"identifier {identifier['table']!r}.{identifier['column']!r} is not a model column")
    section = _section(spec, "schema")
    _reject_unknown(section, {"id_prefix_separator"}, "schema")
    separator = section.get("id_prefix_separator")
    if not isinstance(separator, str) or not separator:
        raise ValueError("schema id_prefix_separator must be a nonempty string")
    return {"id_prefix_separator": separator}


def _scalar_terminal(value):
    return type(value) in (int, str) and value != ""


def _validate_routing(routing, columns):
    """Check the routing declaration against the model's own tables and columns."""
    style = routing.get("style")
    if style not in ROUTING_STYLES:
        raise ValueError(f"unsupported routing style {style!r}; supported: {sorted(ROUTING_STYLES)}")
    if not _scalar_terminal(routing.get("terminal_id")):
        raise ValueError("routing terminal_id must be a nonempty string or an integer")

    def require_routed(layers, key):
        if not isinstance(layers, list) or not layers:
            raise ValueError(f"routing style {style!r} requires {key!r}, a list of layers")
        for layer in layers:
            if not {"id", "toid"} <= set(columns.get(layer, {})):
                raise ValueError(f"routing layer {layer!r} is not a table with id and toid columns")

    # The routing algorithms identify their layers by these names; a model
    # must provide them (documented implementation extension).
    required = {"direct": ("flowpaths", "network"), "via_nexus": ("flowpaths", "nexus", "network")}[style]
    for layer in required:
        if layer not in columns:
            raise ValueError(f"routing style {style!r} requires a {layer!r} table")
    if style == "direct":
        _reject_unknown(routing, {"style", "terminal_id", "layers", "link_label"}, "routing")
        require_routed(routing.get("layers"), "layers")
        if not isinstance(routing.get("link_label"), str) or not routing["link_label"]:
            raise ValueError("routing link_label must be a nonempty string")
        return
    _reject_unknown(routing, {"style", "terminal_id", "target_layers", "outlet_types", "nexus_id_prefixes"}, "routing")
    require_routed(routing.get("target_layers"), "target_layers")
    outlets, prefixes = routing.get("outlet_types"), routing.get("nexus_id_prefixes")
    if (not isinstance(outlets, dict) or not all(isinstance(key, str) and key and isinstance(value, str)
                                                  for key, value in outlets.items())):
        raise ValueError("routing outlet_types must map nonempty ID prefixes to nexus type names")
    if not isinstance(prefixes, list) or not all(isinstance(item, str) and item for item in prefixes):
        raise ValueError("routing nexus_id_prefixes must be a list of nonempty strings")


def _validate_relationship(relationship, columns):
    name = relationship["name"]
    allowed = {"name", "source", "source_key", "target", "target_key", "flag"}
    if set(relationship) - allowed - {"note", "source_note"}:
        raise ValueError(f"unsupported relationship {name!r} semantics: {sorted(set(relationship) - allowed)}")
    if not isinstance(name, str) or not name or "|" in name:
        raise ValueError(f"invalid relationship name: {name!r}")
    for table_field, key_field in (("source", "source_key"), ("target", "target_key")):
        table, key = relationship[table_field], relationship[key_field]
        if key not in columns.get(table, {}):
            raise ValueError(f"relationship {name!r}: unknown {table_field} {table!r}.{key!r}")
    flag = relationship.get("flag")
    if flag is not None and flag not in columns[relationship["source"]]:
        raise ValueError(f"relationship {name!r}: unknown flag column {flag!r}")


@_semantics
def network_semantics(spec):
    """Validate and return the network check's conventions.

    Returns
    -------
    dict
        ``primary_ids``, ``relationships``, ``reciprocal_links`` and
        ``routing`` as declared by the model.
    """
    columns = model_columns(spec)
    section = _section(spec, "network")
    _reject_unknown(section, {"primary_ids", "relationships", "reciprocal_links", "routing"}, "network")
    for table, key in section["primary_ids"].items():
        if table not in columns:
            raise ValueError(f"invalid primary_ids: unknown table {table!r}")
        if key not in columns[table]:
            raise ValueError(f"invalid primary_ids: {table!r} has no column {key!r}")
    seen = set()
    for relationship in section["relationships"]:
        if relationship["name"] in seen:
            raise ValueError(f"duplicate relationship name: {relationship['name']!r}")
        seen.add(relationship["name"])
        _validate_relationship(relationship, columns)
    links = section["reciprocal_links"]
    if links is not None:
        if len(links) != 2 or any(len(link) != 3 for link in links):
            raise ValueError("reciprocal_links must be null or two [table, id column, reference column] entries")
        for table, *fields in links:
            if any(field not in columns.get(table, {}) for field in fields):
                raise ValueError(f"reciprocal link {table!r} has unknown columns {fields!r}")
    _validate_routing(section["routing"], columns)
    return section


@_semantics
def geometry_semantics(spec):
    """Validate and return the geometry check's conventions.

    Returns
    -------
    dict
        ``topology_layer``, the default ``overlap_min_area_m2`` and
        ``gap_min_area_m2``, and ``crs`` (``authority``, ``code``, ``srs_id``)
        taken from the topology layer's registered geometry.
    """
    columns = model_columns(spec)
    section = _section(spec, "geometry")
    _reject_unknown(section, {"topology_layer", "overlap_min_area_m2", "gap_min_area_m2"}, "geometry")
    layer = section["topology_layer"]
    geometry = (spec["tables"].get(layer) or {}).get("geometry")
    if layer not in columns or not geometry or str(geometry["type"]).upper() not in POLYGON_TYPES:
        raise ValueError(f"unsupported topology layer {layer!r}: it must be a registered polygon layer")
    for field in ("overlap_min_area_m2", "gap_min_area_m2"):
        _nonnegative_number(section.get(field), f"geometry {field}")
    crs = geometry["crs"]
    return {
        "topology_layer": layer,
        "overlap_min_area_m2": section["overlap_min_area_m2"],
        "gap_min_area_m2": section["gap_min_area_m2"],
        "crs": {"authority": crs["authority"], "code": crs["code"], "srs_id": geometry["srs_id"]},
    }


def validate_spec(spec):
    """Validate every declaration the consistency checks rely on.

    Parameters
    ----------
    spec : dict
        Specification from :func:`load_spec`.

    Raises
    ------
    ValueError
        If any check's semantics are missing, unsupported or inconsistent.
    """
    if not isinstance(spec.get("checks"), dict):
        raise ValueError("specification has no checks section")
    schema_semantics(spec)
    network_semantics(spec)
    geometry_semantics(spec)
    try:
        validate_attribute_rules(spec)
    except (KeyError, TypeError, IndexError, AttributeError) as exc:
        raise ValueError(f"invalid attribute specification: {exc!r}") from exc


def validate_model(model):
    """Validate every output kind of a Data Model before any input is read.

    Parameters
    ----------
    model : str
        Data Model identifier.

    Returns
    -------
    list of str
        The model's output kinds.

    Raises
    ------
    ValueError
        If the model is unknown or any of its specifications is unsupported;
        the message names the output kind.
    """
    kinds = output_kinds(model)
    for kind in kinds:
        try:
            validate_spec(load_spec(model, kind))
        except ValueError as exc:
            raise ValueError(f"Data Model {model!r}, output kind {kind!r}: {exc}") from exc
    return kinds
