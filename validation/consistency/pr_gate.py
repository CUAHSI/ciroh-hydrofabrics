"""Decide, from a pull request's description and changed files, whether to run the checks.

A pull request that touches the Build (the pipelines and the code that makes the
hydrofabric) must name a Build resource for the Consistency Checks to run on.
Any other pull request passes without one.

The description is untrusted input: values are read from it by label and
nothing in it is ever executed.
"""

import argparse
import os
import re
from pathlib import Path

BUILD_PATH_PREFIXES = ("pipelines/", "ngen-workflow/")
BUILD_FILES = ("Dockerfile", "docker-compose.yml")
DEFAULT_DATA_MODEL = "v2.2"
RESOURCE_URL = re.compile(r"https://(?:www\.)?hydroshare\.org/resource/[0-9a-f]{32}/?")
DATA_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def touches_build(path):
    """True if a changed file can change the Build's output; Markdown notes cannot."""
    if path in BUILD_FILES:
        return True
    if path.startswith("ngen-workflow/"):
        return not path.endswith(".md")
    return path.startswith(BUILD_PATH_PREFIXES)


def field(body, label):
    """The text after ``<label>:`` on the first line that has it, ignoring HTML comments."""
    body = re.sub(r"<!--.*?-->", "", body.replace("\r\n", "\n"), flags=re.DOTALL)
    pattern = rf"^[ \t]*(?:[-*][ \t]+)?{re.escape(label)}[ \t]*:[ \t]*(.*)$"
    match = re.search(pattern, body, flags=re.IGNORECASE | re.MULTILINE)
    # A URL pasted as <https://...> is tolerated.
    return match.group(1).strip().strip("<>").strip() if match else ""


def evaluate(body, changed_paths):
    """Return ``status`` (``run``, ``skip`` or ``fail``) and a ``message`` for the reviewer.

    A ``run`` result also carries the ``resource`` to check and its ``data_model``.
    """
    resource = field(body, "Build resource")
    if not resource:
        if any(touches_build(path) for path in changed_paths):
            return {"status": "fail", "message": "This pull request changes the Build; give a Build resource."}
        return {"status": "skip", "message": "no Build required"}
    if not RESOURCE_URL.fullmatch(resource):
        return {"status": "fail", "message": "`Build resource` must look like https://www.hydroshare.org/resource/<id>/"}
    data_model = field(body, "Data model") or DEFAULT_DATA_MODEL
    if not DATA_MODEL_NAME.fullmatch(data_model):
        return {"status": "fail", "message": "`Data model` must be a plain name such as v2.2"}
    return {"status": "run", "resource": resource, "data_model": data_model, "message": "checking Build resource"}


def main(argv=None):
    """Print the decision as ``key=value`` lines for ``$GITHUB_OUTPUT``.

    The description comes from the ``PR_BODY`` environment variable, never from a
    command line or a shell string. The command always exits 0; the workflow
    decides what a ``fail`` status does, after it has told the reviewer why.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files", type=Path, required=True, help="file listing changed paths, one per line")
    args = parser.parse_args(argv)
    changed = [line.strip() for line in args.changed_files.read_text().splitlines() if line.strip()]
    result = evaluate(os.environ.get("PR_BODY", ""), changed)
    for key in ("status", "resource", "data_model", "message"):
        if key in result:
            print(f"{key}={result[key]}")


if __name__ == "__main__":
    main()
