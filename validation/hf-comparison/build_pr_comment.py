#!/usr/bin/env python3
"""
Assemble the pull request comment from the comparison reports.

Inputs:
    --parsed       JSON produced by parse_pr_body.py
    --reports-dir  directory holding <type>/<version>/<vpu>/report.md files
    --run-url      link to the workflow run, where the full reports are attached
    --output       file to write the comment markdown to

GitHub rejects comments over 65,536 characters, and the difference tables in
a report have one row per difference, so each report is cut at a line
boundary to fit and a pointer to the full report artifact is added.
"""

import argparse
import json
from pathlib import Path

# Hidden marker used by the workflow to find and update its own comment.
MARKER = "<!-- hf-comparison-report -->"

# GitHub's limit is 65,536; leave headroom for headings and notes.
MAX_COMMENT_CHARS = 60000

REPORT_TITLES = {
    "reference_hydrofabric": "Reference hydrofabric",
    "ngen_hydrofabric": "Ngen hydrofabric",
}


def demote_headings(markdown: str) -> str:
    """Drop the report's own title and push its other headings down one level,
    so they nest under the comment's heading for that hydrofabric type."""
    lines = markdown.splitlines()
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join((("#" + line) if line.startswith("#") else line) for line in lines).strip()


def truncate_at_line(text: str, limit: int, note: str) -> str:
    """Cut text to at most `limit` characters on a line boundary, adding `note` if cut."""
    if len(text) <= limit:
        return text
    kept = text[: max(limit - len(note) - 2, 0)]
    kept = kept.rsplit("\n", 1)[0]
    return f"{kept}\n\n{note}"


def find_report(reports_dir: Path, remote_type: str) -> Path | None:
    """Return the report.md for one hydrofabric type, or None if it was not produced."""
    matches = sorted((reports_dir / remote_type).glob("*/*/report.md"))
    return matches[0] if matches else None


def build_comment(parsed: dict, reports_dir: Path, run_url: str) -> str:
    parts = [MARKER, "## Hydrofabric comparison", ""]

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

    reports = []
    for remote_type, title in REPORT_TITLES.items():
        report = find_report(reports_dir, remote_type)
        if report:
            reports.append((title, report))

    full_report_note = f"_Showing the first part of this report. The full report is in the [workflow artifacts]({run_url})._"
    footer = f"\n---\nFull `report.md`, `report.csv` and `report.json` files are attached to the [workflow run]({run_url}) as the `hydrofabric-comparison-reports` artifact."

    # Share the remaining character budget evenly between the reports.
    used = len("\n".join(parts)) + len(footer)
    per_report = (MAX_COMMENT_CHARS - used) // max(len(reports), 1)

    for title, report in reports:
        body = demote_headings(report.read_text())
        body = truncate_at_line(body, per_report, full_report_note)
        parts.extend([f"### {title}", "", body, ""])

    if not reports:
        parts.append("The comparison did not produce a report. See the workflow log for details.")

    parts.append(footer)
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the PR comment from comparison reports.")
    parser.add_argument("--parsed", type=Path, required=True)
    parser.add_argument("--reports-dir", type=Path, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    parsed = json.loads(args.parsed.read_text())
    args.output.write_text(build_comment(parsed, args.reports_dir, args.run_url))


if __name__ == "__main__":
    main()
