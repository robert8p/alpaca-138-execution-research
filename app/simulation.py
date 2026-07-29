from __future__ import annotations

import gzip
import io
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Iterable, Iterator

from app.fees import regulatory_fees
from app.protocol import PROTOCOL
from app.timeutils import parse_timestamp, time_exit_timestamp
from app.trade_conditions import price_updating_trade


def _ts(row: dict[str, Any]) -> datetime:
    return parse_timestamp(row.get("t") or row.get("timestamp"))


def _price(row: dict[str, Any]) -> float | None:
    value = row.get("p") if "p" in row else row.get("price")
    return float(value) if value is not None else None


def _quote(row: dict[str, Any]) -> tuple[float | None, float | None, float | None, float | None]:
    bp = row.get("bp", row.get("bid_price"))
    ap = row.get("ap", row.get("ask_price"))
    bs = row.get("bs", row.get("bid_size"))
    ass = row.get("as", row.get("ask_size"))
    # Alpaca SIP quote sizes (`bs`/`as`) are round lots, not shares. The
    # normalised long names are treated as already expressed in shares.
    multiplier = 100.0 if ("bs" in row or "as" in row) else 1.0
    return (
        float(bp) if bp is not None else None,
        float(ap) if ap is not None else None,
        float(bs) * multiplier if bs is not None else None,
        float(ass) * multiplier if ass is not None else None,
    )


def _valid_quote(q: dict[str, Any] | None) -> bool:
    if not q:
        return False
    bp, ap, bs, ass = _quote(q)
    return bool(bp and ap and bp > 0 and ap >= bp and (bs or 0) >= 0 and (ass or 0) >= 0)


def _slippage(price: float, bid: float, ask: float, scenario: dict[str, Any]) -> tuple[float, float]:
    spread = max(0.0, ask - bid)
    amount = max(price * scenario["slippage_bps_floor"] / 10_000.0, spread * scenario["spread_fraction"])
    bps = amount / price * 10_000.0 if price > 0 else 0.0
    return amount, bps


@dataclass
class ScenarioState:
    name: str
    config: dict[str, Any]
    reaction_ts: datetime
    entry_deadline: datetime
    exit_clock: datetime
    requested_notional: float
    previous_close: float
    prior_minute_dollar_volume: float | None
    entry_status: str = "pending"
    shares: float | None = None
    entry_ts: datetime | None = None
    entry_ask: float | None = None
    entry_price: float | None = None
    entry_spread_bps: float | None = None
    entry_slippage_bps: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    pending_exit_reason: str | None = None
    pending_exit_ts: datetime | None = None
    pending_exit_deadline: datetime | None = None
    exit_reason: str | None = None
    exit_ts: datetime | None = None
    exit_bid: float | None = None
    exit_price: float | None = None
    exit_spread_bps: float | None = None
    exit_slippage_bps: float | None = None
    max_price: float | None = None
    min_price: float | None = None
    session_max_price: float | None = None
    session_min_price: float | None = None
    target_hit: bool = False
    stop_triggered: bool = False
    forced_overnight: bool = False
    unresolved: bool = False
    quality_flags: list[str] = field(default_factory=list)
    entry_rejection_reasons: list[str] = field(default_factory=list)
    forward_executable_returns: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def open(self) -> bool:
        return self.entry_status == "filled" and self.exit_ts is None

    def attempt_entry(self, quote_row: dict[str, Any], at: datetime) -> None:
        if self.entry_status != "pending" or at > self.entry_deadline or not _valid_quote(quote_row):
            return
        qts = _ts(quote_row)
        max_age = PROTOCOL["orders"]["entry_quote_max_age_seconds"]
        if abs((at - qts).total_seconds()) > max_age:
            return
        bid, ask, _bid_size, ask_size = _quote(quote_row)
        assert bid is not None and ask is not None and ask_size is not None
        slip, slip_bps = _slippage(ask, bid, ask, self.config)
        effective = ask + slip
        shares = math.floor(self.requested_notional / effective)
        if shares < 1:
            self.entry_status = "price_above_notional"
            return
        required_size = shares * self.config["displayed_size_multiplier"]
        if ask_size < required_size:
            if "insufficient_displayed_ask" not in self.entry_rejection_reasons:
                self.entry_rejection_reasons.append("insufficient_displayed_ask")
            return
        if self.prior_minute_dollar_volume is None or self.prior_minute_dollar_volume <= 0:
            self.entry_status = "missing_capacity_volume"
            return
        ratio = self.requested_notional / self.prior_minute_dollar_volume
        if ratio > self.config["max_order_to_prior_minute_dollar_volume"]:
            self.entry_status = "volume_capacity_rejected"
            return
        self.entry_status = "filled"
        self.shares = float(shares)
        self.entry_ts = at
        self.entry_ask = ask
        self.entry_price = effective
        self.entry_spread_bps = (ask - bid) / ((ask + bid) / 2) * 10_000 if ask + bid > 0 else None
        self.entry_slippage_bps = slip_bps
        self.stop_price = effective * 0.95
        self.target_price = self.previous_close * PROTOCOL["orders"]["profit_target_multiple_of_previous_close"]
        self.max_price = effective
        self.min_price = effective
        self.session_max_price = effective
        self.session_min_price = effective

    def expire_entry(self) -> None:
        if self.entry_status != "pending":
            return
        if "insufficient_displayed_ask" in self.entry_rejection_reasons:
            self.entry_status = "insufficient_displayed_ask"
        else:
            self.entry_status = "no_fresh_executable_ask"

    def observe_trade(self, trade_row: dict[str, Any], active_quote: dict[str, Any] | None) -> None:
        if self.entry_status != "filled" or not price_updating_trade(trade_row):
            return
        ts = _ts(trade_row)
        price = _price(trade_row)
        if price is None or price <= 0:
            return
        # Session diagnostics continue after exit, but MAE/MFE must stop with the trade.
        self.session_max_price = max(self.session_max_price or price, price)
        self.session_min_price = min(self.session_min_price or price, price)
        if not self.open:
            return
        self.max_price = max(self.max_price or price, price)
        self.min_price = min(self.min_price or price, price)
        if self.pending_exit_reason:
            self.attempt_exit(active_quote, ts)
            return
        if self.target_price is not None and price >= self.target_price:
            self.target_hit = True
            self.pending_exit_reason = "profit_target"
        elif self.stop_price is not None and price <= self.stop_price:
            fresh_nbbo = False
            inside_nbbo = True
            if _valid_quote(active_quote):
                quote_ts = _ts(active_quote)
                fresh_nbbo = abs((ts - quote_ts).total_seconds()) <= PROTOCOL["orders"]["exit_quote_max_age_seconds"]
                if fresh_nbbo:
                    bid, ask, _bs, _as = _quote(active_quote)
                    assert bid is not None and ask is not None
                    inside_nbbo = bid <= price <= ask
            if fresh_nbbo and not inside_nbbo:
                if "stop_outside_nbbo_ignored" not in self.quality_flags:
                    self.quality_flags.append("stop_outside_nbbo_ignored")
                return
            if not fresh_nbbo and "stop_nbbo_election_unverified" not in self.quality_flags:
                self.quality_flags.append("stop_nbbo_election_unverified")
            self.stop_triggered = True
            self.pending_exit_reason = "stop_loss"
        if self.pending_exit_reason:
            self.pending_exit_ts = ts
            self.pending_exit_deadline = ts + timedelta(seconds=PROTOCOL["orders"]["exit_wait_seconds"])
            self.attempt_exit(active_quote, ts)

    def observe_quote(self, quote_row: dict[str, Any]) -> None:
        if self.entry_status != "filled" or self.entry_ts is None or self.entry_price is None or not _valid_quote(quote_row):
            return
        qts = _ts(quote_row)
        bid, ask, bid_size, _ask_size = _quote(quote_row)
        assert bid is not None and ask is not None and bid_size is not None
        for minutes in PROTOCOL["diagnostics"]["forward_minutes"]:
            key = str(minutes)
            if key in self.forward_executable_returns or qts < self.entry_ts + timedelta(minutes=minutes):
                continue
            if self.shares is None or bid_size < self.shares * self.config["displayed_size_multiplier"]:
                flag = f"forward_{minutes}m_insufficient_displayed_bid_seen"
                if flag not in self.quality_flags:
                    self.quality_flags.append(flag)
                continue
            slip, _slip_bps = _slippage(bid, bid, ask, self.config)
            executable = max(0.0, bid - slip)
            self.forward_executable_returns[key] = {
                "status": "observed",
                "ts": qts.isoformat(),
                "bid": bid,
                "executable_price": executable,
                "gross_return_pct": (executable / self.entry_price - 1) * 100,
                "delay_seconds": int((qts - (self.entry_ts + timedelta(minutes=minutes))).total_seconds()),
            }

    def attempt_exit(self, quote_row: dict[str, Any] | None, at: datetime) -> None:
        if not self.open or not self.pending_exit_reason or not _valid_quote(quote_row):
            return
        qts = _ts(quote_row)
        max_age = PROTOCOL["orders"]["exit_quote_max_age_seconds"]
        if abs((at - qts).total_seconds()) > max_age:
            return
        if self.pending_exit_deadline and at > self.pending_exit_deadline and self.pending_exit_reason != "time_exit":
            self.quality_flags.append("exit_quote_delayed_beyond_primary_window")
        bid, ask, bid_size, _ask_size = _quote(quote_row)
        assert bid is not None and ask is not None and bid_size is not None
        if self.shares is None or bid_size < self.shares * self.config["displayed_size_multiplier"]:
            return
        slip, slip_bps = _slippage(bid, bid, ask, self.config)
        effective = max(0.0, bid - slip)
        self.exit_reason = self.pending_exit_reason
        self.exit_ts = at
        self.exit_bid = bid
        self.exit_price = effective
        self.exit_spread_bps = (ask - bid) / ((ask + bid) / 2) * 10_000 if ask + bid > 0 else None
        self.exit_slippage_bps = slip_bps

    def maybe_time_exit(self, event_ts: datetime, active_quote: dict[str, Any] | None) -> None:
        if self.open and event_ts >= self.exit_clock and not self.pending_exit_reason:
            self.pending_exit_reason = "time_exit"
            self.pending_exit_ts = self.exit_clock
            self.pending_exit_deadline = self.exit_clock + timedelta(seconds=PROTOCOL["orders"]["exit_wait_seconds"])
            self.attempt_exit(active_quote, self.exit_clock)

    def finalize(self, trade_date, next_session_open: datetime | None) -> dict[str, Any]:
        if self.entry_status == "pending":
            self.expire_entry()
        if self.entry_status == "filled" and self.entry_ts is not None:
            for minutes in PROTOCOL["diagnostics"]["forward_minutes"]:
                key = str(minutes)
                if key not in self.forward_executable_returns:
                    self.forward_executable_returns[key] = {
                        "status": "no_executable_bid_by_session_end",
                        "target_ts": (self.entry_ts + timedelta(minutes=minutes)).isoformat(),
                    }
        if self.open:
            self.forced_overnight = True
            self.unresolved = True
            self.quality_flags.append("forced_overnight_exposure")
        gross_pnl = fees = net_pnl = net_return = None
        mae = mfe = None
        if self.entry_price and self.shares:
            if self.min_price is not None:
                mae = (self.min_price / self.entry_price - 1) * 100
            if self.max_price is not None:
                mfe = (self.max_price / self.entry_price - 1) * 100
        fee_detail: dict[str, float] = {}
        if self.entry_price and self.exit_price is not None and self.shares:
            gross_pnl = (self.exit_price - self.entry_price) * self.shares
            fee_detail = regulatory_fees(
                trade_date, self.shares, self.entry_price * self.shares, self.exit_price * self.shares
            )
            fees = fee_detail["total"]
            net_pnl = gross_pnl - fees
            net_return = net_pnl / (self.entry_price * self.shares) * 100
        return {
            "scenario": self.name,
            "fill_status": self.entry_status,
            "requested_notional": self.requested_notional,
            "shares": self.shares,
            "entry_ts": self.entry_ts,
            "entry_ask": self.entry_ask,
            "entry_price": self.entry_price,
            "entry_spread_bps": self.entry_spread_bps,
            "entry_slippage_bps": self.entry_slippage_bps,
            "exit_reason": self.exit_reason,
            "exit_ts": self.exit_ts,
            "exit_bid": self.exit_bid,
            "exit_price": self.exit_price,
            "exit_spread_bps": self.exit_spread_bps,
            "exit_slippage_bps": self.exit_slippage_bps,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "net_return_pct": net_return,
            "maximum_adverse_excursion_pct": mae,
            "maximum_favourable_excursion_pct": mfe,
            "target_hit": self.target_hit,
            "stop_triggered": self.stop_triggered,
            "forced_overnight": self.forced_overnight,
            "unresolved": self.unresolved,
            "quality_flags": self.quality_flags,
            "metadata": {
                "fee_detail": fee_detail,
                "forward_executable_returns": self.forward_executable_returns,
                "session_diagnostic_high": self.session_max_price,
                "session_diagnostic_low": self.session_min_price,
            },
        }


def simulate_target(
    target: dict[str, Any],
    trades: Iterable[dict[str, Any]],
    quotes: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    decision_ts = parse_timestamp(target["decision_ts"])
    trade_date = target["trade_date"]
    if isinstance(trade_date, str):
        from datetime import date
        trade_date = date.fromisoformat(trade_date)
    exit_clock = time_exit_timestamp(trade_date)
    states = [
        ScenarioState(
            name=name,
            config=config,
            reaction_ts=decision_ts + timedelta(seconds=config["reaction_seconds"]),
            entry_deadline=decision_ts + timedelta(seconds=config["reaction_seconds"] + PROTOCOL["orders"]["entry_wait_seconds"]),
            exit_clock=exit_clock,
            requested_notional=PROTOCOL["portfolio"]["requested_notional_usd"],
            previous_close=float(target["previous_close"]),
            prior_minute_dollar_volume=(float(target["prior_minute_dollar_volume"]) if target.get("prior_minute_dollar_volume") else None),
        )
        for name, config in PROTOCOL["execution_scenarios"].items()
    ]

    trade_iter = iter(trades)
    quote_iter = iter(quotes)
    next_trade = next(trade_iter, None)
    next_quote = next(quote_iter, None)
    active_quote: dict[str, Any] | None = None

    while next_trade is not None or next_quote is not None:
        trade_ts = _ts(next_trade) if next_trade is not None else None
        quote_ts = _ts(next_quote) if next_quote is not None else None
        use_quote = quote_ts is not None and (trade_ts is None or quote_ts <= trade_ts)
        row = next_quote if use_quote else next_trade
        assert row is not None
        event_ts = _ts(row)

        for state in states:
            state.maybe_time_exit(event_ts, active_quote)
            if state.entry_status == "pending" and event_ts >= state.reaction_ts:
                candidate_quote = active_quote if active_quote is not None else (row if use_quote else None)
                if candidate_quote is not None:
                    state.attempt_entry(candidate_quote, state.reaction_ts)
                if state.entry_status == "pending" and event_ts > state.entry_deadline:
                    state.expire_entry()

        if use_quote:
            active_quote = row
            for state in states:
                state.observe_quote(active_quote)
                if state.entry_status == "pending" and state.reaction_ts <= event_ts <= state.entry_deadline:
                    state.attempt_entry(active_quote, event_ts)
                if state.pending_exit_reason and state.open:
                    state.attempt_exit(active_quote, event_ts)
            next_quote = next(quote_iter, None)
        else:
            for state in states:
                state.observe_trade(row, active_quote)
            next_trade = next(trade_iter, None)

    for state in states:
        state.maybe_time_exit(exit_clock, active_quote)
    return [state.finalize(trade_date, target.get("next_session_open")) for state in states]
