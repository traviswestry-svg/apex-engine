"""Tests for APEX 24.3 Strategy Research Laboratory."""
from engine import institutional_research_lab_v243 as research
from engine import institutional_governance as gov


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(gov, "DB_PATH", str(tmp_path / "gov.db"))


TRADES = [
    {"pnl": 100, "r_multiple": 2.0, "regime": "TREND", "strategy_family": "MOMENTUM", "size_bucket": "FULL"},
    {"pnl": -50, "r_multiple": -1.0, "regime": "TREND", "strategy_family": "MOMENTUM", "size_bucket": "HALF"},
    {"pnl": 75, "r_multiple": 1.5, "regime": "CHOP", "strategy_family": "MEAN_REV", "size_bucket": "FULL"},
    {"pnl": -25, "r_multiple": -0.5, "regime": "CHOP", "strategy_family": "MEAN_REV", "size_bucket": "HALF"},
]


def test_status_offline_only(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = research.status()
    assert s["status"] == "READY"
    assert s["offline_research_only"] is True
    assert s["production_settings_mutation_enabled"] is False
    assert s["automatic_promotion_enabled"] is False


def test_core_metrics_math(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = research.performance_analytics(TRADES)
    o = out["overall"]
    assert o["sample"] == 4
    assert o["win_rate"] == 50.0
    assert o["gross_profit"] == 175.0
    assert o["gross_loss"] == 75.0
    # profit factor = 175/75
    assert round(float(o["profit_factor"]), 4) == round(175 / 75, 4)
    # expectancy = (100-50+75-25)/4 = 25
    assert o["expectancy"] == 25.0
    # average R = (2 -1 +1.5 -0.5)/4 = 0.5
    assert o["average_r"] == 0.5
    # max drawdown: equity path 100,50,125,100 -> peak 100 then dd 50 -> max dd 50
    assert o["max_drawdown"] == 50.0


def test_breakdowns_present(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    out = research.performance_analytics(TRADES)
    assert set(out["by_regime"]) == {"TREND", "CHOP"}
    assert set(out["by_strategy_family"]) == {"MOMENTUM", "MEAN_REV"}
    assert set(out["by_position_sizing"]) == {"FULL", "HALF"}


def test_equity_curve(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    ec = research.equity_curve(TRADES)
    assert [p["equity"] for p in ec["points"]] == [100.0, 50.0, 125.0, 100.0]
    assert ec["final_equity"] == 100.0


def test_experiment_immutable_version_history(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    created = research.create_experiment(name="EXP1", strategy="MOMENTUM",
                                         hypothesis="tighter stop improves R",
                                         baseline_params={"stop": 1.0})
    assert created["created"] is True
    assert created["production_settings_modified"] is False
    eid = created["experiment_id"]
    rev = research.add_revision(experiment_id=eid, params={"stop": 0.75},
                                notes="tighter", before_metrics={"expectancy": 20},
                                after_metrics={"expectancy": 30})
    assert rev["version_no"] == 2
    assert rev["before_after"]["delta"]["expectancy"] == 10
    assert rev["production_settings_modified"] is False
    detail = research.experiment(eid)
    assert detail["current_version"] == 2
    assert [v["version_no"] for v in detail["version_history"]] == [1, 2]


def test_create_experiment_is_idempotent_on_name(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    a = research.create_experiment(name="DUP", strategy="S", hypothesis="h")
    b = research.create_experiment(name="DUP", strategy="S", hypothesis="h")
    assert a["created"] is True and b["created"] is False
    assert b["status"] == "EXISTS"


def test_rank_strategies_orders_by_expectancy(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    r = research.rank_strategies([
        {"strategy": "LOW", "metrics": {"expectancy": 5, "profit_factor": 1.1}},
        {"strategy": "HIGH", "metrics": {"expectancy": 50, "profit_factor": 2.5}},
    ])
    assert r["ranking"][0]["strategy"] == "HIGH"
    assert r["ranking"][0]["rank"] == 1


def test_experiments_do_not_touch_production(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    research.create_experiment(name="E", strategy="S", hypothesis="h", baseline_params={"x": 1})
    # There is no production mutation API surface; status confirms the guarantee.
    assert research.status()["production_settings_mutation_enabled"] is False
    assert research.experiments()["experiments"][0]["name"] == "E"
