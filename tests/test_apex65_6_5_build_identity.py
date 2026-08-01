from engine.build_identity import STABILIZATION_BUILD, apply_build_identity, build_identity


def test_build_identity_separates_runtime_component_and_stabilization():
    identity = build_identity(
        component_name="morning_brief",
        component_version="50.5.0_HISTORICAL_LEVEL_CALIBRATION",
        runtime_release_version="48.2.0",
    )
    assert identity["runtime_release_version"] == "48.2.0"
    assert identity["component_version"] == "50.5.0_HISTORICAL_LEVEL_CALIBRATION"
    assert identity["stabilization_build"] == "65.6.5"
    assert identity["component_name"] == "morning_brief"


def test_apply_build_identity_preserves_legacy_version():
    payload = {"version": "legacy-component-version"}
    apply_build_identity(
        payload,
        component_name="test_component",
        component_version="component-v2",
        runtime_release_version="runtime-v1",
    )
    assert payload["version"] == "legacy-component-version"
    assert payload["runtime_release_version"] == "runtime-v1"
    assert payload["component_version"] == "component-v2"
    assert payload["stabilization_build"] == STABILIZATION_BUILD
