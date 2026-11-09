"""Hydrosequence Consistency Checks for flowpath and network edges.

Metrics count source rows; edge checks exclude terminal links. Duplicate
flowpath-layer IDs and conflicting network values make resolution ambiguous;
other unresolved links or unusable comparison values are indeterminate.
Ambiguity takes precedence if an edge has both problems. Repeated network
rows with the same valid target value can be resolved without selecting a row.
Reference network rows labeled fl-fl have a supported downstream flowpath
meaning; other nonterminal topology labels are indeterminate. NextGen network
checks follow network nexus rows to network flowpath rows; nexus rows themselves
have no comparable flowpath hydrosequence. A separate comparison checks each
network flowpath row's sequence against its flowpath layer value, including
terminal flowpaths.
"""

import math


_AMBIGUOUS = object()
_INDETERMINATE = object()


def _valid_sequence(value):
    return type(value) in (int, float) and math.isfinite(value)


def _missing_id(value):
    return value is None or (isinstance(value, str) and not value.strip())


def metrics(connection, kind, columns):
    """Return applicable violation, indeterminate, and ambiguity counts."""
    flowpath_columns = columns.get("flowpaths", set())
    network_columns = columns.get("network", set())
    if kind not in {"reference", "ngen"} or "id" not in flowpath_columns:
        return {}

    has_flowpath_sequence = "hydroseq" in flowpath_columns
    nexus_columns = columns.get("nexus", set())
    has_nexus = {"id", "toid"} <= nexus_columns
    check_flowpaths = has_flowpath_sequence and "toid" in flowpath_columns and (kind == "reference" or has_nexus)
    check_network = (
        kind == "reference"
        and has_flowpath_sequence
        and {"id", "toid", "topo"} <= network_columns
        and bool({"hydroseq", "dnhydroseq"} & network_columns)
    ) or (
        kind == "ngen" and "id" in nexus_columns and {"id", "toid", "hydroseq"} <= network_columns
    )
    check_network_sequences = (
        kind == "ngen" and has_flowpath_sequence and "id" in nexus_columns
        and {"id", "hydroseq"} <= network_columns
    )
    if not check_flowpaths and not check_network and not check_network_sequences:
        return {}

    # Duplicate flowpath IDs are never used to resolve a target, even when
    # their hydrosequence values agree.
    flowpaths = {}
    fields = "id, hydroseq" if has_flowpath_sequence else "id, NULL"
    for identifier, sequence in connection.execute(f'SELECT {fields} FROM "flowpaths"'):
        if not _missing_id(identifier):
            flowpaths[identifier] = _AMBIGUOUS if identifier in flowpaths else sequence

    nexuses = {}
    if kind == "ngen":
        fields = "id, toid" if has_nexus else "id, NULL"
        for identifier, downstream_id in connection.execute(f'SELECT {fields} FROM "nexus"'):
            if not _missing_id(identifier):
                nexuses[identifier] = _AMBIGUOUS if identifier in nexuses else downstream_id

    result = {}
    if check_flowpaths:
        result.update(_flowpath_metrics(connection, kind, flowpath_columns, flowpaths, nexuses))
    if check_network:
        if kind == "reference":
            result.update(_reference_network_metrics(connection, network_columns, flowpaths))
        else:
            result.update(_nextgen_network_metrics(connection, flowpaths, nexuses))
    if check_network_sequences:
        result.update(_nextgen_network_sequence_metrics(connection, flowpaths, nexuses))
    return result


def _flowpath_metrics(connection, kind, flowpath_columns, flowpaths, nexuses):
    has_downstream_sequence = kind == "reference" and "dnhydroseq" in flowpath_columns
    result = {
        "hydroseq_order_violations.flowpaths": 0,
        "hydroseq_order_indeterminate.flowpaths": 0,
        "hydroseq_order_ambiguous.flowpaths": 0,
    }
    if has_downstream_sequence:
        result.update({
            "dnhydroseq_mismatches.flowpaths": 0,
            "dnhydroseq_indeterminate.flowpaths": 0,
            "dnhydroseq_ambiguous.flowpaths": 0,
        })

    fields = "id, toid, hydroseq, dnhydroseq" if has_downstream_sequence else "id, toid, hydroseq"
    for row in connection.execute(f'SELECT {fields} FROM "flowpaths"'):
        identifier, downstream_id, sequence = row[:3]
        if kind == "ngen":
            # Flowpaths lead to nexus; a uniquely resolved nexus can lead to a
            # downstream flowpath or to wb-0 (including coastal/internal outlets).
            downstream_id = nexuses.get(downstream_id)
            if downstream_id == "wb-0":
                continue
        elif downstream_id == 0:
            continue
        downstream = flowpaths.get(downstream_id)
        ambiguous = (
            flowpaths.get(identifier) is _AMBIGUOUS
            or downstream_id is _AMBIGUOUS
            or downstream is _AMBIGUOUS
        )
        unresolved = _missing_id(identifier) or _missing_id(downstream_id) or downstream_id not in flowpaths
        if ambiguous:
            result["hydroseq_order_ambiguous.flowpaths"] += 1
            if has_downstream_sequence:
                result["dnhydroseq_ambiguous.flowpaths"] += 1
            continue
        if unresolved or not _valid_sequence(sequence) or not _valid_sequence(downstream):
            result["hydroseq_order_indeterminate.flowpaths"] += 1
        elif sequence <= downstream:
            result["hydroseq_order_violations.flowpaths"] += 1
        if has_downstream_sequence:
            downstream_sequence = row[3]
            if unresolved or not _valid_sequence(downstream_sequence) or not _valid_sequence(downstream):
                result["dnhydroseq_indeterminate.flowpaths"] += 1
            elif downstream_sequence != downstream:
                result["dnhydroseq_mismatches.flowpaths"] += 1
    return result


def _nextgen_network_metrics(connection, flowpaths, nexuses):
    result = {
        "hydroseq_order_violations.network": 0,
        "hydroseq_order_indeterminate.network": 0,
        "hydroseq_order_ambiguous.network": 0,
    }
    # Network nexus IDs can have repeated rows; resolve only a single distinct
    # destination and never substitute the potentially different nexus layer.
    # Likewise, resolve a downstream flowpath only when every network row for
    # its ID has the same valid sequence, independent of the flowpaths layer.
    network_nexuses = {}
    network_sequences = {}
    for identifier, target, sequence in connection.execute('SELECT id, toid, hydroseq FROM "network"'):
        if identifier in nexuses:
            if identifier not in network_nexuses:
                network_nexuses[identifier] = target
            elif network_nexuses[identifier] != target:
                network_nexuses[identifier] = _AMBIGUOUS
        if identifier in flowpaths:
            value = sequence if _valid_sequence(sequence) else _INDETERMINATE
            if identifier not in network_sequences:
                network_sequences[identifier] = value
            elif network_sequences[identifier] != value:
                network_sequences[identifier] = _AMBIGUOUS

    for identifier, nexus_id, sequence in connection.execute('SELECT id, toid, hydroseq FROM "network"'):
        # NextGen network includes both flowpath and nexus rows. Classify the
        # source by membership, not network.type, topo, or an ID prefix: type
        # may describe a flowpath's downstream nexus, and labels can vary.
        is_flowpath = identifier in flowpaths
        is_nexus = identifier in nexuses
        if is_flowpath and is_nexus:
            result["hydroseq_order_ambiguous.network"] += 1
            continue
        if is_nexus:
            continue
        if not is_flowpath:
            result["hydroseq_order_indeterminate.network"] += 1
            continue

        downstream_id = network_nexuses.get(nexus_id)
        # Colliding IDs cannot reliably identify a flowpath-to-nexus edge or
        # its downstream flowpath, even when both layers contain that ID.
        if nexus_id in nexuses and nexus_id in flowpaths:
            result["hydroseq_order_ambiguous.network"] += 1
            continue
        if downstream_id == "wb-0":
            continue
        downstream = network_sequences.get(downstream_id)
        if (
            flowpaths[identifier] is _AMBIGUOUS
            or downstream_id is _AMBIGUOUS
            or flowpaths.get(downstream_id) is _AMBIGUOUS
            or downstream is _AMBIGUOUS
            or (downstream_id in flowpaths and downstream_id in nexuses)
        ):
            result["hydroseq_order_ambiguous.network"] += 1
        elif (
            _missing_id(nexus_id) or _missing_id(downstream_id) or downstream_id not in flowpaths
            or not _valid_sequence(sequence) or not _valid_sequence(downstream)
        ):
            result["hydroseq_order_indeterminate.network"] += 1
        elif sequence <= downstream:
            result["hydroseq_order_violations.network"] += 1
    return result


def _nextgen_network_sequence_metrics(connection, flowpaths, nexuses):
    """Compare network flowpath sequences independently of their routing."""
    result = {
        "hydroseq_mismatches.network": 0,
        "hydroseq_comparison_indeterminate.network": 0,
        "hydroseq_comparison_ambiguous.network": 0,
    }
    for identifier, sequence in connection.execute('SELECT id, hydroseq FROM "network"'):
        is_flowpath = identifier in flowpaths
        is_nexus = identifier in nexuses
        if is_flowpath and (is_nexus or flowpaths[identifier] is _AMBIGUOUS):
            result["hydroseq_comparison_ambiguous.network"] += 1
        elif is_nexus:
            continue
        elif not is_flowpath or not _valid_sequence(sequence) or not _valid_sequence(flowpaths[identifier]):
            result["hydroseq_comparison_indeterminate.network"] += 1
        elif sequence != flowpaths[identifier]:
            result["hydroseq_mismatches.network"] += 1
    return result


def _reference_network_metrics(connection, network_columns, flowpaths):
    has_sequence = "hydroseq" in network_columns
    has_downstream_sequence = "dnhydroseq" in network_columns
    result = {}
    if has_sequence:
        result.update({
            "hydroseq_order_violations.network": 0,
            "hydroseq_order_indeterminate.network": 0,
            "hydroseq_order_ambiguous.network": 0,
        })
    if has_downstream_sequence:
        result.update({
            "dnhydroseq_mismatches.network": 0,
            "dnhydroseq_indeterminate.network": 0,
            "dnhydroseq_ambiguous.network": 0,
        })

    # The two comparisons have independent sequence-field prerequisites.
    fields = ["id", "toid", "hydroseq" if has_sequence else "NULL", "topo"]
    fields.append("dnhydroseq" if has_downstream_sequence else "NULL")
    for identifier, downstream_id, sequence, topology, downstream_sequence in connection.execute(
        f'SELECT {", ".join(fields)} FROM "network"'
    ):
        if downstream_id == 0:
            continue
        if topology != "fl-fl":
            if has_sequence:
                result["hydroseq_order_indeterminate.network"] += 1
            if has_downstream_sequence:
                result["dnhydroseq_indeterminate.network"] += 1
            continue
        downstream = flowpaths.get(downstream_id)
        if downstream is _AMBIGUOUS:
            if has_sequence:
                result["hydroseq_order_ambiguous.network"] += 1
            if has_downstream_sequence:
                result["dnhydroseq_ambiguous.network"] += 1
            continue
        unresolved = _missing_id(identifier) or _missing_id(downstream_id) or downstream_id not in flowpaths
        if has_sequence:
            if unresolved or not _valid_sequence(sequence) or not _valid_sequence(downstream):
                result["hydroseq_order_indeterminate.network"] += 1
            elif sequence <= downstream:
                result["hydroseq_order_violations.network"] += 1
        if has_downstream_sequence:
            if unresolved or not _valid_sequence(downstream_sequence) or not _valid_sequence(downstream):
                result["dnhydroseq_indeterminate.network"] += 1
            elif downstream_sequence != downstream:
                result["dnhydroseq_mismatches.network"] += 1
    return result
