"""Layer relationship Consistency Checks."""


def quote(name):
    """Quote an SQLite identifier, which cannot be supplied as a parameter."""
    return '"' + name.replace('"', '""') + '"'


def orphan_counts(connection, source, source_key, target, target_key, flag=None):
    """Count missing references and, when available, their zero-flag subset."""
    source_sql, source_key_sql = quote(source), quote(source_key)
    target_sql, target_key_sql = quote(target), quote(target_key)
    counts = "COUNT(*)"
    if flag is not None:
        counts += f", COALESCE(SUM(CASE WHEN {quote(flag)} = 0 THEN 1 ELSE 0 END), 0)"
    # SQLite materializes the IN subquery as a lookup, avoiding a quadratic
    # correlated scan on GeoPackages without indexes on relationship keys.
    return connection.execute(
        f"SELECT {counts} FROM {source_sql} WHERE {source_key_sql} IS NULL OR "
        f"{source_key_sql} NOT IN (SELECT {target_key_sql} FROM {target_sql} "
        f"WHERE {target_key_sql} IS NOT NULL)"
    ).fetchone()


def reciprocal_counts(connection):
    """Count directed links from each layer with mismatched or ambiguous back-references.

    Source and target IDs must be non-null and present. A duplicated target ID
    is ambiguous immediately; otherwise a null or missing back-reference is
    skipped. With a resolved back-reference, duplicate source or back-reference
    IDs are ambiguous; only unique IDs can produce a mismatch. Duplicate rows
    are counted per source row, not as Cartesian join pairs.
    """
    ambiguous = object()
    references = {}
    tables = (("divides", "divide_id", "id"), ("flowpaths", "id", "divide_id"))
    for table, identifier_column, reference_column in tables:
        index = {}
        for identifier, reference in connection.execute(
            f"SELECT {quote(identifier_column)}, {quote(reference_column)} FROM {quote(table)}"
        ):
            if identifier is not None:
                # Never choose a representative of a duplicate ID, even if its rows agree.
                index[identifier] = ambiguous if identifier in index else reference
        references[table] = index

    mismatches = ambiguities = 0
    # Inspect both directions: a shared target can make only one side disagree.
    for table, identifier_column, reference_column in tables:
        source_index = references[table]
        target_index = references["flowpaths" if table == "divides" else "divides"]
        for identifier, reference in connection.execute(
            f"SELECT {quote(identifier_column)}, {quote(reference_column)} FROM {quote(table)}"
        ):
            if identifier is None or reference is None or reference not in target_index:
                continue
            back_reference = target_index[reference]
            if back_reference is ambiguous:
                ambiguities += 1
            elif back_reference is None or back_reference not in source_index:
                continue
            elif source_index[identifier] is ambiguous or source_index[back_reference] is ambiguous:
                ambiguities += 1
            elif back_reference != identifier:
                mismatches += 1
    return mismatches, ambiguities


def metrics(connection, kind, columns):
    """Return relationship counts for the structured CLI report."""
    result = {}
    network_columns = {name for name in columns.get("network", set()) if name.lower() != "fid"}
    if network_columns:
        # Exact text comparison must not inherit a column's NOCASE collation.
        fields = ", ".join(f"{quote(name)} COLLATE BINARY" for name in sorted(network_columns))
        result["duplicate_network_rows"] = connection.execute(
            f"SELECT COALESCE(SUM(n - 1), 0) FROM "
            f"(SELECT COUNT(*) AS n FROM {quote('network')} GROUP BY {fields})"
        ).fetchone()[0]
    relationships = [
        ("divides_without_flowpaths", "divides", "id", "flowpaths", "id"),
        ("divides_without_referencing_flowpaths", "divides", "divide_id", "flowpaths", "divide_id"),
        ("flowpaths_without_divides", "flowpaths", "divide_id", "divides", "divide_id"),
    ]
    if kind == "ngen":
        relationships.extend([
            ("divides_without_attributes", "divides", "divide_id", "divide-attributes", "divide_id"),
            ("hydrolocations_without_nexus", "hydrolocations", "nex_id", "nexus", "id"),
        ])
    flags = {
        "divides_without_flowpaths": "has_flowline",
        "divides_without_referencing_flowpaths": "has_flowline",
        "flowpaths_without_divides": "has_divide",
        "divides_without_attributes": "has_flowline",
    }
    for name, source, source_key, target, target_key in relationships:
        if source_key in columns.get(source, set()) and target_key in columns.get(target, set()):
            flag = flags.get(name)
            if flag not in columns[source]:
                flag = None
            counts = orphan_counts(connection, source, source_key, target, target_key, flag)
            result[name] = counts[0]
            if flag is not None:
                result[f"{name}.{flag}_0"] = counts[1]
    if all({"id", "divide_id"} <= columns.get(table, set()) for table in ("divides", "flowpaths")):
        mismatches, ambiguities = reciprocal_counts(connection)
        result["reciprocal_divide_flowpath_mismatches"] = mismatches
        result["reciprocal_divide_flowpath_ambiguous"] = ambiguities
    return result
