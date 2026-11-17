# Consistency Checks

A **Consistency Check** is an automated check that a Build is internally sound:
its network, geometry and attributes agree with one another and with the Data
Model the Build declares. Each check measures **one GeoPackage** and reports
counts. It does not compare the Build with another hydrofabric; that is the
job of Alignment Checks, which these pages do not cover.

The measured counts are compared with limits recorded from the official
products, so a Build may carry the official products' errors forward but may not
add to them. See [ADR 0001](../adr/0001-consistency-check-gating.md) for the
reasoning, and the project [glossary](../../GLOSSARY.md) for the terms Build,
Data Model and Official Hydrofabric.

```sh
pixi run consistency-check path/to/my-hydrofabric.gpkg --type ngen --vpu 16
```

## Pages

| Page | What it covers |
| --- | --- |
| [Reading a report](reading-a-report.md) | The report line, PASS / FAIL / INFO, advisory versus blocking, exit statuses `0`, `1` and `2`, and what a reviewer does on a FAIL. **Start here.** |
| [`geopackage_layers`](geopackage-layers.md) | Whether the file has layers and whether any are empty. |
| [`schema`](schema.md) | Layers, columns, registration, CRS and identifier prefixes against the Data Model specification. |
| [`network`](network.md) | Duplicate keys, dangling links, cycles, outlets, orphan features and `hydroseq` order. |
| [`geometry`](geometry.md) | Null, empty, invalid and duplicate shapes, and divide overlaps and gaps. |
| [`attributes`](attributes.md) | Positive and in-range values, sentinel candidates, and length consistency. |
| [Running and recording](running-and-recording.md) | The command line, VPU selection, HydroShare, `checks.yaml`, `counts.yaml`, `--record`, adding a Data Model or a check. |
| [The v2.2 Data Model](data-model-v2.2.md) | The evidence behind the v2.2 specifications. |

Every metric on the per-check pages is either a **ratcheted** count (PASS when
`value <= recorded count`, FAIL otherwise) or an **INFO** value that never
affects the gate. Each page has worked examples that were produced by running
the checker on small GeoPackages.

## Thresholds and conventions

These are the numbers and naming conventions the checks depend on. **Data Model
specific (v2.2)** means the value comes from the v2.2 specification in
[`validation/consistency/models/v2.2/`](../../validation/consistency/models/v2.2/)
(the `ngen.json` and `reference.json` files) and another Data Model may declare a different one.
That includes the 100 m² area thresholds, the 1 m length tolerance and the
terminal identifiers, because the checker reads them from the specification
rather than from code. **Generic** means it is fixed in the implementation and
applies to every Data Model.

This table is a summary. Each check page has the full list with the rationale,
and is the place to look first if the two ever differ.

| Item | Value | Scope | Source |
| --- | --- | --- | --- |
| Result of a ratcheted metric | PASS when `value <= recorded count`; a missing count is `0` | Generic | [`consistency_check.py`](../../validation/consistency/consistency_check.py), [ADR 0001](../adr/0001-consistency-check-gating.md) |
| Divide overlap threshold | 100 m², an overlap is counted when its area is **strictly greater** | Data Model specific (v2.2) | `checks.geometry.overlap_min_area_m2`; overridable with `geometry.overlap_min_area_m2` in `checks.yaml` |
| Divide gap threshold | 100 m², strictly greater | Data Model specific (v2.2) | `checks.geometry.gap_min_area_m2`; no override |
| Topology layer and CRS | `divides`, EPSG:5070 | Data Model specific (v2.2) | `checks.geometry.topology_layer` and the layer's registration |
| Length tolerance | 1 m absolute, comparing `Length_m` with `lengthkm * 1000` | Data Model specific (v2.2) | `length_consistency` rules, CAM-1602 |
| Attribute bounds | `0 < n <= 1`, `So >= 0`, `0 <= MusX <= 0.5`, and the others on the [attributes page](attributes.md) | Data Model specific (v2.2) | CAM-1602 assumptions, and the sources cited per rule |
| Sentinel candidate | `-9998` (meaning undetermined) | Data Model specific (v2.2) | `sentinel_handling` in the specification |
| Terminal `toid` | `wb-0` for `ngen`, `0` for `reference` | Data Model specific (v2.2) | `checks.network.routing.terminal_id` |
| Nexus outlet prefixes | `tnx-` terminal, `cnx-` coastal, `inx-` internal | Data Model specific (v2.2) | `checks.network.routing.outlet_types` |
| Reference network link label | `topo = fl-fl` | Data Model specific (v2.2) | `checks.network.routing.link_label` |
| Identifier prefix separator | `-` | Data Model specific (v2.2) | `checks.schema.id_prefix_separator` |
| `hydroseq` order | Upstream `hydroseq` greater than downstream | Generic | [`network_hydroseq.py`](../../validation/consistency/network/network_hydroseq.py) |
| Roundoff allowance for the length tolerance | A tiny allowance so the inclusive boundary is stable; see the [attributes page](attributes.md#thresholds-and-conventions) | Generic | [`attribute_checks.py`](../../validation/consistency/attributes/attribute_checks.py) |

The 100 m² thresholds are recorded in the specification files, but those files
and the sources behind them do not state why 100 m² was chosen. Treat the value
as a project convention, not a derived quantity.

## What is in scope

These pages describe the checks as implemented in
[`validation/consistency/`](../../validation/consistency/): the five registered
checks above, for the v2.2 `ngen` and `reference` output kinds. Alignment
Checks, which compare a Build with the hydrofabric it came from, are not
covered.
