from __future__ import annotations

import math
from datetime import date


def sec_rate_per_million(trade_date: date) -> float:
    if trade_date < date(2024, 5, 22):
        return 8.00
    if trade_date < date(2025, 5, 14):
        return 27.80
    if trade_date < date(2026, 4, 4):
        return 0.00
    return 20.60




def cat_llc_rate_per_share(trade_date: date) -> float:
    if trade_date < date(2024, 9, 1):
        return 0.0
    if trade_date < date(2025, 1, 1):
        return 0.000035
    if trade_date < date(2025, 7, 1):
        return 0.000022
    return 0.000009


def finra_taf_terms(trade_date: date) -> tuple[float, float]:
    if trade_date < date(2026, 1, 1):
        return 0.000166, 8.30
    return 0.000195, 9.79


def finra_taf_per_share(trade_date: date) -> float:
    return finra_taf_terms(trade_date)[0]


def _round_up_cent(value: float) -> float:
    if value <= 0:
        return 0.0
    return math.ceil((value - 1e-12) * 100.0) / 100.0


def regulatory_fees(trade_date: date, shares: float, entry_notional: float, exit_notional: float) -> dict[str, float]:
    shares = max(0.0, shares)
    exit_notional = max(0.0, exit_notional)
    exit_price = exit_notional / shares if shares > 0 else 0.0

    sec_raw = exit_notional * sec_rate_per_million(trade_date) / 1_000_000.0
    sec = _round_up_cent(sec_raw)

    taf_rate, taf_cap = finra_taf_terms(trade_date)
    # FINRA does not assess TAF when the execution price per share is below
    # the applicable per-share TAF rate.
    taf_raw = 0.0 if exit_price < taf_rate else min(shares * taf_rate, taf_cap)
    taf = _round_up_cent(taf_raw)

    # The frozen study uses the official CAT LLC industry-member rate effective
    # on the trade date and applies it to both entry and exit. Additional
    # broker-specific pass-through fees are not reconstructed.
    cat_rate = cat_llc_rate_per_share(trade_date)
    cat = shares * cat_rate * 2.0
    return {
        "sec": sec,
        "sec_unrounded": sec_raw,
        "taf": taf,
        "taf_unrounded": taf_raw,
        "taf_cap": taf_cap,
        "cat": cat,
        "cat_fee_per_share_per_side": cat_rate,
        "total": sec + taf + cat,
    }
