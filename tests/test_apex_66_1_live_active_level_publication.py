import sqlite3

from engine import canonical_session_context as csc


def _brief(levels, generated_at="2026-08-03T09:50:00-04:00"):
    return {
        "generated_at": generated_at,
        "source_session_date": "2026-07-31",
        "target_session_date": "2026-08-03",
        "version": "test",
        "structured": {"spot": 7544.0, "levels": levels},
    }


def test_live_publication_updates_mutable_without_churning_static(tmp_path):
    db = str(tmp_path / "ctx.db")
    csc.save_from_morning_brief(_brief([
        {"kind": "prev_day_high", "price": 7512.04, "source": "polygon"},
        {"kind": "developing_poc", "price": 7499.0, "source": "vp"},
        {"kind": "call_wall", "price": 7550.0, "source": "gamma"},
    ]), path=db)

    out = csc.publish_live_levels([
        {"kind": "developing_poc", "price": 7538.0, "source": "vp"},
        {"kind": "call_wall", "price": 7560.0, "source": "gamma"},
    ], symbol="SPX", target_session_date="2026-08-03",
       observed_at="2026-08-03T12:15:00-04:00", reference_spot=7542.0,
       authoritative_kinds={"developing_poc", "call_wall"}, path=db)

    assert out["ok"] is True
    rows = csc.active_levels("SPX", target_session_date="2026-08-03", path=db)
    pairs = {(r["kind"], r["price"]) for r in rows}
    assert ("prev_day_high", 7512.04) in pairs
    assert ("developing_poc", 7538.0) in pairs
    assert ("call_wall", 7560.0) in pairs
    assert ("developing_poc", 7499.0) not in pairs
    assert ("call_wall", 7550.0) not in pairs


def test_live_publication_replaces_multi_node_set_as_one_authoritative_domain(tmp_path):
    db = str(tmp_path / "ctx.db")
    csc.save_from_morning_brief(_brief([
        {"kind": "high_volume_node", "price": 7490.0, "source": "vp"},
        {"kind": "high_volume_node", "price": 7500.0, "source": "vp"},
        {"kind": "low_volume_node", "price": 7518.0, "source": "vp"},
    ]), path=db)

    csc.publish_live_levels([
        {"kind": "high_volume_node", "price": 7525.0, "source": "vp"},
        {"kind": "high_volume_node", "price": 7530.0, "source": "vp"},
    ], symbol="SPX", target_session_date="2026-08-03",
       observed_at="2026-08-03T12:20:00-04:00",
       authoritative_kinds={"hvn"}, path=db)

    rows = csc.active_levels("SPX", target_session_date="2026-08-03", path=db)
    hvn = sorted(r["price"] for r in rows if r["kind"] == "hvn")
    lvn = sorted(r["price"] for r in rows if r["kind"] == "lvn")
    assert hvn == [7525.0, 7530.0]
    # LVN provider domain was not declared authoritative in this publication.
    assert lvn == [7518.0]


def test_authoritative_empty_domain_retires_stale_rows(tmp_path):
    db = str(tmp_path / "ctx.db")
    csc.save_from_morning_brief(_brief([
        {"kind": "fair_value_gap", "price": 7528.0, "source": "liq"},
        {"kind": "prev_close", "price": 7489.72, "source": "polygon"},
    ]), path=db)

    out = csc.publish_live_levels([], symbol="SPX", target_session_date="2026-08-03",
        observed_at="2026-08-03T12:30:00-04:00",
        authoritative_kinds={"fair_value_gap"}, path=db)
    assert out["ok"] is True
    rows = csc.active_levels("SPX", target_session_date="2026-08-03", path=db)
    assert {(r["kind"], r["price"]) for r in rows} == {("prev_close", 7489.72)}


def test_missing_provider_scope_does_not_retire_prior_known_good(tmp_path):
    db = str(tmp_path / "ctx.db")
    csc.save_from_morning_brief(_brief([
        {"kind": "call_wall", "price": 7550.0, "source": "gamma"},
    ]), path=db)
    out = csc.publish_live_levels([], symbol="SPX", target_session_date="2026-08-03",
        observed_at="2026-08-03T12:35:00-04:00",
        authoritative_kinds=set(), path=db)
    assert out["ok"] is False
    rows = csc.active_levels("SPX", target_session_date="2026-08-03", path=db)
    assert [(r["kind"], r["price"]) for r in rows] == [("call_wall", 7550.0)]


def test_live_publication_refreshes_canonical_context_from_full_registry(tmp_path):
    db = str(tmp_path / "ctx.db")
    csc.save_from_morning_brief(_brief([
        {"kind": "prev_day_high", "price": 7512.04, "source": "polygon"},
        {"kind": "or15_high", "price": 7544.06, "source": "computed"},
    ]), path=db)
    csc.publish_live_levels([
        {"kind": "or15_high", "price": 7548.25, "source": "computed"},
    ], symbol="SPX", target_session_date="2026-08-03",
       observed_at="2026-08-03T12:40:00-04:00", reference_spot=7547.0,
       authoritative_kinds={"or15_high"}, path=db)

    ctx = csc.latest("SPX", target_session_date="2026-08-03", path=db)
    assert ctx["generated_at"] == "2026-08-03T12:40:00-04:00"
    assert ctx["source"] == "live_active_level_publisher"
    assert ctx["reference_spot"] == 7547.0
    pairs = {(row["kind"], float(row["price"])) for row in ctx["levels"]}
    assert ("prev_day_high", 7512.04) in pairs
    assert ("or15_high", 7548.25) in pairs
    assert ("or15_high", 7544.06) not in pairs


def test_revisions_preserve_history_while_only_latest_is_active(tmp_path):
    db = str(tmp_path / "ctx.db")
    csc.save_from_morning_brief(_brief([
        {"kind": "developing_poc", "price": 7499.0, "source": "vp"},
    ]), path=db)
    for i, price in enumerate((7505.0, 7510.0, 7515.0), start=1):
        csc.publish_live_levels([
            {"kind": "developing_poc", "price": price, "source": "vp"},
        ], symbol="SPX", target_session_date="2026-08-03",
           observed_at=f"2026-08-03T12:{40+i:02d}:00-04:00",
           authoritative_kinds={"developing_poc"}, path=db)

    active = csc.active_levels("SPX", target_session_date="2026-08-03", path=db)
    assert [(r["kind"], r["price"]) for r in active] == [("developing_poc", 7515.0)]
    with sqlite3.connect(db) as conn:
        rows = conn.execute("select price,active,revision from canonical_active_levels where kind='developing_poc' order by revision").fetchall()
    assert [r[0] for r in rows] == [7499.0, 7505.0, 7510.0, 7515.0]
    assert [r[1] for r in rows] == [0, 0, 0, 1]
    assert [r[2] for r in rows] == [1, 2, 3, 4]
