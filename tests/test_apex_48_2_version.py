from engine.release_manifest import RELEASE_MANIFEST
from engine.release_manager import APPLICATION_VERSION, SEMANTIC_VERSION


def test_48_2_is_canonical_release():
    assert RELEASE_MANIFEST["apex_version"] == "48.2.0"
    assert APPLICATION_VERSION == "48.2.0"
    assert SEMANTIC_VERSION == "48.2.0"
