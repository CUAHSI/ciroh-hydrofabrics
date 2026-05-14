#!/usr/bin/env python3
"""
Usage: python clean_dvc_cache.py /path/to/directory [--dry-run]
Removes 'frozen: true', and 'md5:'/'size:' lines inside the outs: block.
"""
import sys
import re
import argparse
from pathlib import Path


def clean_dvc_file(path: Path, dry_run: bool = False) -> list[str]:
    """Clean a single .dvc file. Returns list of removed lines."""
    lines = path.read_text().splitlines(keepends=True)
    cleaned = []
    removed = []
    past_outs = False

    for line in lines:
        # One-way flag: once we see outs: we never reset it
        if re.match(r"^outs:", line):
            past_outs = True
            cleaned.append(line)
            continue

        # Remove frozen: true anywhere
        if re.match(r"^\s*frozen:\s*true\s*$", line):
            removed.append(line.rstrip())
            continue

        # After outs:, remove md5: and size: at any indentation
        if past_outs and re.match(r"^\s*md5:", line):
            removed.append(line.rstrip())
            continue

        if past_outs and re.match(r"^\s*size:", line):
            removed.append(line.rstrip())
            continue

        cleaned.append(line)

    if removed and not dry_run:
        path.write_text("".join(cleaned))

    return removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", nargs="?", default=".")
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview without writing"
    )
    args = parser.parse_args()

    target = Path(args.directory)

    if not target.is_dir():
        print(f"Error: '{target}' is not a directory", file=sys.stderr)
        sys.exit(1)

    dvc_files = list(target.rglob("*.dvc"))

    if not dvc_files:
        print(f"No .dvc files found in '{target}'")
        sys.exit(0)

    print(
        f"Found {len(dvc_files)} .dvc file(s). Processing {'(dry run) ' if args.dry_run else ''}...\n"
    )

    modified_count = 0
    for f in dvc_files:
        removed = clean_dvc_file(f, dry_run=args.dry_run)
        if removed:
            modified_count += 1
            print(f"  {'Would clean' if args.dry_run else 'Cleaned'}: {f}")
            for r in removed:
                print(f"    - {r}")
        else:
            print(f"  Unchanged: {f}")

    print(
        f"\n{modified_count}/{len(dvc_files)} file(s) {'would be ' if args.dry_run else ''}modified."
    )


if __name__ == "__main__":
    main()