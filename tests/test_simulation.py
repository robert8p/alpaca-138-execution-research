from datetime import date, datetime, timezone

from app.simulation import simulate_target

UTC = timezone.utc


def q(ts: str, bid: float, ask: float, bid_size: float = 1000, ask_size: float = 1000):
    return {"t": ts, "bp": bid, "ap": ask, "bs": bid_size, "as": ask_size}


def t(ts: str, price: float, size: float = 100):
    return {"t": ts, "p": price, "s": size}


def target():
    return {
        "trade_date": date(2024, 1, 2),
        "decision_ts": datetime(2024, 1, 2, 17, 0, tzinfo=UTC),
        "previous_close": 10.0,
        "prior_minute_dollar_volume": 100000.0,
        "next_session_open": datetime(2024, 1, 3, 14, 30, tzinfo=UTC),
    }


def by_name(results, name):
    return next(row for row in results if row["scenario"] == name)


def test_base_entry_and_target_exit_use_executable_quotes():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00),
        q("2024-01-02T17:05:00Z", 14.99, 15.01),
    ]
    trades = [t("2024-01-02T17:05:00Z", 15.00)]
    base = by_name(simulate_target(target(), trades, quotes), "base")
    assert base["fill_status"] == "filled"
    assert base["shares"] == 41
    assert base["entry_price"] > 12.0
    assert base["exit_reason"] == "profit_target"
    assert base["exit_price"] < 14.99
    assert base["net_pnl"] > 0


def test_stop_can_execute_worse_than_five_percent():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00),
        q("2024-01-02T17:05:00Z", 11.20, 11.25),
    ]
    trades = [t("2024-01-02T17:05:00Z", 11.22)]
    base = by_name(simulate_target(target(), trades, quotes), "base")
    assert base["stop_triggered"] is True
    assert base["exit_reason"] == "stop_loss"
    assert base["net_return_pct"] < -5.0


def test_displayed_size_rejects_fill():
    quotes = [q("2024-01-02T17:00:30Z", 11.98, 12.00, ask_size=0)]
    base = by_name(simulate_target(target(), [], quotes), "base")
    assert base["fill_status"] == "insufficient_displayed_ask"
    assert base["net_pnl"] is None


def test_missing_close_liquidity_is_forced_overnight():
    quotes = [q("2024-01-02T17:00:30Z", 11.98, 12.00)]
    base = by_name(simulate_target(target(), [], quotes), "base")
    assert base["fill_status"] == "filled"
    assert base["forced_overnight"] is True
    assert base["unresolved"] is True
    assert base["net_pnl"] is None


def test_time_exit_uses_quote_at_1555_new_york():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00),
        q("2024-01-02T20:55:00Z", 12.49, 12.51),
    ]
    base = by_name(simulate_target(target(), [], quotes), "base")
    assert base["exit_reason"] == "time_exit"
    assert base["exit_ts"] == datetime(2024, 1, 2, 20, 55, tzinfo=UTC)


def test_entry_waits_within_window_for_sufficient_displayed_size():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00, ask_size=0.10),  # 10 shares after round-lot conversion
        q("2024-01-02T17:00:33Z", 11.98, 12.00, ask_size=1.00),  # 100 shares
        q("2024-01-02T20:55:00Z", 12.49, 12.51),
    ]
    base = by_name(simulate_target(target(), [], quotes), "base")
    assert base["fill_status"] == "filled"
    assert base["entry_ts"] == datetime(2024, 1, 2, 17, 0, 33, tzinfo=UTC)


def test_forward_diagnostic_waits_for_executable_bid_capacity():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00),
        q("2024-01-02T17:05:30Z", 12.20, 12.22, bid_size=0.10),
        q("2024-01-02T17:05:40Z", 12.20, 12.22, bid_size=1.00),
        q("2024-01-02T20:55:00Z", 12.49, 12.51),
    ]
    base = by_name(simulate_target(target(), [], quotes), "base")
    diagnostic = base["metadata"]["forward_executable_returns"]["5"]
    assert diagnostic["status"] == "observed"
    assert diagnostic["delay_seconds"] == 10
    assert "forward_5m_insufficient_displayed_bid_seen" in base["quality_flags"]


def test_trade_outside_fresh_nbbo_does_not_elect_stop():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00),
        q("2024-01-02T17:05:00Z", 11.80, 12.00),
        q("2024-01-02T20:55:00Z", 12.49, 12.51),
    ]
    trades = [t("2024-01-02T17:05:00Z", 11.00)]
    base = by_name(simulate_target(target(), trades, quotes), "base")
    assert base["stop_triggered"] is False
    assert base["exit_reason"] == "time_exit"
    assert "stop_outside_nbbo_ignored" in base["quality_flags"]


def test_alpaca_quote_sizes_are_converted_from_round_lots():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00, ask_size=0.50),  # 50 displayed shares
        q("2024-01-02T20:55:00Z", 12.49, 12.51),
    ]
    base = by_name(simulate_target(target(), [], quotes), "base")
    assert base["fill_status"] == "filled"
    assert base["shares"] == 41


def test_mae_mfe_stop_at_exit_while_session_diagnostics_continue():
    quotes = [
        q("2024-01-02T17:00:30Z", 11.98, 12.00),
        q("2024-01-02T17:05:00Z", 14.99, 15.01),
        q("2024-01-02T17:10:00Z", 19.99, 20.01),
    ]
    trades = [
        t("2024-01-02T17:05:00Z", 15.00),
        t("2024-01-02T17:10:00Z", 20.00),
    ]
    base = by_name(simulate_target(target(), trades, quotes), "base")
    assert base["exit_reason"] == "profit_target"
    assert base["maximum_favourable_excursion_pct"] < 30.0
    assert base["metadata"]["session_diagnostic_high"] == 20.0
