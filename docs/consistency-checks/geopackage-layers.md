# `geopackage_layers` check

A basic sanity check that the file contains layers and that they are not empty.
It is Data Model independent: it does not read a specification.

| Metric | Result type | What it measures |
| --- | --- | --- |
| `missing_layers` | PASS/FAIL | `1` if the GeoPackage has no layers at all, otherwise `0`. |
| `empty_layers` | PASS/FAIL | The number of layers that have zero features (rows). |

## How they are calculated

The check lists the layers GDAL/OGR reports for the GeoPackage (through
`pyogrio.list_layers`, which includes feature and attribute tables) and reads
each layer's feature count. `missing_layers` is `1` when the list is empty.
`empty_layers` is the number of layers whose feature count is `0`; an empty
layer is not necessarily wrong.

## Pass and fail

| Metric | Passes when | Fails when |
| --- | --- | --- |
| `missing_layers` | `0 <= recorded count`: the file has at least one layer. | `1 > recorded count`: the file has no layers. |
| `empty_layers` | The count of empty layers is no greater than the recorded count. | There are more empty layers than recorded. |

There are no INFO metrics and no incomplete cases specific to this check.
Together with `schema`, a file with no layers also reports every layer as
missing. The checked-in counts record `0` for both metrics in every official
VPU.

## Worked example

A GeoPackage has two layers: `nexus` with one feature and `lakes` with none.

```text
geopackage_layers | missing_layers | 0 | 0 | PASS | advisory
geopackage_layers | empty_layers | 1 | 0 | FAIL | advisory
```

`lakes` has no features, so `empty_layers` is `1`. No count is recorded, so the
limit is `0` and the line is a FAIL. If `lakes` is legitimately empty in the
official product, `counts.yaml` records `empty_layers: 1` and the same file
reports:

```text
geopackage_layers | empty_layers | 1 | 1 | PASS | advisory
```
