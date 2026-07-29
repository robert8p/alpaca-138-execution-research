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
    assert protocol_hash() == "3fc98c787bd375ca7daae92e0c73c53f46c0620f3c82e2d1f767c53939102b2c"


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
