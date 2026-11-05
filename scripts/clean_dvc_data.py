#!/usr/bin/env python3
"""Remove stage/output checksums and frozen flags from .dvc files.

Usage: python clean_dvc_data.py /path/to/directory [--dry-run]
"""
import argparse
import re
import sys
from pathlib import Path

import yaml


def clean_dvc_file(path: Path, dry_run: bool = False) -> list[str]:
    """Clean a single .dvc file. Returns list of removed lines."""
    lines = path.read_text().splitlines(keepends=True)
    document = yaml.compose("".join(lines), Loader=yaml.SafeLoader)
    if not isinstance(document, yaml.MappingNode):
        raise TypeError(f"{path}: expected a YAML mapping")

    fields_to_remove = []

    def collect_frozen(node):
        if isinstance(node, yaml.MappingNode):
            for key, value in node.value:
                if (
                    key.value == "frozen"
                    and isinstance(value, yaml.ScalarNode)
                    and value.tag == "tag:yaml.org,2002:bool"
                    and value.value == "true"
                ):
                    fields_to_remove.append((key, value))
                else:
                    collect_frozen(value)
        elif isinstance(node, yaml.SequenceNode):
            for item in node.value:
                collect_frozen(item)

    collect_frozen(document)
    for key, value in document.value:
        if key.value == "md5":
            fields_to_remove.append((key, value))
        elif key.value == "outs" and isinstance(value, yaml.SequenceNode):
            for output in value.value:
                if isinstance(output, yaml.MappingNode):
                    fields_to_remove.extend(
                        (field, field_value)
                        for field, field_value in output.value
                        if field.value in {"md5", "size"}
                    )

    removed = []
    # Use YAML node positions to preserve unrelated text, comments and dependencies.
    for key, value in sorted(fields_to_remove, key=lambda pair: pair[0].start_mark.index):
        line_number = key.start_mark.line
        line = lines[line_number]
        prefix = line[:key.start_mark.column]
        suffix = line[value.end_mark.column:].strip()
        if (
            key.start_mark.line != value.end_mark.line
            or not re.fullmatch(r"[ \t]*(?:-[ \t]+)?", prefix)
            or (suffix and not suffix.startswith("#"))
        ):
            raise ValueError(
                f"{path}:{line_number + 1}: cannot safely remove inline YAML field"
            )

        removed.append(line.rstrip())
        if "-" in prefix:
            # Keep the sequence item when its first mapping field is removed.
            lines[line_number] = prefix.rstrip() + ("\n" if line.endswith("\n") else "")
        else:
            lines[line_number] = ""

    if removed and not dry_run:
        path.write_text("".join(lines))

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
