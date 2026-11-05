# Consistency Checks start advisory and gate with a count ratchet, not zero tolerance

A strict, zero-tolerance Consistency Check gate would fail every Contribution: the Official Hydrofabrics themselves fail strict checks (e.g. the official NextGen v2.2 VPU 16 has 6 duplicate nexus IDs and divide overlaps up to 11.7 km²), and while the project is still recreating the official products, its own pipeline's Builds are worse than the official ones on many checks. We therefore (1) report each check as a violation count for a single GeoPackage, (2) compare it with checked-in counts recorded from the Official Hydrofabric for the same Data Model, output kind and VPU (the NOAA OWP Reference Hydrofabric for Community Reference Hydrofabrics, the NOAA OWP NextGen Hydrofabric for Community NextGen Hydrofabrics), and (3) treat a count above its recorded limit as a failure. Contributions may carry the official product's errors forward but must not add more; a Contribution that lowers a count updates the recorded counts, so they only ever fall.

For now, the checks are advisory: they run on every PR and report to the reviewer (required-to-run), but a failure does not block the merge. They become blocking (required-to-pass) when CUAHSI maintainers decide to switch them on; there is no automatic criterion. This reverses the required-to-pass decision in CAM-1560 because the project's own recreation PRs must stay mergeable while the pipeline is worse than the official products.

## Considered Options

- **Zero tolerance**: rejected; it blocks all Contributions until the pipeline and the official products' inherited errors are fixed.
- **Counts seeded from the project's own Build**: rejected; it would accept pipeline defects (e.g. 260,278 duplicate network rows) as the limit.
- **Live base comparison** (download and check the base in CI on every PR): rejected; doubles CI cost and still needs a rule for which product is the base.
- **Per-feature ratchet** ("no new violating features", matched by ID): rejected for Consistency Checks; it depends on ID stability across Builds, which makes it an Alignment Check (CAM-1573). A count ratchet can hide a fix in one place that offsets a new error elsewhere; Alignment Checks and the reviewer cover that case.
- **Blocking from day one, with a maintainer override label**: rejected for now in favour of advisory mode; recreation PRs would need routine overrides.

## Consequences

- A Consistency Check stays a check of one Build against itself and its declared Data Model; the "no increase" rule belongs to Contribution Review, not to the check.
- Checks with no recorded count (e.g. cycles, or a VPU not yet in the official resource) are held to zero.
- Until the switch, a Contribution can merge with failing Consistency Checks; the reviewer is responsible for judging them.
- The switch is a per-check `blocking` flag in a checked-in config, all `false` at first. Maintainers turn checks on one at a time in a reviewed PR, so git history records when and why. The workflow is a required status check from day one; it fails only when a `blocking` check exceeds its recorded count.
