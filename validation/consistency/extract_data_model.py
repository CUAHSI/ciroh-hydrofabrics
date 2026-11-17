"""Regenerate a Data Model specification's observed sections from GeoPackages.

A Data Model specification mixes two kinds of content. The *observed* sections
(``sources``, ``tables``, ``identifiers`` observations and
``terminal_observations``) describe what official products contain and can be
rebuilt from them. Everything else (``checks``, ``attribute_constraints``, the
metadata and the wording of the ``*_basis`` fields) was reviewed by a person and
is carried over unchanged.

The command reads GeoPackages read-only, uses no network access, and starts from
the checked-in ``models/<model>/<kind>.json``. It writes a *candidate* for
review; it replaces the checked-in file only when asked with ``--update``.
"""

import argparse
import copy
import hashlib
import json
import re
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import data_model
from attributes.specification import text_declaration

REPO_ROOT = Path(__file__).resolve().parents[2]
CANDIDATES = REPO_ROOT / ".scratch" / "data-model-candidates"


class ExtractionError(Exception):
    """A problem with the request or its inputs; reported without a traceback."""


def parse_arguments(argv):
    parser = argparse.ArgumentParser(
        description="Regenerate a Data Model specification's observed sections from official GeoPackages "
                    "and write a candidate for review.")
    parser.add_argument("geopackages", nargs="+", type=Path, metavar="GEOPACKAGE",
                        help="GeoPackages named <kind>-hydrofabric-vpu-<VPU>.gpkg, one per VPU")
    parser.add_argument("--data-model", required=True, help="Data Model identifier, such as v2.2")
    parser.add_argument("--type", required=True, dest="kind", help="output kind, such as ngen or reference")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--output", type=Path,
                       help="where to write the candidate (default: .scratch/data-model-candidates/<model>/<kind>.json)")
    where.add_argument("--update", action="store_true",
                       help="replace the checked-in specification instead of writing a candidate")
    parser.add_argument("--resource-url", help="URL of the resource the GeoPackages came from, recorded as given")
    parser.add_argument("--file-url", action="append", default=[], metavar="VPU=URL",
                        help="URL of one VPU's GeoPackage, recorded as given; repeatable")
    return parser.parse_args(argv)


def vpu_of(path, kind):
    """Read the VPU from a GeoPackage name, following the ``consistency-check`` convention."""
    match = re.fullmatch(rf"{re.escape(kind)}-hydrofabric-vpu-([A-Za-z0-9]+)\.gpkg", path.name)
    if not match:
        raise ExtractionError(f"{path.name}: expected a name like {kind}-hydrofabric-vpu-<VPU>.gpkg")
    return match.group(1)


def sha256_of(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def recorded_path(path):
    """A path inside the repository is recorded relative to it, so specs do not carry user directories."""
    resolved = path.resolve()
    if resolved.is_relative_to(REPO_ROOT):
        return str(resolved.relative_to(REPO_ROOT))
    return str(path)


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def read_structure(connection):
    """Describe every registered table: its registration, geometry and physical columns."""
    geometry = {
        row[0]: row[1:] for row in connection.execute(
            "SELECT g.table_name, g.column_name, g.geometry_type_name, g.srs_id, g.z, g.m, "
            "s.srs_name, s.organization, s.organization_coordsys_id "
            "FROM gpkg_geometry_columns g LEFT JOIN gpkg_spatial_ref_sys s ON s.srs_id = g.srs_id")
    }
    tables = {}
    for name, data_type, srs_id in connection.execute(
            "SELECT table_name, data_type, srs_id FROM gpkg_contents ORDER BY table_name"):
        registered = geometry.get(name)
        tables[name] = {
            "gpkg_contents": {"data_type": data_type, "srs_id": srs_id},
            "geometry": registered and {
                "column": registered[0], "type": registered[1], "srs_id": registered[2],
                "crs": {"name": registered[5], "authority": registered[6], "code": registered[7]},
                "z": registered[3], "m": registered[4],
            },
            "columns": [{"name": row[1], "type": row[2]}
                        for row in connection.execute(f"PRAGMA table_info({quote(name)})")],
        }
    return tables


def observe_numeric_identifier(connection, table, column):
    """Count a whole column by SQLite storage class, and the numbers that have a fractional part."""
    table_sql, column_sql = quote(table), quote(column)
    classes = dict(connection.execute(
        f"SELECT typeof({column_sql}), COUNT(*) FROM {table_sql} GROUP BY 1 ORDER BY 1"))
    fractional = connection.execute(
        f"SELECT COUNT(*) FROM {table_sql} WHERE typeof({column_sql}) IN ('integer', 'real') "
        f"AND {column_sql} != CAST({column_sql} AS INTEGER)").fetchone()[0]
    return {"storage_class_counts": classes, "fractional_numeric_count": fractional}


def observe_text_identifier(connection, table, column, separator):
    """Count a whole column by ID prefix: the text before the first separator, if it follows a character."""
    table_sql, column_sql = quote(table), quote(column)
    row_count, null_count = connection.execute(
        f"SELECT COUNT(*), COUNT(*) - COUNT({column_sql}) FROM {table_sql}").fetchone()
    prefixes = dict(connection.execute(
        f"SELECT substr({column_sql}, 1, instr({column_sql}, ?) - 1), COUNT(*) FROM {table_sql} "
        f"WHERE instr({column_sql}, ?) > 1 GROUP BY 1 ORDER BY 1", (separator, separator)))
    return {"row_count": row_count, "null_count": null_count,
            "unprefixed_count": row_count - null_count - sum(prefixes.values()), "prefix_counts": prefixes}


def observe_identifiers(connection, wanted, structure, separator):
    """Observe the reviewed identifier columns that this GeoPackage has.

    A text column is observed by prefix and any other column by storage class.
    """
    observations = {}
    for table, column in wanted:
        declared = {item["name"]: item["type"] for item in structure.get(table, {}).get("columns", [])}
        if column not in declared:
            continue
        if text_declaration(declared[column]):
            observations[(table, column)] = observe_text_identifier(connection, table, column, separator)
        else:
            observations[(table, column)] = observe_numeric_identifier(connection, table, column)
    return observations


def has_columns(structure, table, *columns):
    declared = {item["name"] for item in structure.get(table, {}).get("columns", [])}
    return set(columns) <= declared


def observe_direct_terminals(connection, structure, routing, vpu):
    """Count terminal, null and dangling ``toid`` values in each layer that routes to itself.

    The counts are named for the zero terminal of the Reference products, so another terminal is refused
    rather than recorded under a misleading name.
    """
    if type(routing["terminal_id"]) is not int or routing["terminal_id"] != 0:
        raise ExtractionError("terminal observations for direct routing are defined only for terminal_id 0")
    entries = []
    for layer in routing["layers"]:
        if not has_columns(structure, layer, "id", "toid"):
            continue
        table_sql = quote(layer)
        row_count, zero, null = connection.execute(
            f"SELECT COUNT(*), COALESCE(SUM(toid = 0), 0), COALESCE(SUM(toid IS NULL), 0) FROM {table_sql}").fetchone()
        # NOT IN over a subquery lets SQLite build one lookup; a per-row probe would scan the table each time.
        dangling = connection.execute(
            f"SELECT COUNT(*) FROM {table_sql} WHERE toid IS NOT NULL AND toid != 0 "
            f"AND toid NOT IN (SELECT id FROM {table_sql} WHERE id IS NOT NULL)").fetchone()[0]
        entry = {"table": layer, "vpu": vpu, "row_count": row_count, "toid_zero_count": zero,
                 "toid_null_count": null, "nonzero_toid_not_in_same_table_id_count": dangling}
        if layer == "flowpaths" and has_columns(structure, layer, "dnhydroseq"):
            entry["dnhydroseq_zero_count"], entry["both_toid_and_dnhydroseq_zero_count"] = connection.execute(
                f"SELECT COALESCE(SUM(dnhydroseq = 0), 0), COALESCE(SUM(dnhydroseq = 0 AND toid = 0), 0) "
                f"FROM {table_sql}").fetchone()
        entries.append(entry)
    return entries


def observe_nexus_terminals(connection, structure, routing, separator, vpu):
    """Group rows whose ``toid`` is the terminal by the prefix of their ``id`` and their ``type``."""
    entries = []
    for layer in ("nexus", "network"):
        if not has_columns(structure, layer, "id", "toid", "type"):
            continue
        rows = connection.execute(
            f"SELECT CASE WHEN instr(id, :sep) > 1 THEN substr(id, 1, instr(id, :sep) - 1) END AS prefix, "
            f"type, COUNT(*) FROM {quote(layer)} WHERE toid = :terminal "
            f"GROUP BY prefix, type ORDER BY prefix, type",
            {"sep": separator, "terminal": routing["terminal_id"]}).fetchall()
        groups = [{"id_prefix": prefix, "type": kind, "toid": routing["terminal_id"], "count": count}
                  for prefix, kind, count in rows]
        entries.append({"table": layer, "vpu": vpu, "groups": groups})
    return entries


def observe_terminals(connection, structure, routing, separator, vpu):
    """Record how the routing convention's terminal marker occurs in this GeoPackage."""
    if routing["style"] == "direct":
        return observe_direct_terminals(connection, structure, routing, vpu)
    return observe_nexus_terminals(connection, structure, routing, separator, vpu)


def observe(path, vpu, base, urls):
    """Read one GeoPackage, read-only, into its source record, structure and observations."""
    wanted = [(entry["table"], entry["column"]) for entry in base["identifiers"]]
    separator = base["checks"]["schema"]["id_prefix_separator"]
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        try:
            structure = read_structure(connection)
            identifiers = observe_identifiers(connection, wanted, structure, separator)
            terminals = observe_terminals(
                connection, structure, base["checks"]["network"]["routing"], separator, vpu)
        except sqlite3.DatabaseError as exc:
            raise ExtractionError(f"{path}: not a readable GeoPackage ({exc})") from exc
    source = {"vpu": vpu, "filename": path.name, **urls, "local_path": recorded_path(path), "sha256": sha256_of(path)}
    return {"source": source, "structure": structure, "identifiers": identifiers, "terminals": terminals}


def build_identifiers(base_identifiers, by_vpu):
    """Keep the reviewed list of identifier columns, replacing their observations."""
    identifiers = []
    for entry in base_identifiers:
        key = (entry["table"], entry["column"])
        observations = {vpu: found["identifiers"][key] for vpu, found in by_vpu.items() if key in found["identifiers"]}
        if not observations:
            continue
        entry = {**entry, "observations": observations}
        if any("prefix_counts" in found for found in observations.values()):
            # A convenience summary of what was seen, not an allowed-prefix rule.
            entry["observed_prefixes"] = sorted({prefix for found in observations.values()
                                                 for prefix in found["prefix_counts"]})
        identifiers.append(entry)
    return identifiers


def build_candidate(base, by_vpu):
    """Replace the observed sections of the reviewed base; carry everything else over."""
    candidate = copy.deepcopy(base)
    candidate["sources"] = [found["source"] for found in by_vpu.values()]
    candidate["tables"] = next(iter(by_vpu.values()))["structure"]
    candidate["identifiers"] = build_identifiers(base["identifiers"], by_vpu)
    candidate["terminal_observations"] = [entry for found in by_vpu.values() for entry in found["terminals"]]
    return candidate


def table_differences(name, first, second, vpus):
    """Describe how one table differs between two VPUs' GeoPackages."""
    first_vpu, second_vpu = vpus
    problems = []
    for field in ("gpkg_contents", "geometry"):
        if first[field] != second[field]:
            problems.append(f"{name}: {field} is {first[field]} in VPU {first_vpu} but {second[field]} in VPU {second_vpu}")
    first_columns = {column["name"]: column["type"] for column in first["columns"]}
    second_columns = {column["name"]: column["type"] for column in second["columns"]}
    for column in first_columns.keys() - second_columns.keys():
        problems.append(f"{name}: column {column!r} is in VPU {first_vpu} but not in VPU {second_vpu}")
    for column in second_columns.keys() - first_columns.keys():
        problems.append(f"{name}: column {column!r} is in VPU {second_vpu} but not in VPU {first_vpu}")
    for column in first_columns.keys() & second_columns.keys():
        if first_columns[column] != second_columns[column]:
            problems.append(f"{name}: column {column!r} is {first_columns[column]} in VPU {first_vpu} "
                            f"but {second_columns[column]} in VPU {second_vpu}")
    if not problems and first["columns"] != second["columns"]:
        problems.append(f"{name}: columns are in a different order in VPU {first_vpu} and VPU {second_vpu}")
    return problems


def structure_conflicts(by_vpu):
    """List every way the VPUs' structures disagree with the first VPU's; empty if they all agree."""
    (first_vpu, first), *others = by_vpu.items()
    problems = []
    for vpu, found in others:
        for name in sorted(first["structure"].keys() | found["structure"].keys()):
            in_first, in_other = name in first["structure"], name in found["structure"]
            if in_first and in_other:
                problems += table_differences(name, first["structure"][name], found["structure"][name], (first_vpu, vpu))
            else:
                owner, missing = (first_vpu, vpu) if in_first else (vpu, first_vpu)
                problems.append(f"{name}: table is in VPU {owner} but not in VPU {missing}")
    return problems


def write_json(path, spec):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def unusable_reason(candidate):
    """Explain why the Consistency Checks could not use the candidate, or return ``None``.

    The reviewed sections were written for the previous structure, so a changed structure can
    leave them pointing at layers or columns that no longer exist.
    """
    try:
        data_model.validate_spec(copy.deepcopy(candidate))
    except ValueError as exc:
        return (f"the checks cannot use this candidate ({exc}); the reviewed sections "
                f"(checks, attribute_constraints) need editing to match the new structure")
    return None


def destination(arguments):
    """Choose where to write, never letting a candidate replace the checked-in file by accident."""
    checked_in = data_model.MODELS / arguments.data_model / f"{arguments.kind}.json"
    if arguments.update:
        return checked_in
    target = arguments.output or CANDIDATES / arguments.data_model / f"{arguments.kind}.json"
    if target.resolve() == checked_in.resolve():
        raise ExtractionError(f"{target} is the checked-in specification; pass --update to replace it")
    return target


def parse_file_urls(items, supplied_vpus):
    """Read ``VPU=URL`` options, each of which must name a VPU that was supplied."""
    urls = {}
    for item in items:
        vpu, separator, url = item.partition("=")
        if not separator or not url:
            raise ExtractionError(f"--file-url {item!r} must look like VPU=URL")
        if vpu not in supplied_vpus:
            raise ExtractionError(f"--file-url names VPU {vpu}, but no GeoPackage was supplied for it")
        urls[vpu] = url
    return urls


def observe_all(arguments, base):
    """Observe every GeoPackage, keyed by VPU in sorted order."""
    paths = {}
    for path in arguments.geopackages:
        vpu = vpu_of(path, arguments.kind)
        if vpu in paths:
            raise ExtractionError(f"VPU {vpu} has more than one GeoPackage: {paths[vpu]} and {path}")
        paths[vpu] = path
    file_urls = parse_file_urls(arguments.file_url, paths)
    by_vpu = {}
    for vpu in sorted(paths):
        # Only provenance the person supplied is recorded; no URL is derived from a name.
        urls = {}
        if arguments.resource_url:
            urls["resource_url"] = arguments.resource_url
        if vpu in file_urls:
            urls["file_url"] = file_urls[vpu]
        by_vpu[vpu] = observe(paths[vpu], vpu, base, urls)
    return by_vpu


def dropped_content(base, candidate):
    """List what the base specification had and the supplied GeoPackages do not reproduce."""
    notes = []
    kept_vpus = {source["vpu"] for source in candidate["sources"]}
    for source in base["sources"]:
        if source["vpu"] not in kept_vpus:
            notes.append(f"VPU {source['vpu']} was a source of the base specification but no GeoPackage was "
                         f"supplied for it, so its observations are gone")
    kept = {(entry["table"], entry["column"]) for entry in candidate["identifiers"]}
    for entry in base["identifiers"]:
        if (entry["table"], entry["column"]) not in kept:
            notes.append(f"identifier {entry['table']}.{entry['column']} is not in the supplied GeoPackages "
                         f"and was dropped")
    return notes


def run(arguments):
    try:
        base = data_model.load_spec(arguments.data_model, arguments.kind, "extractor base")
    except ValueError as exc:
        raise ExtractionError(f"{exc}; the reviewed specification to start from must exist") from exc
    target = destination(arguments)
    by_vpu = observe_all(arguments, base)
    conflicts = structure_conflicts(by_vpu)
    if conflicts:
        print("error: the VPUs have conflicting structures, so no candidate was written:", file=sys.stderr)
        for problem in conflicts:
            print(f"  {problem}", file=sys.stderr)
        return 1
    candidate = build_candidate(base, by_vpu)
    for note in dropped_content(base, candidate):
        print(f"note: {note}", file=sys.stderr)
    unusable = unusable_reason(candidate)
    if unusable and arguments.update:
        print(f"error: {unusable}; {target} was not changed", file=sys.stderr)
        return 1
    write_json(target, candidate)
    print(f"Wrote {'the specification' if arguments.update else 'candidate'} {target}")
    if unusable:
        print(f"warning: {unusable}", file=sys.stderr)
        return 1
    return 0


def main(argv=None):
    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    try:
        return run(arguments)
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
