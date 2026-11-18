"""Behavioral tests for the pull request gate that decides whether a Build must be checked."""

import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parents[1] / "pr_gate.py"
sys.path.insert(0, str(GATE.parent))

from pr_gate import evaluate  # noqa: E402

RESOURCE = "https://www.hydroshare.org/resource/0123456789abcdef0123456789abcdef/"
EMPTY_TEMPLATE = "## Description of changes\n\nSomething.\n\nBuild resource:\nData model: v2.2\n"


def test_pull_request_without_build_affecting_paths_needs_no_build():
    result = evaluate(EMPTY_TEMPLATE, ["README.md", "docs/adr/0001-x.md", ".github/workflows/a.yaml"])

    assert result["status"] == "skip"
    assert result["message"] == "no Build required"


@pytest.mark.parametrize(
    "path",
    [
        "pipelines/conus/dvc.yaml",
        "ngen-workflow/R/hfaggregate.R",
        "ngen-workflow/Python/topology_fix.py",
        "Dockerfile",
        "docker-compose.yml",
    ],
)
def test_build_affecting_path_with_empty_build_resource_fails(path):
    result = evaluate(EMPTY_TEMPLATE, ["README.md", path])

    assert result["status"] == "fail"
    assert "Build resource" in result["message"]


def test_build_resource_on_a_build_pull_request_is_checked_with_the_default_data_model():
    body = f"Build resource: {RESOURCE}\n"

    result = evaluate(body, ["pipelines/conus/dvc.yaml"])

    assert result == {"status": "run", "resource": RESOURCE, "data_model": "v2.2", "message": "checking Build resource"}


def test_declared_data_model_is_used():
    body = f"Build resource: {RESOURCE}\nData model: v3.0\n"

    assert evaluate(body, ["Dockerfile"])["data_model"] == "v3.0"


def test_build_resource_is_read_when_pasted_as_a_list_item_in_angle_brackets():
    body = f"- Build resource: <{RESOURCE}>\n"

    result = evaluate(body, ["Dockerfile"])

    assert result["status"] == "run"
    assert result["resource"] == RESOURCE


def test_pull_request_that_does_not_touch_the_build_is_never_checked():
    body = f"Build resource: {RESOURCE}\n"

    result = evaluate(body, ["README.md"])

    assert result == {"status": "skip", "message": "no Build required"}


@pytest.mark.parametrize("body", ["Build resource: not a url\n", f"Build resource: {RESOURCE}\nData model: $(id)\n"])
def test_invalid_values_never_fail_a_pull_request_that_does_not_touch_the_build(body):
    assert evaluate(body, ["README.md"]) == {"status": "skip", "message": "no Build required"}


def test_template_instructions_in_comments_are_not_read_as_values():
    body = f"<!-- Build resource: {RESOURCE} -->\nBuild resource:\n"

    assert evaluate(body, ["Dockerfile"])["status"] == "fail"


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/resource/0123456789abcdef0123456789abcdef/",
        "http://www.hydroshare.org/resource/0123456789abcdef0123456789abcdef/",
        "https://www.hydroshare.org/resource/short/",
        "https://www.hydroshare.org/resource/0123456789abcdef0123456789abcdef/data/contents/a.gpkg",
        "https://www.hydroshare.org/resource/0123456789abcdef0123456789abcdef/; rm -rf /",
        "not a url",
    ],
)
def test_build_resource_that_is_not_a_hydroshare_resource_url_fails(value):
    result = evaluate(f"Build resource: {value}\n", ["pipelines/conus/dvc.yaml"])

    assert result["status"] == "fail"
    assert "https://www.hydroshare.org/resource/<id>/" in result["message"]
    assert "resource" not in result


@pytest.mark.parametrize("value", ["v2.2; echo hi", "../etc", "$(id)", "v 2"])
def test_data_model_that_is_not_a_plain_name_fails(value):
    body = f"Build resource: {RESOURCE}\nData model: {value}\n"

    result = evaluate(body, ["ngen-workflow/R/hfaggregate.R"])

    assert result["status"] == "fail"
    assert "Data model" in result["message"]


def test_command_prints_github_output_lines(tmp_path):
    changed = tmp_path / "changed.txt"
    changed.write_text("README.md\nngen-workflow/R/hfaggregate.R\n")
    env = {"PR_BODY": f"Build resource: {RESOURCE}\nData model: v2.2\n"}

    done = subprocess.run(
        [sys.executable, str(GATE), "--changed-files", str(changed)],
        env=env, capture_output=True, text=True, check=True,
    )

    assert done.stdout.splitlines() == [
        "status=run",
        f"resource={RESOURCE}",
        "data_model=v2.2",
        "message=checking Build resource",
    ]


def test_command_reports_a_failure_without_exiting_nonzero(tmp_path):
    changed = tmp_path / "changed.txt"
    changed.write_text("Dockerfile\n")

    done = subprocess.run(
        [sys.executable, str(GATE), "--changed-files", str(changed)],
        env={"PR_BODY": "Build resource:\n"}, capture_output=True, text=True, check=True,
    )

    lines = done.stdout.splitlines()
    assert lines[0] == "status=fail"
    assert lines[1].startswith("message=")


@pytest.mark.parametrize(
    "path",
    [
        "ngen-workflow/README.md",
        "ngen-workflow/docs/notes.md",
        "docs/Dockerfile",
        "validation/consistency/pr_gate.py",
    ],
)
def test_paths_outside_the_build_need_no_build(path):
    assert evaluate(EMPTY_TEMPLATE, [path])["status"] == "skip"
