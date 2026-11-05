"""Tests for the DVC metadata cleanup command."""

import subprocess
import sys
from pathlib import Path

import yaml

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "clean_dvc_data.py"


def run_cleaner(directory, *args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(directory), *args],
        capture_output=True,
        text=True,
        check=True,
    )


def test_cleans_stage_and_output_hashes_without_changing_dependencies(tmp_path):
    dvc_file = tmp_path / "sample.dvc"
    dvc_file.write_text(
        "md5: stage-checksum\n"
        "frozen: true\n"
        "deps:\n"
        "- md5: dependency-checksum\n"
        "  size: 12\n"
        "  path: remote://example/input\n"
        "outs:\n"
        "- md5: output-checksum\n"
        "  size: 34\n"
        "  hash: md5\n"
        "  path: output.parquet\n"
    )

    result = run_cleaner(tmp_path)

    assert "1/1 file(s) modified" in result.stdout
    assert yaml.safe_load(dvc_file.read_text()) == {
        "deps": [{"md5": "dependency-checksum", "size": 12, "path": "remote://example/input"}],
        "outs": [{"hash": "md5", "path": "output.parquet"}],
    }
    assert "0/1 file(s) modified" in run_cleaner(tmp_path).stdout


def test_multiple_outputs_and_fields_after_outs_are_preserved(tmp_path):
    dvc_file = tmp_path / "multiple.dvc"
    dvc_file.write_text(
        "outs:\n"
        "- size: 5\n"
        "  md5: first-checksum\n"
        "  path: first\n"
        "- path: second\n"
        "  md5: second-checksum\n"
        "  size: 6\n"
        "  meta:\n"
        "    md5: nested-metadata\n"
        "    size: 7\n"
        "deps:\n"
        "- path: input\n"
        "  md5: dependency-checksum\n"
        "  size: 8\n"
        "md5: stage-checksum\n"
    )

    run_cleaner(tmp_path)

    assert yaml.safe_load(dvc_file.read_text()) == {
        "outs": [
            {"path": "first"},
            {"path": "second", "meta": {"md5": "nested-metadata", "size": 7}},
        ],
        "deps": [{"path": "input", "md5": "dependency-checksum", "size": 8}],
    }


def test_preserves_comments_and_false_frozen_flags(tmp_path):
    dvc_file = tmp_path / "sample.dvc"
    dvc_file.write_text(
        "# Keep this comment\n"
        "frozen: false\n"
        "outs:\n"
        "- md5: checksum # removed with the checksum\n"
        "  # Keep the output comment\n"
        "  path: output\n"
    )

    run_cleaner(tmp_path)

    assert dvc_file.read_text() == (
        "# Keep this comment\n"
        "frozen: false\n"
        "outs:\n"
        "-\n"
        "  # Keep the output comment\n"
        "  path: output\n"
    )


def test_inline_fields_fail_without_modifying_file(tmp_path):
    dvc_file = tmp_path / "inline.dvc"
    original = "md5: stage-checksum\nouts: [{md5: output-checksum, path: output}]\n"
    dvc_file.write_text(original)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path)], capture_output=True, text=True, check=False
    )

    assert result.returncode != 0
    assert "cannot safely remove inline YAML field" in result.stderr
    assert dvc_file.read_text() == original


def test_dry_run_reports_changes_without_writing(tmp_path):
    dvc_file = tmp_path / "sample.dvc"
    original = "md5: stage-checksum\nouts:\n- md5: output-checksum\n  path: output\n"
    dvc_file.write_text(original)

    result = run_cleaner(tmp_path, "--dry-run")

    assert "1/1 file(s) would be modified" in result.stdout
    assert dvc_file.read_text() == original
