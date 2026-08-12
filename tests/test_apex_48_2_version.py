from engine.release_manifest import RELEASE_MANIFEST
from engine.release_manager import APPLICATION_VERSION, SEMANTIC_VERSION
from engine.version import APPLICATION_VERSION as VERSION_MODULE_APPLICATION_VERSION


def test_current_manifest_is_canonical_release():
    expected = RELEASE_MANIFEST["apex_version"]
    assert expected
    assert APPLICATION_VERSION == expected
    assert SEMANTIC_VERSION == expected
    assert VERSION_MODULE_APPLICATION_VERSION == expected
