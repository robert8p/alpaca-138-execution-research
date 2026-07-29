import pandas as pd

from app.reporting import _gate, _metric_set


def synthetic_frame():
    rows = []
    for i in range(40):
        pnl = 5.0 if i % 3 else -2.0
        rows.append(
            {
                "cohort": "signal",
                "scenario": "base",
                "common_stock_sensitivity": True,
                "fill_status": "filled",
                "net_pnl": pnl,
                "gross_pnl": pnl + 0.05,
                "fees": 0.05,
                "net_return_pct": pnl / 500 * 100,
                "trade_date": f"2024-01-{(i % 20) + 1:02d}",
                "entry_ts": f"2024-01-{(i % 20) + 1:02d}T17:00:30Z",
                "symbol": f"S{i % 12}",
                "unresolved": False,
                "target_hit": pnl > 0,
                "stop_triggered": pnl < 0,
            }
        )
        rows.append({**rows[-1], "scenario": "conservative", "net_pnl": pnl / 2, "gross_pnl": pnl / 2 + .05, "net_return_pct": pnl / 1000 * 100})
    return pd.DataFrame(rows)


def test_metric_set_and_gate_are_deterministic():
    frame = synthetic_frame()
    base = _metric_set(frame, cohort="signal", scenario="base", population="all", seed_material="x")
    conservative = _metric_set(frame, cohort="signal", scenario="conservative", population="all", seed_material="y")
    again = _metric_set(frame, cohort="signal", scenario="base", population="all", seed_material="x")
    assert base.bootstrap_95pct_lower_mean_return == again.bootstrap_95pct_lower_mean_return
    assert base.completed == 40
    assert base.net_pnl > 0
    assert _gate(base, conservative)["checks"]["minimum_filled_trades"] is True


def test_concentration_uses_total_net_profit_not_gross_winners():
    frame = pd.DataFrame(
        [
            {
                "cohort": "signal", "scenario": "base", "common_stock_sensitivity": True,
                "fill_status": "filled", "net_pnl": 100.0, "gross_pnl": 100.0, "fees": 0.0,
                "net_return_pct": 20.0, "trade_date": "2024-01-02", "entry_ts": "2024-01-02T17:00:30Z",
                "symbol": "WIN", "unresolved": False, "target_hit": True, "stop_triggered": False,
            },
            {
                "cohort": "signal", "scenario": "base", "common_stock_sensitivity": True,
                "fill_status": "filled", "net_pnl": -80.0, "gross_pnl": -80.0, "fees": 0.0,
                "net_return_pct": -16.0, "trade_date": "2024-01-03", "entry_ts": "2024-01-03T17:00:30Z",
                "symbol": "LOSS", "unresolved": False, "target_hit": False, "stop_triggered": True,
            },
        ]
    )
    metrics = _metric_set(frame, cohort="signal", scenario="base", population="all", seed_material="concentration")
    assert metrics.net_pnl == 20.0
    assert metrics.single_symbol_profit_share == 5.0
    assert metrics.single_date_profit_share == 5.0
