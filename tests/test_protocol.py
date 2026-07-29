from app.protocol import PROTOCOL, canonical_json, protocol_hash


def test_signal_is_exactly_frozen():
    signal = PROTOCOL["signal"]
    assert signal["comparison"] == ">"
    assert signal["threshold_pct"] == 13.776879223878035
    assert PROTOCOL["decision_clock"] == "17:00"
    assert PROTOCOL["decision_timezone"] == "Europe/London"
    assert PROTOCOL["portfolio"]["maximum_signal_trades_per_day"] == 5
    assert PROTOCOL["portfolio"]["requested_notional_usd"] == 500.0


def test_protocol_hash_is_canonical_and_stable():
    assert canonical_json() == canonical_json()
    assert len(protocol_hash()) == 64
    assert protocol_hash() == "ddce449bdd0c6dc6f720e67ff6964bb1dbbe37d6b7429c5455eded1afd630ca2"


def test_confirmation_precedes_excluded_discovery_period():
    windows = PROTOCOL["historical_windows"]
    assert windows["confirmation"]["end_inclusive"] == "2026-04-19"
    assert windows["excluded_discovery_start"] == "2026-04-20"


def test_execution_scenarios_are_preregistered():
    scenarios = PROTOCOL["execution_scenarios"]
    assert scenarios["optimistic"]["reaction_seconds"] == 5
    assert scenarios["base"]["reaction_seconds"] == 30
    assert scenarios["conservative"]["reaction_seconds"] == 60
    assert scenarios["base"]["slippage_bps_floor"] == 10.0
    assert scenarios["base"]["spread_fraction"] == 0.25


def test_quantity_and_fee_schedule_are_frozen():
    assert PROTOCOL["portfolio"]["primary_quantity"] == "whole_shares_floor"
    assert PROTOCOL["portfolio"]["fractional_orders"].startswith("not_modelled")
    schedule = PROTOCOL["fees"]["cat_llc_per_side_schedule"]
    assert schedule[1]["usd_per_share"] == 0.000035
    assert schedule[-1]["end_inclusive"] == "2026-04-19"


def test_primary_is_locked_into_eight_quarterly_tranches():
    tranches = PROTOCOL["quarterly_tranches"]["primary"]
    assert len(tranches) == 8
    assert tranches[0]["start"] == "2024-01-01"
    assert tranches[-1]["end_inclusive"] == "2025-12-31"
    assert [item["sequence_no"] for item in tranches] == list(range(1, 9))
    assert PROTOCOL["quarterly_tranches"]["early_validation_forbidden"] is True


def test_futility_rule_is_negative_only_and_pre_registered():
    gate = PROTOCOL["early_futility_gate"]
    assert gate["enabled"] is True
    assert gate["base_net_pnl_negative"] is True
    assert gate["conservative_net_pnl_negative"] is True
    assert gate["date_block_bootstrap_95pct_upper_mean_return_nonpositive"] is True
    assert gate["action"].startswith("automatically_stop")
