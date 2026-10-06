#!/usr/bin/env python3
"""
Assemble the pull request comment from the comparison reports.

Inputs:
    --parsed        JSON produced by parse_pr_body.py
    --reports-dir   directory holding <type>/<version>/<vpu>/report.md files
    --run-url       link to the workflow run (used if there is no artifact link)
    --artifact-url  link that downloads the report artifact (optional)
    --output        file to write the comment markdown to

The comment is a short summary: the report's header details plus its Schema
and Layers tables. Everything else in report.md (the attribute and geometry
difference tables, which have one row per difference) is left to the
artifact, so the comment stays small and quick to scan.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

# Hidden marker used by the workflow to find and update its own comment.
MARKER = "<!-- hf-comparison-report -->"

REPORT_TITLES = {
    "reference_hydrofabric": "Reference hydrofabric",
    "ngen_hydrofabric": "Ngen hydrofabric",
}

# Report sections shown in the comment; all other "## " sections are dropped.
KEPT_SECTIONS = ("Schema", "Layers")

# The overall MATCH / DIFFERENCES FOUND line is not shown in the comment.
# Other results (e.g. COMPARISON NOT PERFORMED) are kept because they explain
# why there are no tables.
HIDDEN_RESULT_LINES = ("**Result:** DIFFERENCES FOUND", "**Result:** MATCH")


def summarize_report(markdown: str) -> str:
    """Reduce a report.md to its header details and the Schema and Layers sections.

    The report's own title is dropped, and kept section headings are nested
    under the comment's heading for that hydrofabric type.
    """
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]

    kept = []
    keep = True  # the text before the first "## " heading holds the header details
    for line in lines:
        if line.startswith("## "):
            keep = line[3:].strip() in KEPT_SECTIONS
            if keep:
                kept.append("##" + line)
            continue
        if keep and line.strip() not in HIDDEN_RESULT_LINES:
            kept.append(line)

    # Dropping lines can leave runs of blank lines; collapse them.
    cleaned = []
    for line in kept:
        if line == "" and cleaned and cleaned[-1] == "":
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def find_report(reports_dir: Path, remote_type: str) -> Path | None:
    """Return the report.md for one hydrofabric type, or None if it was not produced."""
    matches = sorted((reports_dir / remote_type).glob("*/*/report.md"))
    return matches[0] if matches else None


def build_comment(parsed: dict, reports_dir: Path, run_url: str, artifact_url: str) -> str:
    created = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    parts = [MARKER, "## Hydrofabric comparison", "", f"_Created: {created}_", ""]

    if parsed["errors"]:
        parts.append("The PR description has problems, so some comparisons were skipped:")
        parts.extend(f"- {error}" for error in parsed["errors"])
        parts.append("")

    if not parsed["has_inputs"]:
        parts.append(
            "No hydrofabric URLs were provided in the PR description, so no comparison was run. "
            "To request one, fill in the **Hydrofabric comparison** section and edit the description."
        )
        return "\n".join(parts)

    found = 0
    for remote_type, title in REPORT_TITLES.items():
        report = find_report(reports_dir, remote_type)
        if report:
            found += 1
            parts.extend([f"### {title}", "", summarize_report(report.read_text()), ""])

    if not found:
        parts.append("The comparison did not produce a report. See the workflow log for details.")
        return "\n".join(parts)

    link = artifact_url or run_url
    parts.extend([
        "---",
        "The full report includes additional information, such as attribute and geometry "
        f"differences, and can be downloaded [here]({link}).",
    ])
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the PR comment from comparison reports.")
    parser.add_argument("--parsed", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--artifact-url", default="")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    parsed = json.loads(args.parsed.read_text())
    args.output.write_text(build_comment(parsed, args.reports_dir, args.run_url, args.artifact_url))


if __name__ == "__main__":
    main()
