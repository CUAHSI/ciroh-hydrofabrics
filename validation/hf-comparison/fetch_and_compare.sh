#!/usr/bin/env bash
#
# Download one user-supplied GeoPackage (or a .zip containing one) and compare
# it against the official hydrofabric using compare_hydrofabric.py.
#
# Usage:
#   fetch_and_compare.sh <reference_hydrofabric|ngen_hydrofabric> <url> <version> <vpu>
#
# This is a comparison aid for PR review, not a gate: if the download or the
# comparison fails, a report.md describing the problem is written instead and
# the script still exits 0. `python` must have the geospatial dependencies:
# run it through `pixi run` locally; CI installs requirements.txt with pip.

set -uo pipefail

type="$1"
url="$2"
version="$3"
vpu="$4"

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
report_dir="${here}/reports/${type}/${version}/${vpu}"
work_dir="$(mktemp -d)" || { echo "Could not create a temporary directory" >&2; exit 1; }
trap 'rm -rf "${work_dir}"' EXIT

# Write a report.md that explains why no comparison could be produced.
write_error_report() {
  mkdir -p "${report_dir}"
  {
    echo "# Hydrofabric Comparison Report"
    echo
    echo "- **Hydrofabric type:** ${type}"
    echo "- **Version:** ${version}"
    echo "- **VPU:** ${vpu}"
    echo
    echo "**Result:** COMPARISON NOT PERFORMED"
    echo
    echo "$1"
  } > "${report_dir}/report.md"
  echo "$1" >&2
}

# Download over https only (no redirects to other protocols), with size and
# time limits since the URL comes from a PR description.
download="${work_dir}/download"
if ! curl --fail --silent --show-error --location \
    --proto '=https' --proto-redir '=https' \
    --max-filesize 3000000000 --max-time 1800 \
    --output "${download}" "${url}"; then
  write_error_report "Could not download \`${url}\`. Check that the HydroShare resource is public and the link is a direct file link."
  exit 0
fi

# Unwrap a zip so the comparison always receives a .gpkg. `-j` flattens paths,
# so nothing in the archive can be written outside the work directory.
gpkg="${download}"
if [[ "$(echo "${url}" | tr '[:upper:]' '[:lower:]')" == *.zip ]]; then
  if ! unzip -q -j "${download}" '*.gpkg' -d "${work_dir}/unzipped"; then
    write_error_report "The zip file at \`${url}\` could not be extracted or contains no \`.gpkg\` file."
    exit 0
  fi
  gpkg="$(find "${work_dir}/unzipped" -name '*.gpkg' | head -n 1)"
fi

# Compare. Differences are expected in a PR, so --fail-on-diff is not used.
if ! python "${here}/compare_hydrofabric.py" "${gpkg}" \
    --remote-hydrofabric-type "${type}" \
    --version "${version}" \
    --vpu "${vpu}"; then
  write_error_report "The comparison failed to run for \`${url}\`. See the workflow log for details (the version/VPU may not be configured in \`reference_sources.yaml\`, or the file may not be a valid hydrofabric GeoPackage)."
fi
exit 0
