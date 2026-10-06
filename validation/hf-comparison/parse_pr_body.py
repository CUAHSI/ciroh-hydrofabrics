#!/usr/bin/env python3
"""
Read a pull request description (from stdin) and extract the fields used to
request a hydrofabric comparison:

    - Version: v2.2
    - VPU: 16
    - Reference hydrofabric URL: https://www.hydroshare.org/...gpkg
    - Ngen hydrofabric URL: https://www.hydroshare.org/...gpkg

The PR description is untrusted user input, so every value is validated
against a strict pattern. Anything that fails validation is dropped (set to
an empty string) and described in "errors" instead of being passed along.

Prints a JSON object to stdout:
    {
      "version": "v2.2", "vpu": "16",
      "reference_url": "...", "ngen_url": "...",
      "has_inputs": true,
      "errors": ["..."]
    }
"""

import json
import re
import sys
from urllib.parse import urlparse

# Only HydroShare may be used as a download source.
ALLOWED_HOSTS = {"www.hydroshare.org", "hydroshare.org"}
ALLOWED_EXTENSIONS = (".gpkg", ".zip")

VERSION_PATTERN = re.compile(r"^v\d+(\.\d+)*$")
VPU_PATTERN = re.compile(r"^\d{2}[A-Za-z]?$")


def strip_html_comments(text: str) -> str:
    """Remove <!-- ... --> blocks so template instructions are never parsed as values."""
    return re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)


def find_field(body: str, label: str) -> str:
    """Return the text after '<label>:' on the first matching line, or '' if absent."""
    pattern = rf"^[ \t]*(?:[-*][ \t]+)?{re.escape(label)}[ \t]*:[ \t]*(.*)$"
    match = re.search(pattern, body, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""
    # Tolerate a URL pasted as <https://...>.
    return match.group(1).strip().strip("<>").strip()


def url_problem(url: str):
    """Return a short description of why a URL is not acceptable, or None if it is."""
    parsed = urlparse(url)
    if parsed.scheme != "https":
        return "must start with https://"
    if parsed.hostname not in ALLOWED_HOSTS:
        return "must be a hydroshare.org URL"
    if not parsed.path.lower().endswith(ALLOWED_EXTENSIONS):
        return "must end in .gpkg or .zip"
    return None


def parse_body(body: str) -> dict:
    body = strip_html_comments(body.replace("\r\n", "\n"))

    version = find_field(body, "Version")
    vpu = find_field(body, "VPU")
    urls = {
        "reference_url": find_field(body, "Reference hydrofabric URL"),
        "ngen_url": find_field(body, "Ngen hydrofabric URL"),
    }
    labels = {
        "reference_url": "Reference hydrofabric URL",
        "ngen_url": "Ngen hydrofabric URL",
    }

    errors = []
    has_inputs = any(urls.values())

    # Version and VPU only matter when there is something to compare.
    if has_inputs:
        if not VERSION_PATTERN.match(version):
            errors.append("`Version` is missing or invalid (expected something like `v2.2`).")
            version = ""
        if not VPU_PATTERN.match(vpu):
            errors.append("`VPU` is missing or invalid (expected something like `16` or `03N`).")
            vpu = ""
    else:
        version, vpu = "", ""

    for key, url in urls.items():
        if not url:
            continue
        problem = url_problem(url)
        if problem:
            errors.append(f"`{labels[key]}` {problem}.")
            urls[key] = ""

    return {
        "version": version,
        "vpu": vpu,
        "reference_url": urls["reference_url"],
        "ngen_url": urls["ngen_url"],
        "has_inputs": has_inputs,
        "errors": errors,
    }


def main() -> None:
    json.dump(parse_body(sys.stdin.read()), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
