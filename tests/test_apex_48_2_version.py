from engine.release_manifest import RELEASE_MANIFEST
from engine.release_manager import APPLICATION_VERSION, SEMANTIC_VERSION


def test_current_manifest_is_canonical_release():
    assert RELEASE_MANIFEST["apex_version"] == "66.3.2"
    assert APPLICATION_VERSION == "66.3.2"
    assert SEMANTIC_VERSION == "66.3.2"
