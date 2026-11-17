"""Data Model selection and semantic validation, independent of any GeoPackage."""

import copy
import json
import sys
from pathlib import Path

import pytest

CONSISTENCY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CONSISTENCY))

import data_model
from geometry.geometry_checks import geometry
from network.network_checks import network

V22 = CONSISTENCY / "models" / "v2.2"


def v22_spec(kind):
    return json.loads((V22 / f"{kind}.json").read_text())


@pytest.fixture
def models(monkeypatch, tmp_path):
    """An empty, isolated models directory that the loader reads from."""
    monkeypatch.setattr(data_model, "MODELS", tmp_path)
    return tmp_path


def install(root, spec, model="v9.9", kind=None):
    kind = kind or spec["output_kind"]
    spec["data_model_version"] = model
    (root / model).mkdir(exist_ok=True)
    (root / model / f"{kind}.json").write_text(json.dumps(spec))


@pytest.mark.parametrize("kind", ["ngen", "reference"])
def test_v22_specifications_are_fully_supported(kind):
    spec = data_model.load_spec("v2.2", kind)

    # Every check can interpret the checked-in model, or this raises.
    data_model.validate_spec(spec)


def test_output_kinds_are_the_specifications_present_for_the_model():
    assert data_model.output_kinds("v2.2") == ["ngen", "reference"]


def test_output_kinds_follow_a_newly_added_model(models):
    install(models, v22_spec("reference"), "v9.9")

    assert data_model.output_kinds("v9.9") == ["reference"]


@pytest.mark.parametrize("model", ["v9.9", "", "../v2.2", "v2.2/.."])
def test_unknown_or_unsafe_model_is_rejected_with_the_available_models(model):
    with pytest.raises(ValueError, match=r"Data Model.*v2\.2"):
        data_model.output_kinds(model)


def test_model_without_specifications_is_rejected(models):
    (models / "v9.9").mkdir()

    with pytest.raises(ValueError, match="no output kinds"):
        data_model.output_kinds("v9.9")


def test_symlinked_model_directory_is_rejected(models, tmp_path_factory):
    real = tmp_path_factory.mktemp("real")
    install(real, v22_spec("reference"), "v9.9")
    (models / "v9.9").symlink_to(real / "v9.9")

    with pytest.raises(ValueError, match="Data Model"):
        data_model.output_kinds("v9.9")


def test_metadata_must_match_the_requested_model_and_kind(models):
    spec = v22_spec("reference")
    install(models, spec, "v9.9")
    mismatched = json.loads((models / "v9.9" / "reference.json").read_text())
    mismatched["data_model_version"] = "v2.2"
    (models / "v9.9" / "reference.json").write_text(json.dumps(mismatched))

    with pytest.raises(ValueError, match="metadata"):
        data_model.load_spec("v9.9", "reference")


def test_unsupported_format_version_is_rejected(models):
    spec = v22_spec("reference")
    spec["format_version"] = "2.0"
    install(models, spec)

    with pytest.raises(ValueError, match="metadata"):
        data_model.load_spec("v9.9", "reference")


def test_missing_kind_is_rejected(models):
    install(models, v22_spec("reference"))

    with pytest.raises(ValueError, match="output kind 'ngen'"):
        data_model.load_spec("v9.9", "ngen")


def mutated(kind, change):
    spec = copy.deepcopy(v22_spec(kind))
    change(spec["checks"])
    return spec


@pytest.mark.parametrize("section", ["schema", "network", "geometry"])
def test_a_model_must_declare_the_semantics_of_each_check(section):
    spec = v22_spec("ngen")
    del spec["checks"][section]

    with pytest.raises(ValueError, match=section):
        data_model.validate_spec(spec)


def test_a_model_without_any_check_semantics_is_rejected():
    spec = v22_spec("ngen")
    del spec["checks"]

    with pytest.raises(ValueError, match="checks"):
        data_model.validate_spec(spec)


@pytest.mark.parametrize("change,message", [
    (lambda c: c["network"]["routing"].update(style="mesh"), "routing style"),
    (lambda c: c["network"]["routing"].update(unexpected=1), "unsupported.*routing"),
    (lambda c: c["network"]["routing"].update(terminal_id=True), "terminal_id"),
    (lambda c: c["network"]["primary_ids"].update(nowhere="id"), "primary_ids.*nowhere"),
    (lambda c: c["network"]["primary_ids"].update(divides="missing_column"), "primary_ids.*missing_column"),
    (lambda c: c["network"]["relationships"][0].update(target="nowhere"), "relationship.*nowhere"),
    (lambda c: c["network"]["relationships"][0].update(flag="missing_flag"), "relationship.*missing_flag"),
    (lambda c: c["network"]["relationships"].append(dict(c["network"]["relationships"][0])), "duplicate.*relationship"),
    (lambda c: c["network"].update(unexpected=1), "unsupported.*network"),
    (lambda c: c["geometry"].update(topology_layer="nexus"), "topology layer"),
    (lambda c: c["geometry"].update(overlap_min_area_m2=-1), "overlap_min_area_m2"),
    (lambda c: c["geometry"].update(gap_min_area_m2="big"), "gap_min_area_m2"),
    (lambda c: c["schema"].update(id_prefix_separator=""), "id_prefix_separator"),
    (lambda c: c["geometry"].update(unexpected=1), "unsupported.*geometry"),
])
def test_unsupported_or_inconsistent_semantics_are_rejected_in_ngen(change, message):
    with pytest.raises(ValueError, match=message):
        data_model.validate_spec(mutated("ngen", change))


@pytest.mark.parametrize("change,message", [
    (lambda c: c["network"]["routing"].update(link_label=""), "link_label"),
    (lambda c: c["network"]["routing"].update(layers=["nowhere"]), "routing.*nowhere"),
    (lambda c: c["network"]["routing"].pop("layers"), "layers"),
])
def test_direct_routing_requires_its_layers_in_reference(change, message):
    with pytest.raises(ValueError, match=message):
        data_model.validate_spec(mutated("reference", change))


def test_via_nexus_routing_requires_the_nexus_layers():
    spec = v22_spec("ngen")
    del spec["tables"]["nexus"]

    with pytest.raises(ValueError, match="nexus"):
        data_model.validate_spec(spec)


def test_validate_model_checks_every_kind_before_any_input_is_read(models):
    install(models, v22_spec("ngen"))
    broken = v22_spec("reference")
    broken["checks"]["network"]["routing"]["style"] = "mesh"
    install(models, broken)

    with pytest.raises(ValueError, match="reference.*routing style"):
        data_model.validate_model("v9.9")


# Each check loads the selected model itself, so it must fail explicitly,
# before reading the input, rather than fall back to v2.2.
@pytest.mark.parametrize("check", [network, geometry])
def test_a_check_rejects_an_unknown_model_before_reading_its_input(models, tmp_path, check):
    with pytest.raises(ValueError, match="no Data Model 'v9.9'"):
        check(tmp_path / "missing.gpkg", "v9.9", "ngen")


@pytest.mark.parametrize("check, section", [(network, "network"), (geometry, "geometry")])
def test_a_check_rejects_a_model_that_does_not_declare_its_semantics(models, tmp_path, check, section):
    spec = v22_spec("ngen")
    del spec["checks"][section]
    install(models, spec)

    with pytest.raises(ValueError, match=section):
        check(tmp_path / "missing.gpkg", "v9.9", "ngen")


def test_the_network_check_rejects_an_unsupported_routing_style(models, tmp_path):
    spec = v22_spec("ngen")
    spec["checks"]["network"]["routing"]["style"] = "mesh"
    install(models, spec)

    with pytest.raises(ValueError, match="unsupported routing style 'mesh'"):
        network(tmp_path / "missing.gpkg", "v9.9", "ngen")
