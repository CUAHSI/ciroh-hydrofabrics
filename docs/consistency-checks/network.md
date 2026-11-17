# `network` check

The `network` check measures how the features of a GeoPackage connect to each
other: duplicate keys, links that do not resolve, cycles, outlets, orphan
features, and the order of `hydroseq` values along the flowpath network. It
reads attributes only and does not load geometries.

The conventions it applies (keys, relationships, the terminal value and the
routing style) come from the `checks.network` section of the Data Model's
specification and are **v2.2 observations, not an exhaustive standard**. A new
Data Model declares its own; see
[adding a model](running-and-recording.md#adding-a-data-model). Metric names
that depend on the model's layer names (`flowpaths`, `nexus`, `network`,
`divides`) and columns (`id`, `toid`, `hydroseq`, `dnhydroseq`, `topo`) are
fixed in the implementation.

Every metric on this page is a **ratcheted count**: PASS when
`value <= recorded count`, FAIL otherwise. There are no INFO metrics. The
counts called *indeterminate* and *ambiguous* are ratcheted too, but they mean
"could not be evaluated", not "wrong". A metric whose required tables or
columns are missing is omitted (the `schema` check reports the missing
prerequisite). If no network metric applies at all, `no_applicable_checks` is
`1`, which is a FAIL against a recorded `0`.

## Routing conventions

| Convention | `ngen` (v2.2) | `reference` (v2.2) | Source |
| --- | --- | --- | --- |
| Routing style | `via_nexus`: flowpaths, divides and attribute tables point to a nexus; a nexus points to a flowpath | `direct`: flowpaths and network rows point to flowpaths in their own layer | Data Model specific (v2.2), `checks.network.routing.style` |
| Terminal value of `toid` | `wb-0` | `0` | Data Model specific (v2.2), `checks.network.routing.terminal_id` |
| Nexus outlet prefix and type | `tnx-` = `terminal`, `cnx-` = `coastal`, `inx-` = `internal` | none | Data Model specific (v2.2), `routing.outlet_types` |
| Network row label for a flowpath link | none | `topo = fl-fl` | Data Model specific (v2.2), `routing.link_label` |
| `hydroseq` order | Upstream `hydroseq` must be **greater** than downstream | the same | Generic: the implementation; it assumes the NHDPlus convention |

A **terminal sentinel** (`wb-0` or `0`) is never reported as a dangling link or
as a member of a cycle.

## Key and link metrics

| Metric | Applies to | What it measures |
| --- | --- | --- |
| `duplicate_primary_ids.<layer>` | See keys below | The number of **extra rows**, not groups: for each repeated non-null key, `count - 1`, summed. Three rows with the same ID add `2`. |
| `duplicate_network_rows` | both, when a `network` layer exists | Extra rows equal in **every column except `fid`** (including geometry, if any). NULLs group together and text is compared case-sensitively. Repeated IDs alone are not duplicates. |
| `indeterminate_null_toid.<layer>` | `ngen`: `flowpaths`, `divides`, `flowpath-attributes`, `flowpath-attributes-ml`, `nexus`, `network`. `reference`: `flowpaths`, `network` | The number of rows whose `toid` is NULL. They are reported separately and are **not** counted as dangling or as a terminal. |
| `dangling_toid.<layer>` | `ngen` and `reference`, see below | The number of non-null `toid` values that do not resolve (rows, not distinct values). |
| `cycle_nodes.<graph>` | `ngen`: `flowpaths_nexus`, `network`. `reference`: `flowpaths`, `network` | The number of distinct IDs that belong to a cycle, including a self-loop. Nodes that are only downstream of a cycle are not counted. |
| `terminal_convention.<layer>` | `ngen` only | Rows that break the outlet convention below. |

**Primary keys** for `duplicate_primary_ids` (from `checks.network.primary_ids`):

| Layer | `ngen` key | `reference` key |
| --- | --- | --- |
| `divides`, `divide-attributes` | `divide_id` | `divide_id` (`divides` only) |
| `flowpaths`, `nexus`, `flowpath-attributes`, `flowpath-attributes-ml` | `id` | `id` (`flowpaths` only) |
| `lakes` | `lake_id` | n/a |
| `pois` | `poi_id` | n/a |
| `hydrolocations` | none established | `hl_id` |

POI uniqueness is an observed convention, not a proven universal constraint.
The `network` table has many rows per ID and is excluded.

**`dangling_toid` resolves** as follows:

| Layer | A `toid` is dangling when it is not | Excluded |
| --- | --- | --- |
| `reference`: `flowpaths`, `network` | an `id` in the same layer | the terminal `0` |
| `ngen`: `flowpaths`, `divides`, `flowpath-attributes`, `flowpath-attributes-ml` | an `id` in `nexus` | the terminal `wb-0` |
| `ngen`: `nexus` | an `id` in `flowpaths` | the terminal `wb-0` |
| `ngen`: `network` | an `id` in `flowpaths`, `nexus` or `network` (all three must have an `id` column) | the terminal `wb-0` |

Links may cross a VPU boundary, so a selected VPU's subgraph can have dangling
links that resolve in the full product.

**Cycles** are strongly connected components found with Tarjan's algorithm on
the `id` to `toid` edges. The `ngen` `flowpaths_nexus` graph joins the
flowpath and nexus layers. Duplicate edges are collapsed; when an ID is
repeated with different targets, all its edges are kept, so a cycle in that
union may be partly an artefact of the duplicates. The graph must fit in
memory.

**`terminal_convention`** (NextGen). A nexus-routed layer should point to a
nexus even at an outlet, so:

- for `flowpaths`, `divides`, `flowpath-attributes` and
  `flowpath-attributes-ml`, the value is the number of rows with `toid = wb-0`
  (a direct reference to the terminal);
- for `nexus` and `network`, the value is the number of outlet-like rows that
  break the convention. A row is outlet-like when its `toid` is `wb-0`, its ID
  starts with `tnx-`, `cnx-` or `inx-`, or its `type` is `terminal`, `coastal`
  or `internal`. It conforms only when the ID prefix implies a type, the
  row's `type` equals that type, **and** `toid = wb-0`. For `network`, only
  rows whose ID begins with a nexus-like prefix (`nex-`, `tnx-`, `cnx-`, `inx-`)
  or whose `toid` is `wb-0` are examined.

These conventions come from sampled products, not an exhaustive specification.

## Orphan and reciprocal metrics

An orphan metric counts **rows of a source layer** whose key is NULL or has no
match in the target layer. Duplicates in the target do not multiply counts.
Where the relationship names a flag column, a companion metric
`<name>.<flag>_0` counts the orphans whose flag is `0`.

| Metric | Source key | Target key | Flag | Applies to |
| --- | --- | --- | --- | --- |
| `divides_without_flowpaths` | `divides.id` | `flowpaths.id` | `has_flowline` | both |
| `divides_without_referencing_flowpaths` | `divides.divide_id` | `flowpaths.divide_id` | `has_flowline` | both |
| `flowpaths_without_divides` | `flowpaths.divide_id` | `divides.divide_id` | `has_divide` | both |
| `divides_without_attributes` | `divides.divide_id` | `divide-attributes.divide_id` | `has_flowline` | `ngen` |
| `hydrolocations_without_nexus` | `hydrolocations.nex_id` | `nexus.id` | none | `ngen` |

The companion metrics are therefore `divides_without_flowpaths.has_flowline_0`,
`divides_without_referencing_flowpaths.has_flowline_0`,
`flowpaths_without_divides.has_divide_0` and
`divides_without_attributes.has_flowline_0`. A divide with `has_flowline = 0`
or a flowpath with `has_divide = 0` is expected to be an orphan in some cases,
such as coastal features, so the subset says how many orphans are *flagged* as
having no counterpart. Both counts are compared with their own recorded limits.

`reciprocal_divide_flowpath_mismatches` and
`reciprocal_divide_flowpath_ambiguous` test the two-way link between divides
and flowpaths. A divide names its flowpath in `divides.id`; a flowpath names
its divide in `flowpaths.divide_id`. For each directed source row whose
counterpart resolves uniquely, the mismatch count increases when that
counterpart points back at a **different** existing source. The `_ambiguous`
metric counts rows that involve duplicate keys, and nothing is selected from a
duplicate. Missing and NULL links are left to the orphan metrics, and one
inconsistent pair can count in both directions.

## Hydrosequence metrics

`hydroseq` increases going upstream, so a flowpath's `hydroseq` must be
**greater** than its downstream flowpath's. Each family below has three
companions: the **violation or mismatch** count, an **`_indeterminate`** count
(the link or a value could not be resolved or compared) and an **`_ambiguous`**
count (duplicate IDs or conflicting values, so no row could be chosen). When
an edge is both ambiguous and unresolved, it is counted as ambiguous. Edge
checks exclude terminal links.

| Family | Applies to | What it counts |
| --- | --- | --- |
| `hydroseq_order_{violations,indeterminate,ambiguous}.flowpaths` | both | A resolved nonterminal edge violates when the upstream `hydroseq` is not greater than the downstream one. |
| `dnhydroseq_{mismatches,indeterminate,ambiguous}.flowpaths` | `reference` only | A mismatch is a flowpath whose `dnhydroseq` differs from the `hydroseq` of the flowpath its `toid` points to. NextGen has no `dnhydroseq` column. |
| `hydroseq_order_{violations,indeterminate,ambiguous}.network` | both | The same order test on network rows. `reference` rows with `topo = fl-fl` are compared with the downstream flowpath; rows with any other label are indeterminate. `ngen` follows network nexus rows to network flowpath rows. |
| `dnhydroseq_{mismatches,indeterminate,ambiguous}.network` | `reference` only | As for the flowpaths, for network rows. |
| `hydroseq_{mismatches,comparison_indeterminate,comparison_ambiguous}.network` | `ngen` only | A mismatch is a network flowpath row whose `hydroseq` differs from the `flowpaths` layer value for the same ID, including terminal rows. |

In `ngen`, a flowpath resolves through `nexus`. A repeated nexus destination
resolves only if every row agrees; conflicting values are ambiguous. Network
nexus rows themselves have no flowpath sequence to compare, and a valid
coastal or internal outlet missing from the network table is indeterminate. In
`reference`, the `network` table has many rows per ID, so counts are rows, not
distinct features.

Official NextGen VPUs contain ordering violations, so review this check before
enabling a blocking gate.

## Pass and fail

Every metric passes when `value <= recorded count` and fails when
`value > recorded count`. What a value of `0` says, and so what a FAIL adds to
the recorded limit, depends on the family:

| Metric family | A value of `0` means | Each unit above the limit is |
| --- | --- | --- |
| `duplicate_primary_ids.*`, `duplicate_network_rows` | no repeated keys or rows | one more extra row |
| `indeterminate_null_toid.*` | no NULL `toid` | one more row with a NULL `toid` |
| `dangling_toid.*` | every non-terminal `toid` resolves | one more unresolved link |
| `cycle_nodes.*` | no cycles | one more ID inside a cycle |
| `terminal_convention.*` | outlets follow the convention | one more nonconforming row |
| orphan metrics and their `.has_*_0` subsets | every row has a counterpart | one more orphan row |
| `reciprocal_*_mismatches` | every resolved link points back | one more directed row pointing elsewhere |
| `hydroseq_order_violations.*`, `*_mismatches.*` | the sequence values are consistent | one more inconsistent edge or row |
| `*_indeterminate.*`, `*_ambiguous.*` | every edge or row could be compared | one more edge or row that could not be assessed |
| `no_applicable_checks` | at least one metric applied | n/a (the value is `1` when no metric applied) |

A metric omitted for missing columns or tables is not printed at all, and is
neither a PASS nor a FAIL. There are no INFO lines in this check. A nonzero
`_indeterminate` or `_ambiguous` value is a FAIL against a limit of `0`, but it
says the rows could not be assessed, not that they violate the convention.

## Worked examples

All examples are NextGen unless stated, run with no recorded counts and the
network check advisory, and show only the relevant report lines. Every
GeoPackage here is deliberately tiny.

### Dangling link and duplicate nexus

| Layer | Rows (`id` → `toid`) |
| --- | --- |
| `flowpaths` | `wb-1` → `nex-1`; `wb-2` → `tnx-1`; `wb-3` → `nex-9` |
| `nexus` | `nex-1` → `wb-2` (twice); `tnx-1` → `wb-0` (type `terminal`) |

```text
network | duplicate_primary_ids.nexus | 1 | 0 | FAIL | advisory
network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory
network | dangling_toid.nexus | 0 | 0 | PASS | advisory
network | cycle_nodes.flowpaths_nexus | 0 | 0 | PASS | advisory
network | terminal_convention.flowpaths | 0 | 0 | PASS | advisory
network | terminal_convention.nexus | 0 | 0 | PASS | advisory
```

- `nex-1` appears twice, so `duplicate_primary_ids.nexus` is `1` (one extra
  row).
- `wb-3` points to `nex-9`, which is not in `nexus`, so
  `dangling_toid.flowpaths` is `1`. `wb-2` points to the existing `tnx-1`.
- `tnx-1` has the `terminal` type, the `tnx-` prefix and `toid = wb-0`, so it
  follows the convention and `terminal_convention.nexus` is `0`.

The same run also reports `hydroseq_order_indeterminate.flowpaths = 1` (the
unresolved `wb-3`) and `hydroseq_order_ambiguous.flowpaths = 1` (`wb-1`, whose
nexus is duplicated).

If `counts.yaml` records `dangling_toid.flowpaths: 1` for this Data Model,
output kind and VPU, the dangling line becomes `1 | 1 | PASS`; the duplicate
nexus line is still a FAIL until its own count is recorded.

### Hydrosequence order

`wb-1` (`hydroseq` 10) flows through `nex-1` to `wb-2` (`hydroseq` 20), which
flows through `tnx-1` to `wb-0`.

```text
network | dangling_toid.flowpaths | 0 | 0 | PASS | advisory
network | hydroseq_order_violations.flowpaths | 1 | 0 | FAIL | advisory
network | hydroseq_order_indeterminate.flowpaths | 0 | 0 | PASS | advisory
network | hydroseq_order_ambiguous.flowpaths | 0 | 0 | PASS | advisory
```

The upstream `10` is not greater than the downstream `20`, so the edge is one
violation. With `hydroseq` values 30 and 20 instead, the violation count is `0`.

### Cycle

`wb-4` → `nex-4`; `nex-4` → `wb-5`; `wb-5` → `nex-5`; `nex-5` → `wb-4`.

```text
network | dangling_toid.flowpaths | 0 | 0 | PASS | advisory
network | dangling_toid.nexus | 0 | 0 | PASS | advisory
network | cycle_nodes.flowpaths_nexus | 4 | 0 | FAIL | advisory
```

All links resolve, yet the four IDs form a cycle, so `cycle_nodes` counts
`wb-4`, `nex-4`, `wb-5` and `nex-5`.

### Orphan divides and flowpaths

| Layer | Rows |
| --- | --- |
| `divides` | `cat-1` (`id` `wb-1`, `has_flowline` 1); `cat-2` (`wb-2`, 0); `cat-3` (`wb-3`, 1) |
| `flowpaths` | `wb-1` (`divide_id` `cat-1`, `has_divide` 1); `wb-3` (`cat-3`, 1); `wb-9` (`cat-9`, 1) |

```text
network | divides_without_flowpaths | 1 | 0 | FAIL | advisory
network | divides_without_flowpaths.has_flowline_0 | 1 | 0 | FAIL | advisory
network | divides_without_referencing_flowpaths | 1 | 0 | FAIL | advisory
network | divides_without_referencing_flowpaths.has_flowline_0 | 1 | 0 | FAIL | advisory
network | flowpaths_without_divides | 1 | 0 | FAIL | advisory
network | flowpaths_without_divides.has_divide_0 | 0 | 0 | PASS | advisory
network | reciprocal_divide_flowpath_mismatches | 0 | 0 | PASS | advisory
network | reciprocal_divide_flowpath_ambiguous | 0 | 0 | PASS | advisory
```

`cat-2` / `wb-2` has no flowpath, and its `has_flowline = 0` places it in the
`.has_flowline_0` subset, so the count and its subset both equal `1`. `wb-9`
points at `cat-9`, which is not a divide, and its `has_divide` is `1`, so the
subset `flowpaths_without_divides.has_divide_0` is `0`. A divide or flowpath
that is an orphan by design (`has_flowline = 0`) raises both counts; the
recorded limits for official products already include those.

### Reference product

`reference` flowpaths `1` → `2`, `2` → `0` (terminal) and `3` → `99`, with
`hydroseq` 30, 20 and 10 and `dnhydroseq` 20, 0 and 5.

```text
network | dangling_toid.flowpaths | 1 | 0 | FAIL | advisory
network | hydroseq_order_violations.flowpaths | 0 | 0 | PASS | advisory
network | hydroseq_order_indeterminate.flowpaths | 1 | 0 | FAIL | advisory
network | hydroseq_order_ambiguous.flowpaths | 0 | 0 | PASS | advisory
network | dnhydroseq_mismatches.flowpaths | 0 | 0 | PASS | advisory
network | dnhydroseq_indeterminate.flowpaths | 1 | 0 | FAIL | advisory
network | dnhydroseq_ambiguous.flowpaths | 0 | 0 | PASS | advisory
```

- Flowpath `2` points to the terminal `0`, so it is neither dangling nor
  compared.
- Flowpath `3` points to `99`, which does not exist: one dangling link, and
  because it cannot be resolved, one indeterminate `hydroseq` order and one
  indeterminate `dnhydroseq` comparison.
- Flowpath `1` has `hydroseq` 30 greater than `2`'s 20 and `dnhydroseq` 20 equal
  to `2`'s `hydroseq`, so there is no violation and no mismatch.
