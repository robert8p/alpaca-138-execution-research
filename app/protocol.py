from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

APP_VERSION = "1.1.1"
STRATEGY_ID = "alpaca_17london_return_gt_13_776879"

# Research values are deliberately hard-coded. Operational environment variables
# cannot change the hypothesis after outcomes are observed.
PROTOCOL: dict[str, Any] = {
    "protocol_version": "1.1.0",
    "strategy_id": STRATEGY_ID,
    "research_status": "execution_backtest_required",
    "direction": "long",
    "decision_clock": "17:00",
    "decision_timezone": "Europe/London",
    "signal": {
        "field": "last_sip_trade_at_or_before_decision",
        "comparison": ">",
        "threshold_pct": 13.776879223878035,
        "denominator": "previous_regular_session_close",
        "maximum_signal_trade_age_seconds_primary": 300,
        "lookahead_forbidden": True,
    },
    "historical_windows": {
        "primary": {"start": "2024-01-01", "end_inclusive": "2025-12-31"},
        "confirmation": {"start": "2026-01-01", "end_inclusive": "2026-04-19"},
        "excluded_discovery_start": "2026-04-20",
    },
    "quarterly_tranches": {
        "primary": [
            {"tranche_key": "2024_q1", "sequence_no": 1, "label": "2024 Q1", "start": "2024-01-01", "end_inclusive": "2024-03-31"},
            {"tranche_key": "2024_q2", "sequence_no": 2, "label": "2024 Q2", "start": "2024-04-01", "end_inclusive": "2024-06-30"},
            {"tranche_key": "2024_q3", "sequence_no": 3, "label": "2024 Q3", "start": "2024-07-01", "end_inclusive": "2024-09-30"},
            {"tranche_key": "2024_q4", "sequence_no": 4, "label": "2024 Q4", "start": "2024-10-01", "end_inclusive": "2024-12-31"},
            {"tranche_key": "2025_q1", "sequence_no": 5, "label": "2025 Q1", "start": "2025-01-01", "end_inclusive": "2025-03-31"},
            {"tranche_key": "2025_q2", "sequence_no": 6, "label": "2025 Q2", "start": "2025-04-01", "end_inclusive": "2025-06-30"},
            {"tranche_key": "2025_q3", "sequence_no": 7, "label": "2025 Q3", "start": "2025-07-01", "end_inclusive": "2025-09-30"},
            {"tranche_key": "2025_q4", "sequence_no": 8, "label": "2025 Q4", "start": "2025-10-01", "end_inclusive": "2025-12-31"},
        ],
        "confirmation": [
            {"tranche_key": "2026_confirmation", "sequence_no": 1, "label": "2026 locked confirmation", "start": "2026-01-01", "end_inclusive": "2026-04-19"},
        ],
        "report_after_every_tranche": True,
        "cumulative_reports": True,
        "early_validation_forbidden": True,
    },
    "early_futility_gate": {
        "enabled": True,
        "earliest_primary_tranche": 1,
        "minimum_completed_trades": 30,
        "minimum_independent_dates": 15,
        "minimum_symbols": 10,
        "base_net_pnl_negative": True,
        "base_mean_return_negative": True,
        "conservative_net_pnl_negative": True,
        "date_block_bootstrap_95pct_upper_mean_return_nonpositive": True,
        "action": "automatically_stop_and_classify_rejected_early_for_futility",
        "cannot_unlock_confirmation": True,
    },
    "universe": {
        "primary": "alpaca_us_equity_active_and_tradable_at_run_catalogue_snapshot",
        "includes": ["common_stock", "etf", "adr", "reit", "unit", "warrant", "other_us_equity"],
        "exclude_otc_without_entitlement": True,
        "sensitivities": ["massive_common_stock_only", "expanded_active_and_inactive_market_data_universe"],
    },
    "portfolio": {
        "requested_notional_usd": 500.0,
        "maximum_signal_trades_per_day": 5,
        "leverage": False,
        "position_recycling": False,
        "one_position_per_symbol_per_day": True,
        "primary_quantity": "whole_shares_floor",
        "fractional_orders": "not_modelled_historical_point_in_time_eligibility_unreliable",
    },
    "execution_scenarios": {
        "optimistic": {
            "reaction_seconds": 5,
            "slippage_bps_floor": 5.0,
            "spread_fraction": 0.10,
            "displayed_size_multiplier": 1.0,
            "max_order_to_prior_minute_dollar_volume": 0.01,
        },
        "base": {
            "reaction_seconds": 30,
            "slippage_bps_floor": 10.0,
            "spread_fraction": 0.25,
            "displayed_size_multiplier": 1.0,
            "max_order_to_prior_minute_dollar_volume": 0.01,
        },
        "conservative": {
            "reaction_seconds": 60,
            "slippage_bps_floor": 25.0,
            "spread_fraction": 0.50,
            "displayed_size_multiplier": 2.0,
            "max_order_to_prior_minute_dollar_volume": 0.005,
        },
    },
    "orders": {
        "entry_quote_max_age_seconds": 1,
        "sip_quote_size_unit": "round_lots_of_100_shares",
        "entry_wait_seconds": 5,
        "partial_fills_primary": False,
        "stop_loss_pct_from_actual_fill": 5.0,
        "profit_target_multiple_of_previous_close": 1.50,
        "time_exit_new_york": "15:55",
        "exit_quote_max_age_seconds": 1,
        "exit_wait_seconds": 60,
        "halted_through_close": "forced_overnight_and_secondary_next_regular_session_quote",
    },
    "fees": {
        "sec_section_31": "effective_dated_and_rounded_up_to_cent",
        "finra_taf": "effective_dated_capped_low_price_exemption_and_rounded_up_to_cent",
        "cat_llc_per_side_schedule": [
            {"start": "2024-01-01", "end_inclusive": "2024-08-31", "usd_per_share": 0.0},
            {"start": "2024-09-01", "end_inclusive": "2024-12-31", "usd_per_share": 0.000035},
            {"start": "2025-01-01", "end_inclusive": "2025-06-30", "usd_per_share": 0.000022},
            {"start": "2025-07-01", "end_inclusive": "2026-04-19", "usd_per_share": 0.000009},
        ],
        "cat_applies_to": ["entry", "exit"],
        "broker_specific_additional_fees": "not_modelled",
    },
    "controls": {
        "liquidity_matched_per_selected_signal": 1,
        "deterministic_random_per_selected_signal": 1,
        "not_part_of_portfolio_pnl": True,
    },
    "diagnostics": {
        "forward_minutes": [5, 15, 30, 60, 120],
        "report_session_high_low": True,
        "report_1555_executable_return": True,
        "neighbour_thresholds_descriptive_only_pct": [10.0, 20.0, 30.0],
    },
    "primary_gate": {
        "minimum_filled_trades": 30,
        "minimum_independent_dates": 15,
        "minimum_symbols": 10,
        "net_pnl_positive": True,
        "profit_factor_minimum": 1.25,
        "base_mean_return_positive": True,
        "base_median_return_positive": True,
        "conservative_net_pnl_nonnegative": True,
        "pnl_excluding_three_largest_winners_positive": True,
        "date_block_bootstrap_95pct_lower_mean_return_positive": True,
        "maximum_drawdown_usd": 5000.0,
        "maximum_consecutive_losses": 10,
        "maximum_unresolved_exit_rate": 0.01,
        "maximum_single_symbol_profit_share": 0.25,
        "maximum_single_date_profit_share": 0.30,
    },
    "final_classifications": [
        "validated_for_paper_testing",
        "promising_but_unproven",
        "rejected",
        "rejected_early_for_futility",
        "invalid_process",
    ],
}


def canonical_json() -> str:
    return json.dumps(PROTOCOL, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def protocol_hash() -> str:
    return hashlib.sha256(canonical_json().encode("utf-8")).hexdigest()


def period_dates(phase: str) -> tuple[date, date]:
    period = PROTOCOL["historical_windows"][phase]
    return date.fromisoformat(period["start"]), date.fromisoformat(period["end_inclusive"])
