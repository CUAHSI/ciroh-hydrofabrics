"""Run consistency checks against hydrofabric GeoPackages."""

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import sqlite3
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path

import pyogrio
import yaml

from attributes.attribute_checks import attributes
from geometry.geometry_checks import geometry
from network.network_checks import network


HERE = Path(__file__).resolve().parent
FILENAME = re.compile(r"(reference|ngen)-hydrofabric-vpu-([A-Za-z0-9]+)\.gpkg")
RESOURCE_PATH = re.compile(r"/resource/([0-9a-f]{32})/?")
HOSTS = {"www.hydroshare.org", "hydroshare.org"}
STORAGE_BUCKETS = {"hydroshare-403701-prod-cloud-native-ciroh", "hydroshare-403701-prod-cloud-native-resource"}


def geopackage_layers(path, model, kind):
    """Report missing layers and layers without any features."""
    layers = pyogrio.list_layers(path)
    empty = sum(pyogrio.read_info(path, layer=layer[0])["features"] == 0 for layer in layers)
    return {"missing_layers": int(len(layers) == 0), "empty_layers": empty}


def quote_identifier(name):
    """Quote an SQLite identifier, which cannot be supplied as a query parameter."""
    return '"' + name.replace('"', '""') + '"'


def schema_geometry(connection, name, expected):
    """Compare registered geometry and CRS, allowing generic types on empty layers."""
    actual = connection.execute(
        "SELECT column_name, geometry_type_name, srs_id FROM gpkg_geometry_columns WHERE table_name = ?",
        (name,),
    ).fetchone()
    metrics = {f"missing_geometry_registration.{name}": int(actual is None)}
    if actual:
        metrics[f"geometry_column.{name}"] = int(actual[0] != expected["column"])
        metrics[f"geometry_crs.{name}"] = int(actual[2] != expected["srs_id"])
        authority = connection.execute(
            "SELECT organization, organization_coordsys_id FROM gpkg_spatial_ref_sys WHERE srs_id = ?",
            (actual[2],),
        ).fetchone()
        crs = expected["crs"]
        metrics[f"crs_authority.{name}"] = int(authority != (crs["authority"], crs["code"]))
        # GDAL can use a generic geometry declaration for empty layers.
        populated = connection.execute(f"SELECT EXISTS(SELECT 1 FROM {quote_identifier(name)})").fetchone()[0]
        metrics[f"geometry_type.{name}"] = int(
            expected["type"] != "GEOMETRY" and actual[1] != expected["type"]
            and not (not populated and actual[1] == "GEOMETRY")
        )
    return metrics


def schema_layer(connection, name, expected, contents):
    """Compare registration and columns of one existing layer."""
    metrics = {f"missing_registration.{name}": int(name not in contents)}
    if name in contents:
        metrics[f"layer_type.{name}"] = int(contents[name][0] != expected["gpkg_contents"]["data_type"])
        if expected["geometry"]:
            metrics[f"contents_crs.{name}"] = int(contents[name][1] != expected["geometry"]["srs_id"])
    actual = {row[1]: row[2] for row in connection.execute("SELECT * FROM pragma_table_info(?)", (name,))}
    target = {column["name"]: column["type"] for column in expected["columns"]}
    actual_names, target_names = set(actual), set(target)
    metrics[f"missing_columns.{name}"] = len(target_names - actual_names)
    metrics[f"extra_columns.{name}"] = len(actual_names - target_names)
    # Compare relative order even if missing columns have an allowed recorded count.
    common = actual_names & target_names
    metrics[f"column_order.{name}"] = int(
        [column for column in actual if column in common] != [column for column in target if column in common]
    )
    metrics[f"column_types.{name}"] = sum(
        actual[column] != target[column] for column in common if column != "geom"
    )
    if expected["geometry"]:
        metrics.update(schema_geometry(connection, name, expected["geometry"]))
    return metrics, actual_names


def schema_identifiers(connection, identifiers, columns_by_table):
    """Report unprefixed IDs and prefixes absent from the source observations."""
    metrics = {}
    for identifier in identifiers:
        name, column = identifier["table"], identifier["column"]
        if "observed_prefixes" not in identifier or column not in columns_by_table.get(name, set()):
            continue
        table_sql, column_sql = quote_identifier(name), quote_identifier(column)
        if not connection.execute(f"SELECT EXISTS(SELECT 1 FROM {table_sql} WHERE {column_sql} IS NOT NULL)").fetchone()[0]:
            continue
        # Query distinct prefixes over the entire column, not a feature sample.
        prefixes = {
            row[0] for row in connection.execute(
                f"SELECT DISTINCT substr({column_sql}, 1, instr({column_sql}, '-') - 1) "
                f"FROM {table_sql} WHERE instr({column_sql}, '-') > 1"
            )
        }
        metrics[f"unobserved_id_prefixes.{name}.{column}"] = len(prefixes - set(identifier["observed_prefixes"]))
        metrics[f"unprefixed_ids.{name}.{column}"] = connection.execute(
            f"SELECT COUNT(*) FROM {table_sql} WHERE {column_sql} IS NOT NULL AND instr({column_sql}, '-') <= 1"
        ).fetchone()[0]
    return metrics


def schema(path, model, kind):
    """Check a Build against its selected Data Model specification."""
    if model != "v2.2" or kind not in {"ngen", "reference"}:
        raise ValueError(f"no schema specification for Data Model {model!r}, output kind {kind!r}")
    spec_path = HERE / "models" / model / f"{kind}.json"
    with spec_path.open(encoding="utf-8") as stream:
        spec = json.load(stream)
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        contents = {row[0]: (row[1], row[2]) for row in connection.execute("SELECT table_name, data_type, srs_id FROM gpkg_contents")}
        metrics = {}
        columns_by_table = {}
        for name, expected in spec["tables"].items():
            metrics[f"missing_layer.{name}"] = int(name not in tables)
            if name in tables:
                layer_metrics, columns_by_table[name] = schema_layer(connection, name, expected, contents)
                metrics.update(layer_metrics)
        metrics.update(schema_identifiers(connection, spec["identifiers"], columns_by_table))
        return metrics


CHECKS = {"geopackage_layers": geopackage_layers, "schema": schema, "network": network, "geometry": geometry, "attributes": attributes}


class UniqueKeyLoader(yaml.SafeLoader):
    """Reject duplicate keys rather than silently overriding gating settings."""

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, (str, int, float, bool, type(None))):
                raise ValueError("YAML mapping keys must be scalar")
            if key in seen:
                raise ValueError(f"duplicate YAML key: {key!r}")
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load_yaml(path):
    with path.open(encoding="utf-8") as stream:
        data = yaml.load(stream, Loader=UniqueKeyLoader)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a YAML mapping")
    return data


def validate_vpu_keys(counts):
    # YAML converts unquoted numeric VPUs, potentially losing leading zeroes.
    for model, kinds in counts.items():
        if not isinstance(kinds, dict):
            raise ValueError(f"expected output-kind mapping for Data Model {model}")
        for kind, vpus in kinds.items():
            if not isinstance(vpus, dict):
                raise ValueError(f"expected VPU mapping for {model}.{kind}")
            if any(not isinstance(vpu, str) for vpu in vpus):
                raise ValueError(f"VPU keys in {model}.{kind} must be quoted strings")


def load_counts(path, *, allow_missing=False):
    try:
        counts = load_yaml(path)
    except FileNotFoundError:
        if not allow_missing:
            raise
        counts = {}
    validate_vpu_keys(counts)
    return counts


def validate_count(metric, value):
    if (type(value) not in (int, float) or value < 0 or
            (type(value) is float and not math.isfinite(value))):
        raise ValueError(f"invalid recorded count for {metric}: {value!r}")


def mapping_at(mapping, keys):
    for key in keys:
        if not isinstance(mapping, dict):
            raise ValueError(f"expected a mapping at {'.'.join(keys)}")
        mapping = mapping.get(key, {})
    if not isinstance(mapping, dict):
        raise ValueError(f"expected a mapping at {'.'.join(keys)}")
    return mapping


@contextmanager
def vpu_input(path, vpu):
    """Present just one VPU to every check when the input contains multiple VPUs."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source:
        layers = [row[0] for row in source.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'gpkg_%' "
            "AND name NOT LIKE 'rtree_%'"
        )]
        tagged = [name for name in layers if any(
            row[1] == "vpuid" for row in source.execute(f"PRAGMA table_info({quote_identifier(name)})")
        )]
        other_vpu = any(source.execute(
            f"SELECT 1 FROM {quote_identifier(name)} WHERE vpuid IS NOT NULL AND vpuid != ? LIMIT 1",
            (vpu,),
        ).fetchone() for name in tagged)
        untagged_rows = [name for name in tagged if source.execute(
            f"SELECT 1 FROM {quote_identifier(name)} WHERE vpuid IS NULL LIMIT 1"
        ).fetchone()]
        if not other_vpu and not untagged_rows:
            yield path
            return
        if len(tagged) != len(layers):
            raise ValueError(f"cannot isolate VPU {vpu}: some layers have no vpuid column")
        if not any(source.execute(
            f"SELECT 1 FROM {quote_identifier(name)} WHERE vpuid = ? LIMIT 1", (vpu,)
        ).fetchone() for name in tagged):
            raise ValueError(f"VPU {vpu} has no features in {path}")
        if set(untagged_rows) - {"network"}:
            raise ValueError(f"cannot isolate VPU {vpu}: some features have no vpuid")
        if "network" in untagged_rows:
            # The CONUS network has no-flowline rows without vpuid. They belong
            # to the VPU of their divide, which must be unambiguous.
            if "divides" not in tagged or not any(
                row[1] == "divide_id" for row in source.execute('PRAGMA table_info("network")')
            ):
                raise ValueError(f"cannot isolate VPU {vpu}: network rows have no VPU or divide")
            ambiguous = source.execute(
                'WITH owners AS (SELECT divide_id, MIN(vpuid) lo, MAX(vpuid) hi '
                'FROM divides WHERE divide_id IS NOT NULL GROUP BY divide_id) '
                'SELECT 1 FROM network n LEFT JOIN owners o ON n.divide_id = o.divide_id '
                'WHERE n.vpuid IS NULL AND (o.divide_id IS NULL OR o.lo IS NULL OR o.lo != o.hi) LIMIT 1'
            ).fetchone()
            if ambiguous:
                raise ValueError(f"cannot isolate VPU {vpu}: network rows have ambiguous divides")

    # Keep the original declarations, registrations and feature IDs so schema,
    # network, geometry and attribute checks all see the same selected rows.
    scratch = HERE.parents[1] / ".scratch"
    scratch.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="consistency-check-vpu-", dir=scratch) as directory:
        selected = Path(directory) / path.name
        with closing(sqlite3.connect(selected, uri=True)) as connection:
            connection.execute("ATTACH DATABASE ? AS source", (path.resolve().as_uri() + "?mode=ro",))
            # Keep GeoPackage identification, but do not claim the selected VPU
            # occupies the source's CONUS-wide spatial extent.
            for pragma in ("application_id", "user_version"):
                value = connection.execute(f"PRAGMA source.{pragma}").fetchone()[0]
                connection.execute(f"PRAGMA {pragma} = {value}")
            tables = list(connection.execute(
                "SELECT name, sql FROM source.sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'rtree_%' "
                "AND name != 'gpkg_ogr_contents'"
            ))
            for name, create_sql in tables:
                connection.execute(create_sql)
                table = quote_identifier(name)
                if name == "gpkg_extensions":
                    connection.execute(
                        f"INSERT INTO {table} SELECT * FROM source.{table} "
                        "WHERE extension_name != 'gpkg_rtree_index'"
                    )
                elif name.startswith("gpkg_"):
                    connection.execute(f"INSERT INTO {table} SELECT * FROM source.{table}")
                elif name == "network" and "network" in untagged_rows:
                    connection.execute(
                        f"INSERT INTO {table} SELECT * FROM source.{table} "
                        'WHERE vpuid = ? OR (vpuid IS NULL AND divide_id IN '
                        '(SELECT divide_id FROM source."divides" WHERE vpuid = ?))', (vpu, vpu),
                    )
                else:
                    connection.execute(
                        f"INSERT INTO {table} SELECT * FROM source.{table} WHERE vpuid = ?", (vpu,)
                    )
            connection.execute(
                "UPDATE gpkg_contents SET min_x = NULL, min_y = NULL, max_x = NULL, max_y = NULL "
                "WHERE data_type = 'features'"
            )
            connection.commit()
        yield selected


def check_file(path, label, model, config, counts, kind=None, vpu=None, measurements=None):
    if kind is None or vpu is None:
        match = FILENAME.fullmatch(path.name)
        if not match:
            raise ValueError(f"unrecognized GeoPackage filename: {label}")
        kind, vpu = match.groups()
    recorded = mapping_at(counts, [model, kind, vpu])
    if measurements is not None:
        identity = (model, kind, vpu)
        if identity in measurements:
            raise ValueError(f"duplicate GeoPackage identity for {model} | {kind} | {vpu}: {label}")
        measurements[identity] = {}
    with vpu_input(path, vpu) as checked_path:
        return check_selected_file(checked_path, label, model, kind, vpu, config, recorded, measurements)


def check_selected_file(path, label, model, kind, vpu, config, recorded, measurements):
    print(f"{label} | {model} | {kind} | {vpu}")
    print("check | metric | value | recorded count | result | mode")
    status = 0
    identity = (model, kind, vpu)
    for name, check in CHECKS.items():
        blocking = config[name]["blocking"]
        try:
            limits = mapping_at(recorded, [name])
            # Each check receives the selected model and output kind so future
            # Data Model checks can select the appropriate specification.
            informational, errors = {}, []
            if name == "geometry":
                metrics, informational, errors = check(
                    path, model, kind, overlap_min_area_m2=config[name].get("overlap_min_area_m2", 100)
                )
            elif name == "attributes":
                metrics, informational = check(path, model, kind)
            else:
                metrics = check(path, model, kind)
            if not isinstance(metrics, dict) or (not metrics and not errors):
                raise ValueError("returned no named metrics")
            results = []
            for metric, value in metrics.items():
                limit = limits.get(metric, 0)
                validate_count(metric, limit)
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid value for {metric}: {value!r}")
                results.append((metric, value, limit, value <= limit))
            for metric, value in informational.items():
                if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                    raise ValueError(f"invalid informational value for {metric}: {value!r}")
        except Exception as exc:
            print(f"error: {label}: check {name} could not run: {exc}", file=sys.stderr)
            status = 2
            continue
        if measurements is not None:
            measurements[identity][name] = dict(metrics)
        for metric, value, limit, passed in results:
            if blocking and not passed:
                status = max(status, 1)
            print(f"{name} | {metric} | {value} | {limit} | {'PASS' if passed else 'FAIL'} | {'blocking' if blocking else 'advisory'}")
        for metric, value in informational.items():
            print(f"{name} | {metric} | {value} | - | INFO | {'blocking' if blocking else 'advisory'}")
        for error in errors:
            print(f"error: {label}: check {name}: {error}", file=sys.stderr)
            status = 2
    return status


def write_counts(path, measurements):
    """Merge measurements into the latest counts while holding a shared-file lock."""
    destination = path.resolve()
    lock_path = destination.with_name(f".{destination.name}.consistency-check.lock")
    # The lock has a stable inode across atomic replacements; never remove it
    # while recorders may be active or waiting for the lock. Prefer a writable
    # descriptor for NFS, but allow shared read-only locks on local filesystems.
    try:
        lock = lock_path.open("a", encoding="utf-8")
    except PermissionError:
        lock = lock_path.open("r", encoding="utf-8")
    with lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        counts = load_counts(destination, allow_missing=True)
        for (model, kind, vpu), checks in measurements.items():
            recorded = mapping_at(counts, [model, kind, vpu])
            for check, metrics in checks.items():
                limits = mapping_at(recorded, [check])
                for metric in metrics:
                    validate_count(metric, limits.get(metric, 0))
        merge_counts(counts, measurements)
        replace_counts(destination, counts)


def merge_counts(counts, measurements):
    """Merge only measured values, preserving other entries and YAML aliases."""
    for (model, kind, vpu), checks in measurements.items():
        # YAML aliases may share mappings across identities or checks. Copy each
        # updated path so recording one entry cannot mutate an unrelated one.
        counts[model] = dict(counts.get(model, {}))
        kinds = counts[model]
        kinds[kind] = dict(kinds.get(kind, {}))
        vpus = kinds[kind]
        vpus[vpu] = dict(vpus.get(vpu, {}))
        recorded = vpus[vpu]
        for check, metrics in checks.items():
            recorded[check] = {**recorded.get(check, {}), **metrics}



class QuotedVPU(str):
    """Mark VPU keys for consistent quoting in recorded counts."""


class CountsDumper(yaml.SafeDumper):
    """Dump counts using safe YAML types and quoted VPU keys."""


def represent_vpu(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="'")


CountsDumper.add_representer(QuotedVPU, represent_vpu)


def quote_vpu_keys(counts):
    # Only VPU keys need a fixed style; keep PyYAML's defaults for the rest.
    return {
        model: {
            kind: {QuotedVPU(vpu): checks for vpu, checks in vpus.items()}
            for kind, vpus in kinds.items()
        }
        for model, kinds in counts.items()
    }


def replace_counts(destination, counts):
    """Atomically replace counts after successful serialization."""
    # The temporary file must share a directory with the destination for atomic rename.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            if destination.exists():
                os.fchmod(stream.fileno(), stat.S_IMODE(destination.stat().st_mode))
            yaml.dump(quote_vpu_keys(counts), stream, Dumper=CountsDumper,
                      sort_keys=True, allow_unicode=True)
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def https_url(url, hosts):
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or
            parsed.password or parsed.port not in (None, 443) or parsed.fragment):
        raise ValueError("unsafe HydroShare URL")
    return parsed


class DownloadRedirect(urllib.request.HTTPRedirectHandler):
    """Follow only HydroShare redirects to the same file or its known storage buckets."""

    def __init__(self, resource, relative_path):
        self.resource = resource
        self.relative_path = relative_path

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = https_url(newurl, HOSTS | {"storage.googleapis.com"})
        path = urllib.parse.unquote(parsed.path).rstrip("/")
        contents = f"{self.resource}/data/contents/{self.relative_path}"
        if parsed.hostname in HOSTS:
            allowed = path in {f"/resource/{contents}", f"/django_irods/rest_download/{contents}"}
        else:
            allowed = any(path == f"/{bucket}/{contents}" for bucket in STORAGE_BUCKETS)
        if not allowed:
            raise ValueError("unsafe HydroShare download redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def hydroshare_files(target):
    parsed = https_url(target, HOSTS)
    match = RESOURCE_PATH.fullmatch(parsed.path)
    if not match or parsed.query:
        raise ValueError("expected a HydroShare resource URL, e.g. https://www.hydroshare.org/resource/<id>/")
    resource = match.group(1)
    listing_path = f"/hsapi/resource/{resource}/files/"
    next_url = f"https://www.hydroshare.org{listing_path}"
    visited = set()
    count = None
    seen = 0
    found = False
    opener = urllib.request.build_opener(DownloadRedirect(resource, ""))
    while next_url:
        page_url = https_url(next_url, HOSTS)
        if page_url.path != listing_path or next_url in visited:
            raise ValueError("invalid or repeated HydroShare listing page")
        visited.add(next_url)
        with opener.open(next_url, timeout=120) as response:
            page = json.load(response)
        if not isinstance(page, dict) or not isinstance(page.get("results"), list):
            raise ValueError("invalid HydroShare file listing")
        if type(page.get("count")) is not int or page["count"] < 0 or (count is not None and count != page["count"]):
            raise ValueError("invalid or changed HydroShare listing count")
        count = page["count"]
        for entry in page["results"]:
            seen += 1
            if not isinstance(entry, dict) or not isinstance(entry.get("file_name"), str) or not isinstance(entry.get("url"), str):
                raise ValueError("invalid file in HydroShare listing")
            name = entry["file_name"]
            if not name.lower().endswith(".gpkg"):
                continue
            found = True
            # HydroShare's API currently emits HTTP file URLs; use the validated
            # resource-relative path with HTTPS rather than trusting that URL.
            file_url = urllib.parse.urlsplit(entry["url"])
            if file_url.scheme not in {"http", "https"} or file_url.hostname not in HOSTS or file_url.username or file_url.password or file_url.port not in (None, 80, 443) or file_url.query or file_url.fragment:
                raise ValueError("invalid HydroShare file URL")
            prefix = f"/resource/{resource}/data/contents/"
            if not file_url.path.startswith(prefix):
                raise ValueError("file URL does not belong to the requested HydroShare resource")
            relative = urllib.parse.unquote(file_url.path[len(prefix):])
            if (not relative or relative.split("/")[-1] != name or
                    any(part in ("", ".", "..") for part in relative.split("/")) or "\\" in relative):
                raise ValueError("invalid HydroShare file path")
            label = f"https://www.hydroshare.org{file_url.path}"
            if not FILENAME.fullmatch(name):
                yield Path(name), label
                continue
            if type(entry.get("size")) is not int or entry["size"] <= 0:
                print(f"error: invalid HydroShare file size: {label}", file=sys.stderr)
                yield None, label
                continue
            expected_size = entry["size"]
            download = urllib.request.build_opener(DownloadRedirect(resource, relative))
            with tempfile.TemporaryDirectory(prefix="consistency-check-") as directory:
                path = Path(directory) / name
                try:
                    with download.open(label, timeout=120) as response, path.open("wb") as stream:
                        shutil.copyfileobj(response, stream, length=1024 * 1024)
                except Exception as exc:
                    # Do not expose signed storage URLs in the report.
                    print(f"error: could not download {label} ({type(exc).__name__})", file=sys.stderr)
                    yield None, label
                    continue
                if path.stat().st_size != expected_size:
                    print(f"error: incomplete download of {label}: expected {expected_size} bytes, got {path.stat().st_size}", file=sys.stderr)
                    yield None, label
                    continue
                yield path, label
        next_url = page.get("next")
        if next_url is not None and not isinstance(next_url, str):
            raise ValueError("invalid HydroShare next page")
    if seen != count:
        raise ValueError(f"incomplete HydroShare listing: received {seen} of {count} files")
    if not found:
        raise ValueError("no GeoPackages found in HydroShare resource")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="GeoPackage, directory, or HydroShare resource URL")
    parser.add_argument("--data-model", default="v2.2")
    parser.add_argument("--type", choices=("ngen", "reference"), help="output type for a single GeoPackage")
    parser.add_argument("--vpu", help="VPU for a single GeoPackage")
    parser.add_argument("--counts", type=Path, default=HERE / "counts.yaml")
    parser.add_argument("--config", type=Path, default=HERE / "checks.yaml")
    parser.add_argument("--record", action="store_true", help="record measured limits in the counts file")
    args = parser.parse_args(argv)

    try:
        counts_path = args.counts.resolve()
        counts = load_counts(counts_path, allow_missing=args.record)
        config = load_yaml(args.config)
        print(f"Configuration: {args.config} | Recorded counts: {args.counts}")
        for name in CHECKS:
            if not isinstance(config.get(name), dict) or type(config[name].get("blocking")) is not bool:
                raise ValueError(f"{args.config}: {name} must have a boolean blocking flag")
        if "geometry" in CHECKS:
            threshold = config["geometry"].get("overlap_min_area_m2", 100)
            if type(threshold) not in (int, float) or not math.isfinite(threshold) or threshold < 0:
                raise ValueError(f"{args.config}: geometry overlap_min_area_m2 must be a finite nonnegative number")
        metadata = (None, None)
        if urllib.parse.urlsplit(args.target).scheme:
            if args.type is not None or args.vpu is not None:
                raise ValueError("--type and --vpu are only valid for a single GeoPackage")
            paths = hydroshare_files(args.target)
        else:
            target = Path(args.target)
            if target.is_dir():
                if args.type is not None or args.vpu is not None:
                    raise ValueError("--type and --vpu are only valid for a single GeoPackage")
                local = sorted(path for path in target.rglob("*") if path.is_file() and path.suffix.lower() == ".gpkg")
                if not local:
                    raise ValueError(f"no GeoPackages found in {target}")
            elif target.is_file():
                if args.type is None or args.vpu is None:
                    raise ValueError("a single GeoPackage requires --type and --vpu")
                if not re.fullmatch(r"[A-Za-z0-9]+", args.vpu):
                    raise ValueError("VPU must contain only letters and digits")
                metadata = (args.type, args.vpu)
                local = [target]
            else:
                raise ValueError(f"target does not exist: {target}")
            paths = ((path, str(path)) for path in local)
        status = 0
        measurements = {} if args.record else None
        for path, label in paths:
            if path is None:
                status = 2
                continue
            try:
                status = max(status, check_file(
                    path, label, args.data_model, config, counts, *metadata, measurements=measurements
                ))
            except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
                print(f"error: {label}: checks could not run: {exc}", file=sys.stderr)
                status = 2
        # A blocking failure is a complete measurement; status 2 means at
        # least one file or check was incomplete, so nothing can be recorded.
        if measurements is not None and status != 2:
            write_counts(counts_path, measurements)
            print(f"Recorded counts: {args.counts}")
        return status
    except (OSError, RuntimeError, ValueError, sqlite3.Error, yaml.YAMLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
