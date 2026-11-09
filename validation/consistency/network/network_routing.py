"""Routing graph Consistency Checks.

Dangling counts are source rows, including possible VPU-boundary links. Cycle
counts are distinct member IDs; identical edges are collapsed and conflicting
edges are retained. NULL targets are reported separately as indeterminate and
excluded from dangling counts. Terminal rules compare observations with the
v2.2 outlet convention, not an exhaustive, authoritative specification.
"""


OUTLET_TYPES = {"tnx-": "terminal", "cnx-": "coastal", "inx-": "internal"}
NEXUS_TARGET_LAYERS = ("flowpaths", "divides", "flowpath-attributes", "flowpath-attributes-ml")


def cycle_node_count(connection, tables, sentinel):
    """Count nodes in cyclic strongly connected components without recursion."""
    edges = {}
    for table in tables:
        for source, target in connection.execute(f'SELECT id, toid FROM "{table}"'):
            if source is not None and target is not None and target != sentinel:
                edges.setdefault(source, set()).add(target)

    index = {}
    low = {}
    active = set()
    components = []
    count = 0

    def visit(node):
        index[node] = low[node] = len(index)
        active.add(node)
        components.append(node)
        return (node, iter(edges.get(node, ())))

    # Iterative Tarjan traversal preserves all outgoing edges for duplicate IDs;
    # only SCC members, not nodes reachable downstream from a cycle, are counted.
    for root in edges:
        if root in index:
            continue
        stack = [visit(root)]
        while stack:
            node, targets = stack[-1]
            target = next(targets, None)
            if target is not None:
                if target not in edges:
                    continue
                if target not in index:
                    stack.append(visit(target))
                elif target in active:
                    low[node] = min(low[node], index[target])
                continue

            stack.pop()
            if stack:
                parent = stack[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                size = 0
                while True:
                    member = components.pop()
                    active.remove(member)
                    size += 1
                    if member == node:
                        break
                if size > 1 or node in edges[node]:
                    count += size
    return count


def invalid_nexus_outlet(identifier, nexus_type, target):
    """Compare outlet-like rows with the observed v2.2 nexus convention."""
    expected_type = OUTLET_TYPES.get(identifier[:4]) if isinstance(identifier, str) else None
    outlet_like = target == "wb-0" or expected_type is not None or nexus_type in OUTLET_TYPES.values()
    return outlet_like and not (expected_type is not None and nexus_type == expected_type and target == "wb-0")


def reference_metrics(connection, columns):
    """Check Reference flowpaths and network independently."""
    results = {}
    for table in ("flowpaths", "network"):
        if not {"id", "toid"} <= columns.get(table, set()):
            continue
        ids = {row[0] for row in connection.execute(f'SELECT id FROM "{table}"') if row[0] is not None}
        results[f"dangling_toid.{table}"] = sum(
            target is not None and target != 0 and target not in ids
            for (target,) in connection.execute(f'SELECT toid FROM "{table}"')
        )
        del ids
        results[f"cycle_nodes.{table}"] = cycle_node_count(connection, (table,), 0)
    return results


def nextgen_dangling_metrics(connection, columns):
    """Check each NextGen source against its applicable downstream ID set."""
    results = {}
    if "id" in columns.get("nexus", set()) and any(
        "toid" in columns.get(table, set()) for table in NEXUS_TARGET_LAYERS
    ):
        nexus_ids = {row[0] for row in connection.execute('SELECT id FROM "nexus"') if row[0] is not None}
        # Coastal and internal divides point to cnx-/inx- IDs in nexus;
        # their nexus outlets use wb-0, not a missing-flowpath link.
        for table in NEXUS_TARGET_LAYERS:
            if "toid" in columns.get(table, set()):
                results[f"dangling_toid.{table}"] = sum(
                    target is not None and target != "wb-0" and target not in nexus_ids
                    for (target,) in connection.execute(f'SELECT toid FROM "{table}"')
                )
        del nexus_ids
    if "toid" in columns.get("nexus", set()) and "id" in columns.get("flowpaths", set()):
        flowpath_ids = {row[0] for row in connection.execute('SELECT id FROM "flowpaths"') if row[0] is not None}
        results["dangling_toid.nexus"] = sum(
            target is not None and target != "wb-0" and target not in flowpath_ids
            for (target,) in connection.execute('SELECT toid FROM "nexus"')
        )
        del flowpath_ids
    tables = ("flowpaths", "nexus", "network")
    # Network omits some valid coastal/internal nexus IDs; all three ID
    # sets are needed before a missing target can be established.
    if "toid" in columns.get("network", set()) and all("id" in columns.get(table, set()) for table in tables):
        ids = set()
        for table in tables:
            ids.update(row[0] for row in connection.execute(f'SELECT id FROM "{table}"') if row[0] is not None)
        results["dangling_toid.network"] = sum(
            target is not None and target != "wb-0" and target not in ids
            for (target,) in connection.execute('SELECT toid FROM "network"')
        )
    return results


def nextgen_terminal_metrics(connection, columns):
    """Compare NextGen outlet rows with the observed terminal convention."""
    results = {}
    # These layers should point to a nexus, even at an outlet.
    # Report direct wb-0 references separately from dangling targets.
    for table in NEXUS_TARGET_LAYERS:
        if "toid" in columns.get(table, set()):
            results[f"terminal_convention.{table}"] = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE toid = ?', ("wb-0",)
            ).fetchone()[0]
    for table in ("nexus", "network"):
        if not {"id", "type", "toid"} <= columns.get(table, set()):
            continue
        # Network also labels flowpaths by their downstream nexus type;
        # only nexus-like IDs and actual sentinel outlets are comparable.
        results[f"terminal_convention.{table}"] = sum(
            invalid_nexus_outlet(identifier, nexus_type, target)
            for identifier, nexus_type, target in connection.execute(f'SELECT id, type, toid FROM "{table}"')
            if table == "nexus" or target == "wb-0"
            or (isinstance(identifier, str) and identifier.startswith(("nex-", "tnx-", "cnx-", "inx-")))
        )
    return results


def metrics(connection, kind, columns):
    """Return applicable routing metrics for a read-only GeoPackage connection."""
    results = {}
    checked_layers = {
        "reference": ("flowpaths", "network"),
        "ngen": NEXUS_TARGET_LAYERS + ("nexus", "network"),
    }
    for table in checked_layers.get(kind, ()):
        if "toid" in columns.get(table, set()):
            results[f"indeterminate_null_toid.{table}"] = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE toid IS NULL'
            ).fetchone()[0]
    if kind == "reference":
        results.update(reference_metrics(connection, columns))
    elif kind == "ngen":
        results.update(nextgen_dangling_metrics(connection, columns))
        if all({"id", "toid"} <= columns.get(table, set()) for table in ("flowpaths", "nexus")):
            results["cycle_nodes.flowpaths_nexus"] = cycle_node_count(connection, ("flowpaths", "nexus"), "wb-0")
        if {"id", "toid"} <= columns.get("network", set()):
            results["cycle_nodes.network"] = cycle_node_count(connection, ("network",), "wb-0")
        results.update(nextgen_terminal_metrics(connection, columns))
    return results
