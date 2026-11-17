"""Routing graph Consistency Checks.

Dangling counts are source rows, including possible VPU-boundary links. Cycle
counts are distinct member IDs; identical edges are collapsed and conflicting
edges are retained. NULL targets are reported separately as indeterminate and
excluded from dangling counts. Terminal rules compare observations with the
outlet convention the Data Model declares (``routing`` in its network
section), which is not necessarily an exhaustive, authoritative specification.
"""


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


def invalid_nexus_outlet(identifier, nexus_type, target, routing):
    """Compare outlet-like rows with the Data Model's nexus outlet convention."""
    outlet_types = routing["outlet_types"]
    expected_type = None
    if isinstance(identifier, str):
        expected_type = next((kind for prefix, kind in outlet_types.items() if identifier.startswith(prefix)), None)
    outlet_like = target == routing["terminal_id"] or expected_type is not None or nexus_type in outlet_types.values()
    return outlet_like and not (
        expected_type is not None and nexus_type == expected_type and target == routing["terminal_id"]
    )


def direct_metrics(connection, columns, routing):
    """Check each directly routed layer (such as flowpaths and network) independently."""
    results = {}
    terminal = routing["terminal_id"]
    for table in routing["layers"]:
        if not {"id", "toid"} <= columns.get(table, set()):
            continue
        ids = {row[0] for row in connection.execute(f'SELECT id FROM "{table}"') if row[0] is not None}
        results[f"dangling_toid.{table}"] = sum(
            target is not None and target != terminal and target not in ids
            for (target,) in connection.execute(f'SELECT toid FROM "{table}"')
        )
        del ids
        results[f"cycle_nodes.{table}"] = cycle_node_count(connection, (table,), terminal)
    return results


def nextgen_dangling_metrics(connection, columns, routing):
    """Check each nexus-routed source against its applicable downstream ID set."""
    results = {}
    terminal = routing["terminal_id"]
    target_layers = routing["target_layers"]
    if "id" in columns.get("nexus", set()) and any(
        "toid" in columns.get(table, set()) for table in target_layers
    ):
        nexus_ids = {row[0] for row in connection.execute('SELECT id FROM "nexus"') if row[0] is not None}
        # Coastal and internal divides point to outlet nexus IDs;
        # their nexus outlets use the terminal ID, not a missing-flowpath link.
        for table in target_layers:
            if "toid" in columns.get(table, set()):
                results[f"dangling_toid.{table}"] = sum(
                    target is not None and target != terminal and target not in nexus_ids
                    for (target,) in connection.execute(f'SELECT toid FROM "{table}"')
                )
        del nexus_ids
    if "toid" in columns.get("nexus", set()) and "id" in columns.get("flowpaths", set()):
        flowpath_ids = {row[0] for row in connection.execute('SELECT id FROM "flowpaths"') if row[0] is not None}
        results["dangling_toid.nexus"] = sum(
            target is not None and target != terminal and target not in flowpath_ids
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
            target is not None and target != terminal and target not in ids
            for (target,) in connection.execute('SELECT toid FROM "network"')
        )
    return results


def nextgen_terminal_metrics(connection, columns, routing):
    """Compare nexus-routed outlet rows with the Data Model's terminal convention."""
    results = {}
    terminal = routing["terminal_id"]
    # These layers should point to a nexus, even at an outlet.
    # Report direct terminal references separately from dangling targets.
    for table in routing["target_layers"]:
        if "toid" in columns.get(table, set()):
            results[f"terminal_convention.{table}"] = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE toid = ?', (terminal,)
            ).fetchone()[0]
    nexus_prefixes = tuple(routing["nexus_id_prefixes"]) + tuple(routing["outlet_types"])
    for table in ("nexus", "network"):
        if not {"id", "type", "toid"} <= columns.get(table, set()):
            continue
        # Network also labels flowpaths by their downstream nexus type;
        # only nexus-like IDs and actual terminal outlets are comparable.
        results[f"terminal_convention.{table}"] = sum(
            invalid_nexus_outlet(identifier, nexus_type, target, routing)
            for identifier, nexus_type, target in connection.execute(f'SELECT id, type, toid FROM "{table}"')
            if table == "nexus" or target == terminal
            or (isinstance(identifier, str) and identifier.startswith(nexus_prefixes))
        )
    return results


def metrics(connection, columns, semantics):
    """Return applicable routing metrics for a read-only GeoPackage connection."""
    routing = semantics["routing"]
    results = {}
    if routing["style"] == "direct":
        checked_layers = tuple(routing["layers"])
    else:
        checked_layers = tuple(routing["target_layers"]) + ("nexus", "network")
    for table in checked_layers:
        if "toid" in columns.get(table, set()):
            results[f"indeterminate_null_toid.{table}"] = connection.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE toid IS NULL'
            ).fetchone()[0]
    if routing["style"] == "direct":
        results.update(direct_metrics(connection, columns, routing))
    else:
        results.update(nextgen_dangling_metrics(connection, columns, routing))
        if all({"id", "toid"} <= columns.get(table, set()) for table in ("flowpaths", "nexus")):
            results["cycle_nodes.flowpaths_nexus"] = cycle_node_count(
                connection, ("flowpaths", "nexus"), routing["terminal_id"]
            )
        if {"id", "toid"} <= columns.get("network", set()):
            results["cycle_nodes.network"] = cycle_node_count(connection, ("network",), routing["terminal_id"])
        results.update(nextgen_terminal_metrics(connection, columns, routing))
    return results
