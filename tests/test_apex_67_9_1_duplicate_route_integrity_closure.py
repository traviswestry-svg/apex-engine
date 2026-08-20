from pathlib import Path

import engine.architecture_integrity as ai


def _write_app(root: Path, body: str) -> None:
    (root / "app.py").write_text(body, encoding="utf-8")


def test_disjoint_methods_on_same_path_are_not_duplicates(tmp_path, monkeypatch):
    _write_app(tmp_path, '''\nclass Dummy:\n    def route(self, *a, **k): return lambda f: f\napp=Dummy()\n@app.route("/same", methods=["GET"])\ndef read_same(): pass\n@app.route("/same", methods=["POST"])\ndef write_same(): pass\n''')
    monkeypatch.setattr(ai, "ROOT", tmp_path)
    count, dupes, details = ai._route_inventory()
    assert count == 2
    assert dupes == []
    assert details == []


def test_overlapping_methods_on_same_path_remain_integrity_failure(tmp_path, monkeypatch):
    _write_app(tmp_path, '''\nclass Dummy:\n    def route(self, *a, **k): return lambda f: f\napp=Dummy()\n@app.route("/same", methods=["GET", "POST"])\ndef first(): pass\n@app.route("/same", methods=["POST"])\ndef second(): pass\n''')
    monkeypatch.setattr(ai, "ROOT", tmp_path)
    count, dupes, details = ai._route_inventory()
    assert count == 2
    assert dupes == ["/same"]
    assert details[0]["overlapping_methods"] == ["POST"]


def test_default_get_routes_still_collide(tmp_path, monkeypatch):
    _write_app(tmp_path, '''\nclass Dummy:\n    def route(self, *a, **k): return lambda f: f\napp=Dummy()\n@app.route("/same")\ndef first(): pass\n@app.route("/same")\ndef second(): pass\n''')
    monkeypatch.setattr(ai, "ROOT", tmp_path)
    _, dupes, details = ai._route_inventory()
    assert dupes == ["/same"]
    assert details[0]["overlapping_methods"] == ["GET"]


def test_current_repository_has_no_true_overlapping_route_duplicates():
    snap = ai.snapshot()
    assert snap["duplicate_routes"] == []
    assert snap["duplicate_route_details"] == []
    assert snap["status"] == "HEALTHY"
