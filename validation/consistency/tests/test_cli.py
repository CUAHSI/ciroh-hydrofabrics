"""Behavioral tests for the consistency-check command."""

import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pytest
import yaml
from shapely.geometry import Point


RUNNER = Path(__file__).resolve().parents[1] / "consistency_check.py"


@pytest.fixture
def runner():
    spec = importlib.util.spec_from_file_location("consistency_check", RUNNER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def gpkg(tmp_path):
    path = tmp_path / "ngen-hydrofabric-vpu-03S.gpkg"
    gpd.GeoDataFrame({"id": ["nex-1"]}, geometry=[Point(0, 0)], crs="EPSG:4326").to_file(
        path, layer="nexus", engine="pyogrio"
    )
    return path


@pytest.fixture
def empty_gpkg(tmp_path):
    path = tmp_path / "reference-hydrofabric-vpu-16.gpkg"
    gpd.GeoDataFrame({"id": []}, geometry=[], crs="EPSG:4326").to_file(
        path, layer="divides", engine="pyogrio"
    )
    return path


def run_command(*args):
    return subprocess.run(
        [sys.executable, str(RUNNER), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_single_file_uses_explicit_metadata_instead_of_filename(gpkg, tmp_path):
    path = gpkg.rename(tmp_path / "my-build.gpkg")
    counts = tmp_path / "counts.yaml"
    counts.write_text(yaml.safe_dump({
        "custom-model": {"reference": {"01": {"geopackage_layers": {"missing_layers": 2}}}}
    }))

    result = run_command(path, "--data-model", "custom-model", "--type", "reference", "--vpu", "01", "--counts", counts)

    assert result.returncode == 0, result.stderr
    assert "my-build.gpkg | custom-model | reference | 01" in result.stdout
    assert "missing_layers | 0 | 2 | PASS | advisory" in result.stdout


def test_single_file_explicit_metadata_takes_precedence_over_filename(gpkg, tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text(yaml.safe_dump({
        "v2.2": {"reference": {"16": {"geopackage_layers": {"missing_layers": 2}}}}
    }))
    result = run_command(gpkg, "--type", "reference", "--vpu", "16", "--counts", counts)

    assert result.returncode == 0, result.stderr
    assert "| v2.2 | reference | 16" in result.stdout
    assert "missing_layers | 0 | 2 | PASS | advisory" in result.stdout


@pytest.mark.parametrize("flags", [[], ["--type", "ngen"], ["--vpu", "03S"]])
def test_single_file_requires_explicit_type_and_vpu(gpkg, flags):
    result = run_command(gpkg, *flags)

    assert result.returncode == 2
    assert "--type" in result.stderr
    assert "--vpu" in result.stderr
    assert "PASS" not in result.stdout


@pytest.mark.parametrize("vpu", ["", "03-S", "01/02"])
def test_single_file_rejects_invalid_vpu(gpkg, vpu):
    result = run_command(gpkg, "--type", "ngen", "--vpu", vpu)

    assert result.returncode == 2
    assert "VPU" in result.stderr


def test_single_file_rejects_unknown_output_type(gpkg):
    result = run_command(gpkg, "--type", "other", "--vpu", "03S")

    assert result.returncode == 2
    assert "invalid choice" in result.stderr


def test_batch_does_not_accept_single_file_metadata(gpkg, tmp_path):
    result = run_command(tmp_path, "--type", "ngen", "--vpu", "03S")

    assert result.returncode == 2
    assert "single" in result.stderr
    assert "PASS" not in result.stdout


def test_hydroshare_batch_rejects_single_file_metadata_without_downloading(runner, monkeypatch, capsys):
    def fail_if_called(*args):
        pytest.fail("a batch with single-file metadata must not make network requests")

    monkeypatch.setattr(runner.urllib.request, "build_opener", fail_if_called)
    resource = "a" * 32
    assert runner.main([f"https://www.hydroshare.org/resource/{resource}/", "--type", "ngen", "--vpu", "03S"]) == 2
    assert "single" in capsys.readouterr().err


def test_reports_metrics_for_a_geopackage(gpkg):
    result = run_command(gpkg, "--type", "ngen", "--vpu", "03S")

    assert result.returncode == 0, result.stderr
    assert "ngen-hydrofabric-vpu-03S.gpkg" in result.stdout
    assert "v2.2" in result.stdout
    assert "ngen" in result.stdout
    assert "03S" in result.stdout
    assert "geopackage_layers" in result.stdout
    assert "missing_layers" in result.stdout
    assert "PASS" in result.stdout
    assert "advisory" in result.stdout


def test_counts_are_selected_by_model_kind_vpu_and_metric(empty_gpkg, tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text(yaml.safe_dump({
        "v2.2": {"reference": {"16": {"geopackage_layers": {"empty_layers": 1}}}}
    }))
    result = run_command(empty_gpkg, "--type", "reference", "--vpu", "16", "--counts", counts)

    assert result.returncode == 0, result.stderr
    assert "empty_layers | 1 | 1 | PASS | advisory" in result.stdout
    other_model = run_command(empty_gpkg, "--type", "reference", "--vpu", "16", "--counts", counts, "--data-model", "other")
    assert other_model.returncode == 0, other_model.stderr
    assert "empty_layers | 1 | 0 | FAIL | advisory" in other_model.stdout


def test_directory_checks_each_geopackage_and_reports_bad_names(gpkg, empty_gpkg, tmp_path):
    (tmp_path / "unexpected.gpkg").write_text("not a geopackage")
    (tmp_path / "notes.txt").write_text("not a geopackage")
    result = run_command(tmp_path)

    assert result.returncode == 2
    assert gpkg.name in result.stdout
    assert empty_gpkg.name in result.stdout
    assert "unexpected.gpkg" in result.stderr
    assert "notes.txt" not in result.stderr


def test_hydroshare_checks_paginated_files_one_at_a_time(runner, gpkg, empty_gpkg, tmp_path, monkeypatch, capsys):
    resource = "a" * 32
    base = f"https://www.hydroshare.org/resource/{resource}/data/contents/"
    listing = f"https://www.hydroshare.org/hsapi/resource/{resource}/files/"
    nested = base + "nested/" + gpkg.name
    files = {nested: gpkg.read_bytes(), base + empty_gpkg.name: empty_gpkg.read_bytes()}
    requested = []

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    class FakeOpener:
        def open(self, url, timeout):
            requested.append(url)
            if url == listing:
                return Response(json.dumps({"count": 2, "next": listing + "?page=2", "results": [
                    {"file_name": gpkg.name, "url": nested.replace("https://", "http://"), "size": gpkg.stat().st_size}
                ]}).encode())
            if url == listing + "?page=2":
                return Response(json.dumps({"count": 2, "next": None, "results": [
                    {"file_name": empty_gpkg.name, "url": base + empty_gpkg.name, "size": empty_gpkg.stat().st_size}
                ]}).encode())
            assert not list(tmp_path.glob("remote-work/*/*.gpkg")), "previous download was not deleted"
            return Response(files[url])

    (tmp_path / "remote-work").mkdir()
    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *args: FakeOpener())
    monkeypatch.setattr(runner.tempfile, "tempdir", str(tmp_path / "remote-work"))
    status = runner.main([f"https://www.hydroshare.org/resource/{resource}/"])
    captured = capsys.readouterr()
    assert status == 0, captured.err
    assert gpkg.name in captured.out
    assert empty_gpkg.name in captured.out
    assert requested == [listing, nested, listing + "?page=2", base + empty_gpkg.name]
    assert not list((tmp_path / "remote-work").iterdir())


def test_hydroshare_continues_after_download_error(runner, gpkg, empty_gpkg, tmp_path, monkeypatch, capsys):
    resource = "a" * 32
    base = f"https://www.hydroshare.org/resource/{resource}/data/contents/"
    listing = f"https://www.hydroshare.org/hsapi/resource/{resource}/files/"
    work = tmp_path / "remote-work"
    work.mkdir()

    class FakeOpener:
        def open(self, url, timeout):
            if url == listing:
                return io.BytesIO(json.dumps({"count": 2, "next": None, "results": [
                    {"file_name": empty_gpkg.name, "url": base + empty_gpkg.name, "size": empty_gpkg.stat().st_size},
                    {"file_name": gpkg.name, "url": base + gpkg.name, "size": gpkg.stat().st_size},
                ]}).encode())
            if url.endswith(empty_gpkg.name):
                raise OSError("download failed")
            return io.BytesIO(gpkg.read_bytes())

    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *args: FakeOpener())
    monkeypatch.setattr(runner.tempfile, "tempdir", str(work))
    status = runner.main([f"https://www.hydroshare.org/resource/{resource}/"])
    captured = capsys.readouterr()
    assert status == 2
    assert empty_gpkg.name in captured.err
    assert gpkg.name in captured.out
    assert not list(work.iterdir())


def test_hydroshare_rejects_external_pagination(runner, monkeypatch, capsys):
    resource = "a" * 32
    requested = []

    class FakeOpener:
        def open(self, url, timeout):
            requested.append(url)
            return io.BytesIO(json.dumps({
                "count": 0, "next": "https://example.com/next", "results": []
            }).encode())

    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *args: FakeOpener())
    assert runner.main([f"https://www.hydroshare.org/resource/{resource}/"]) == 2
    assert len(requested) == 1
    assert "unsafe HydroShare URL" in capsys.readouterr().err


def test_hydroshare_rejects_truncated_file(runner, gpkg, tmp_path, monkeypatch, capsys):
    resource = "a" * 32
    base = f"https://www.hydroshare.org/resource/{resource}/data/contents/"
    listing = f"https://www.hydroshare.org/hsapi/resource/{resource}/files/"
    work = tmp_path / "remote-work"
    work.mkdir()

    class FakeOpener:
        def open(self, url, timeout):
            if url == listing:
                return io.BytesIO(json.dumps({"count": 1, "next": None, "results": [{
                    "file_name": gpkg.name, "url": base + gpkg.name, "size": gpkg.stat().st_size + 1,
                }]}).encode())
            return io.BytesIO(gpkg.read_bytes())

    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *args: FakeOpener())
    monkeypatch.setattr(runner.tempfile, "tempdir", str(work))
    assert runner.main([f"https://www.hydroshare.org/resource/{resource}/"]) == 2
    captured = capsys.readouterr()
    assert gpkg.name in captured.err
    assert "incomplete" in captured.err
    assert "PASS" not in captured.out
    assert not list(work.iterdir())


def test_failing_check_does_not_hide_other_check_results(runner, gpkg, tmp_path, monkeypatch, capsys):
    def broken(path, model, kind):
        raise ValueError("bad check")

    def healthy(path, model, kind):
        assert model == "v2.2"
        assert kind == "ngen"
        return {"problem_count": 0}

    monkeypatch.setattr(runner, "CHECKS", {"broken": broken, "healthy": healthy})
    config = tmp_path / "checks.yaml"
    config.write_text("broken:\n  blocking: false\nhealthy:\n  blocking: false\n")
    assert runner.main([str(gpkg), "--type", "ngen", "--vpu", "03S", "--config", str(config)]) == 2
    captured = capsys.readouterr()
    assert "broken" in captured.err
    assert "healthy | problem_count | 0 | 0 | PASS | advisory" in captured.out


@pytest.mark.parametrize("metrics", [{}, {"problem_count": None}])
def test_invalid_check_results_do_not_hide_later_checks(runner, gpkg, tmp_path, monkeypatch, capsys, metrics):
    monkeypatch.setattr(runner, "CHECKS", {
        "invalid": lambda path, model, kind: metrics,
        "healthy": lambda path, model, kind: {"problem_count": 0},
    })
    config = tmp_path / "checks.yaml"
    config.write_text("invalid:\n  blocking: false\nhealthy:\n  blocking: false\n")
    assert runner.main([str(gpkg), "--type", "ngen", "--vpu", "03S", "--config", str(config)]) == 2
    captured = capsys.readouterr()
    assert "invalid" in captured.err
    assert "healthy | problem_count | 0 | 0 | PASS | advisory" in captured.out


def test_hydroshare_continues_after_invalid_file_size(runner, gpkg, empty_gpkg, tmp_path, monkeypatch, capsys):
    resource = "a" * 32
    base = f"https://www.hydroshare.org/resource/{resource}/data/contents/"
    listing = f"https://www.hydroshare.org/hsapi/resource/{resource}/files/"
    work = tmp_path / "remote-work"
    work.mkdir()

    class FakeOpener:
        def open(self, url, timeout):
            if url == listing:
                return io.BytesIO(json.dumps({"count": 2, "next": None, "results": [
                    {"file_name": empty_gpkg.name, "url": base + empty_gpkg.name, "size": 0},
                    {"file_name": gpkg.name, "url": base + gpkg.name, "size": gpkg.stat().st_size},
                ]}).encode())
            assert url == base + gpkg.name
            return io.BytesIO(gpkg.read_bytes())

    monkeypatch.setattr(runner.urllib.request, "build_opener", lambda *args: FakeOpener())
    monkeypatch.setattr(runner.tempfile, "tempdir", str(work))
    assert runner.main([f"https://www.hydroshare.org/resource/{resource}/"]) == 2
    captured = capsys.readouterr()
    assert "size" in captured.err and empty_gpkg.name in captured.err
    assert gpkg.name in captured.out
    assert not list(work.iterdir())


def test_directory_continues_after_corrupt_geopackage(gpkg, tmp_path):
    bad = tmp_path / "reference-hydrofabric-vpu-16.gpkg"
    bad.write_text("not a geopackage")
    result = run_command(tmp_path)

    assert result.returncode == 2
    assert gpkg.name in result.stdout
    assert bad.name in result.stderr
    assert "could not run" in result.stderr


def test_invalid_config_does_not_silently_disable_blocking(gpkg, tmp_path):
    config = tmp_path / "checks.yaml"
    config.write_text('geopackage_layers:\n  blocking: "false"\n')
    result = run_command(gpkg, "--type", "ngen", "--vpu", "03S", "--config", config)
    assert result.returncode == 2
    assert "boolean blocking" in result.stderr


def test_unquoted_vpu_key_does_not_silently_discard_counts(empty_gpkg, tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text("v2.2:\n  reference:\n    16:\n      geopackage_layers:\n        empty_layers: 1\n")
    result = run_command(empty_gpkg, "--type", "reference", "--vpu", "16", "--counts", counts)
    assert result.returncode == 2
    assert "VPU" in result.stderr
    assert "quote" in result.stderr.lower()


def test_duplicate_config_keys_are_rejected(gpkg, tmp_path):
    config = tmp_path / "checks.yaml"
    config.write_text("geopackage_layers:\n  blocking: true\n  blocking: false\n")
    result = run_command(gpkg, "--type", "ngen", "--vpu", "03S", "--config", config)
    assert result.returncode == 2
    assert "duplicate" in result.stderr.lower()


def test_invalid_recorded_count_is_an_error(empty_gpkg, tmp_path):
    counts = tmp_path / "counts.yaml"
    counts.write_text('v2.2:\n  reference:\n    "16":\n      geopackage_layers:\n        empty_layers: -1\n')
    result = run_command(empty_gpkg, "--type", "reference", "--vpu", "16", "--counts", counts)
    assert result.returncode == 2
    assert "invalid recorded count" in result.stderr


def test_blocking_flag_only_fails_on_excess(empty_gpkg, tmp_path):
    config = tmp_path / "checks.yaml"
    config.write_text("geopackage_layers:\n  blocking: true\n")
    failed = run_command(empty_gpkg, "--type", "reference", "--vpu", "16", "--config", config)
    assert failed.returncode == 1, failed.stderr
    assert "empty_layers | 1 | 0 | FAIL | blocking" in failed.stdout

    counts = tmp_path / "counts.yaml"
    counts.write_text(yaml.safe_dump({
        "v2.2": {"reference": {"16": {"geopackage_layers": {"empty_layers": 1}}}}
    }))
    passed = run_command(empty_gpkg, "--type", "reference", "--vpu", "16", "--config", config, "--counts", counts)
    assert passed.returncode == 0, passed.stderr
    assert "empty_layers | 1 | 1 | PASS | blocking" in passed.stdout
