from scripts.architecture_audit import audit_repository


def test_repository_architecture_has_no_findings():
    assert audit_repository() == []
