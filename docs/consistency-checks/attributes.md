# `attributes` check

The `attributes` check tests numeric attribute values against the rules in the
Data Model's specification: positive areas and lengths, physically plausible
ranges, and agreement between a flowpath's length in two tables. It reads the
GeoPackage read-only and does not download or compare with a reference product.

The rules are declared in the specification,
[`ngen.json`](../../validation/consistency/models/v2.2/ngen.json) or
[`reference.json`](../../validation/consistency/models/v2.2/reference.json), and
are **assumptions requested in CAM-1602**, not universal physical
laws or promises that the official products satisfy them. They do not compare
attribute distributions. A rule is applied to the output kinds that declare it.

## Rules

Each rule has an ID (`<table>.<column>_<kind>`) that appears in the metric
names. A rule's value is **in range** when it satisfies the condition, and a
**violation** otherwise.

### Both output kinds

| Rule ID | Condition | Applies when | v2.2 source |
| --- | --- | --- | --- |
| `divides.areasqkm_positive` | `areasqkm > 0` | every row | CAM-1602 (user-supplied) |
| `flowpaths.lengthkm_positive` | `lengthkm > 0` | every row | CAM-1602 |
| `flowpaths.areasqkm_positive_with_divide` | `areasqkm > 0` | `has_divide` is the integer `1` | CAM-1602 |

`has_divide = 0` means the area rule does not apply to that row; a NULL or
non-boolean `has_divide` makes applicability *indeterminate* (INFO), not a
violation. A flowpath without a divide legitimately has zero area, and a
non-null `divide_id` is not a substitute for the flag.

### NextGen only

| Rule ID | Condition | Source |
| --- | --- | --- |
| `flowpath-attributes.Length_m_positive`, `flowpath-attributes-ml.Length_m_positive` | `Length_m > 0` | CAM-1602 |
| `*.So_nonnegative` | `So >= 0` | CAM-1602 |
| `*.n_range` | `0 < n <= 1` | CAM-1602 |
| `*.MusX_range` | `0 <= MusX <= 0.5` | CAM-1602 |
| `*.length_consistency` | `abs(Length_m - lengthkm * 1000) <= 1` metre; see below | CAM-1602 |
| `divide-attributes.mean.impervious_range` | `0 <= mean.impervious <= 100` percent | NOAA OWP v2.2 data model; endpoints adapted from OWP `validate_hf` |
| `divide-attributes.mean.slope_range` | `0 <= mean.slope <= 90` degrees | `ngen-workflow/R/vaa.r`; endpoints adapted from OWP `validate_hf` and Lynker `hfutils` |
| `divide-attributes.mean.slope_1km_range` | `0 <= mean.slope_1km <= 1` | NWM soil-bottom drainage factor, dimensionless |
| `divide-attributes.mean.smcmax_soil_layers_stag=<1..4>_range` | `0 <= value <= 1` | volumetric saturated soil moisture (volume fraction) |
| `divide-attributes.mean.smcwlt_soil_layers_stag=<1..4>_range` | `0 <= value <= 1` | volumetric soil moisture at wilting point (volume fraction) |

The `*` rows apply to both the `flowpath-attributes` and the
`flowpath-attributes-ml` tables; each is compared separately with `flowpaths`.
The source column cites each rule's origin as recorded in the specification;
see [the v2.2 Data Model](data-model-v2.2.md) for the discussion and links.

The bounds are not claims that every value within them is realistic, or that
values agree across soil layers.

### Thresholds and conventions

| Item | v2.2 value | Source and scope |
| --- | --- | --- |
| Length tolerance | 1 metre, absolute | Data Model specific (v2.2): `max_absolute_difference` in the NextGen `length_consistency` rules (CAM-1602). |
| Length unit scale | `lengthkm * 1000` | Data Model specific (v2.2): `right.scale` of the rule. |
| Roundoff allowance at the tolerance boundary | the smallest of 1e-9 m, one-billionth of the tolerance, and four machine epsilons times the larger operand | Generic: the implementation. It makes the inclusive boundary stable; a zero tolerance has no allowance. |
| Sentinel candidate | `-9998` | Data Model specific (v2.2): the `sentinel_handling` list in the specification. Its meaning is **undetermined**. |
| Join key for length comparison | `id` (text), exact bytes | Data Model specific (v2.2): the rule's `join`. |

## Metrics

### Ratcheted (PASS/FAIL)

| Metric | What it counts |
| --- | --- |
| `violations.<rule ID>` | Rows whose finite numeric value is outside an applicable rule. For `length_consistency`, the uniquely matched `id` pairs outside the tolerance. |
| `invalid_numeric.<table>.<column>` | Non-NULL operand values of a rule column that are not finite SQLite `integer` or `real` values: text, infinities, and detectable NaN. Numeric text is not converted. These are separate from violations. |
| `sentinel.<table>.<column>` | Occurrences of a sentinel candidate (`-9998`) in a present Data Model column declared numeric or BOOLEAN, stored as a number. Text values are not recognized. A sentinel is **also** evaluated by any rule that applies to the column, so one value can count as a violation too. The column does not have to have a rule. |
| `nonfinite_calculation.<rule ID>` | Uniquely matched length pairs whose scaled difference is not finite; reported apart from tolerance violations. |
| `no_applicable_checks` | `1` if **no** rule could be evaluated; `0` is not printed. |

### INFO (never affects the gate)

| Metric | What it counts or lists |
| --- | --- |
| `indeterminate_null.<table>.<column>` | NULL operands of a rule column (SQLite may expose NaN as NULL). They are not violations: how to treat NULLs is undetermined. |
| `indeterminate_applicability.<rule ID>` | Rows of a conditional rule whose flag (`has_divide`) is NULL or non-boolean, so the rule's applicability cannot be decided. |
| `not_evaluated.<rule ID>` | `1` when the rule could not be evaluated because a table, operand column, join key or flag is missing; the `schema` check reports the missing prerequisite. |
| `not_checked.<table>.<column>` | `1` for each column in the specification that has **no** range or interval rule. It is an inventory, even if the column is absent: it does not say the column is valid, present, or covered by another check. |
| `compared_pairs.<rule ID>` | Length pairs actually compared, excluding nonfinite and precision-indeterminate pairs. |
| `indeterminate_operands.<rule ID>` | Uniquely matched pairs with a NULL or invalid operand. |
| `indeterminate_precision.<rule ID>` | Finite pairs that cannot be compared reliably without losing precision. |
| `indeterminate_duplicate_keys.<rule ID>` | Distinct `id` values duplicated on either side, including unmatched ones. No row is chosen and no Cartesian join is counted. |
| `unmatched_left_rows.<rule ID>`, `unmatched_right_rows.<rule ID>` | Rows with a non-NULL `id` that is missing from the other side. Left is the attribute table, right is `flowpaths`. |
| `null_join_key_left_rows.<rule ID>`, `null_join_key_right_rows.<rule ID>` | Rows with a NULL `id`. |
| `invalid_join_key_left_rows.<rule ID>`, `invalid_join_key_right_rows.<rule ID>` | Rows whose `id` is not text. |

`not_checked` and `not_evaluated` are two different kinds of "was not checked":
`not_checked` is a column with no rule at all, and `not_evaluated` is a rule that
exists but whose inputs are missing. A zero `violations` count does not
establish coverage: a rule can be evaluated while few or no rows can be
compared, so read `compared_pairs` and the INFO counts too.

## Length consistency

`length_consistency` compares each attribute table's `Length_m` with
`flowpaths.lengthkm * 1000`. A pair is compared when its text `id` occurs
**once on each side** and both operands are finite numbers. The pair is a
violation when the absolute difference is greater than 1 metre.

Duplicate IDs are never resolved by choosing a row or counting every pairing,
because the right way to compare duplicates is undetermined; the official
attribute tables do contain duplicate IDs. They are reported as
`indeterminate_duplicate_keys` (INFO) and are left out of `violations`.

## Pass and fail

| Result | Metrics | Condition |
| --- | --- | --- |
| PASS | `violations.*`, `invalid_numeric.*`, `sentinel.*`, `nonfinite_calculation.*`, `no_applicable_checks` | `value <= recorded count` (a missing count is `0`) |
| FAIL | the same | `value > recorded count` |
| INFO | `indeterminate_*`, `not_evaluated.*`, `not_checked.*`, `compared_pairs.*`, `unmatched_*`, `null_join_key_*`, `invalid_join_key_*` | always; never gated |

A nonzero ratcheted count is a FAIL against a limit of `0` even while the check
is advisory, and affects the exit status only when the check is blocking.
Review the assumptions, the INFO counts and the product-specific counts before
enabling blocking.

## Worked examples

### NextGen: ranges, a sentinel and length consistency

`flowpaths` has four rows. `flowpath-attributes` has the same four IDs.

| `id` | `lengthkm` | `areasqkm` | `has_divide` | `Length_m` | `n` |
| --- | --- | --- | --- | --- | --- |
| `wb-1` | 1.0 | 2.0 | 1 | 1000.8 | 0.05 |
| `wb-2` | 1.0 | 2.0 | 1 | 1001.5 | 1.2 |
| `wb-3` | 1.0 | 0.0 | 0 | -9998 | 0.05 |
| `wb-4` | NULL | 2.0 | 1 | 500 | 0.05 |

With `So = 0.01` and `MusX = 0.2` everywhere and no recorded counts:

```text
attributes | sentinel.flowpath-attributes.Length_m | 1 | 0 | FAIL | advisory
attributes | violations.flowpaths.lengthkm_positive | 0 | 0 | PASS | advisory
attributes | violations.flowpaths.areasqkm_positive_with_divide | 0 | 0 | PASS | advisory
attributes | violations.flowpath-attributes.Length_m_positive | 1 | 0 | FAIL | advisory
attributes | violations.flowpath-attributes.So_nonnegative | 0 | 0 | PASS | advisory
attributes | violations.flowpath-attributes.n_range | 1 | 0 | FAIL | advisory
attributes | violations.flowpath-attributes.MusX_range | 0 | 0 | PASS | advisory
attributes | violations.flowpath-attributes.length_consistency | 2 | 0 | FAIL | advisory
attributes | indeterminate_null.flowpaths.lengthkm | 1 | - | INFO | advisory
attributes | compared_pairs.flowpath-attributes.length_consistency | 3 | - | INFO | advisory
attributes | indeterminate_operands.flowpath-attributes.length_consistency | 1 | - | INFO | advisory
```

- `wb-3` has `areasqkm` 0, but `has_divide` is `0`, so the area rule does not
  apply and `areasqkm_positive_with_divide` is `0`.
- `-9998` is a sentinel candidate (`sentinel...Length_m` is `1`). It is also not
  positive, so it counts under `Length_m_positive` as well.
- `n = 1.2` on `wb-2` is above 1, so `n_range` is `1`.
- For `length_consistency`, `lengthkm * 1000` is 1000 m. `wb-1` differs by 0.8 m
  (within the 1 m tolerance), `wb-2` by 1.5 m (a violation), and `wb-3` by
  10998 m (a violation): `2` violations. `wb-4` has no finite `lengthkm`, so it
  is not compared: `indeterminate_operands` is `1` and `compared_pairs` is `3`.

### NextGen: duplicate attribute IDs

`flowpaths` has `wb-1` once (`lengthkm` 1.0), and `flowpath-attributes` has
`wb-1` twice with `Length_m` 1000 and 5000.

```text
attributes | violations.flowpath-attributes.length_consistency | 0 | 0 | PASS | advisory
attributes | indeterminate_duplicate_keys.flowpath-attributes.length_consistency | 1 | - | INFO | advisory
attributes | compared_pairs.flowpath-attributes.length_consistency | 0 | - | INFO | advisory
```

The check cannot tell which `wb-1` row is right, so it neither passes nor fails
either one: the pair is **not compared**, and the value `0` for `violations`
reflects no comparison rather than agreement.

### Reference: positive length and area

`flowpaths` has two rows: id `1` (`lengthkm` 0, `areasqkm` 3, `has_divide` 1)
and id `2` (`lengthkm` 1.5, `areasqkm` 0, `has_divide` 0).

```text
attributes | violations.flowpaths.lengthkm_positive | 1 | 0 | FAIL | advisory
attributes | violations.flowpaths.areasqkm_positive_with_divide | 0 | 0 | PASS | advisory
attributes | indeterminate_applicability.flowpaths.areasqkm_positive_with_divide | 0 | - | INFO | advisory
```

Flowpath `1` has zero length, so one violation. Flowpath `2` has zero area, but
`has_divide = 0` makes the rule inapplicable. The reference specification has
just three rules: these two and `divides.areasqkm_positive`, which the same run
reports as `not_evaluated.divides.areasqkm_positive | 1 | - | INFO` because the
example has no `divides` layer.
