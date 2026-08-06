from __future__ import annotations

import gzip
import hashlib
import io
import json
import math
import random
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Iterator
from uuid import UUID
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db import connection, fetch_all, fetch_one
from app.orchestrator import _update_progress
from app.protocol import PROTOCOL
from app.providers import AlpacaClient, InvalidTickerParameter, MassiveClient
from app.queue import complete, enqueue, heartbeat, is_cancelled
from app.simulation import simulate_target
from app.storage import StorageClient
from app.timeutils import NEW_YORK, alpaca_session_timestamp, decision_timestamp, parse_timestamp
from app.trade_conditions import price_updating_trade

settings = get_settings()
SYMBOL_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,14}$")
COMMON_STOCK_TYPES = {"CS"}


def _valid_symbol(symbol: str) -> bool:
    return bool(SYMBOL_RE.fullmatch(symbol)) and any(ch.isalpha() for ch in symbol)


def process_partition(partition: dict[str, Any]) -> None:
    stage = partition["stage"]
    fn = {
        "catalogue": process_catalogue,
        "massive_reference": process_massive_reference,
        "calendar": process_calendar,
        "splits": process_splits,
        "daily_bars": process_daily_bars,
        "decision_snapshot": process_decision_snapshot,
        "signal_verify": process_signal_verify,
        "select_date": process_select_date,
        "execution_raw": process_execution_raw,
        "simulate": process_simulate,
        "overnight_followup": process_overnight_followup,
        "tranche_report": process_tranche_report,
        "report": process_report,
    }.get(stage)
    if fn is None:
        raise RuntimeError(f"Unknown stage: {stage}")
    fn(partition)


def process_catalogue(partition: dict[str, Any]) -> None:
    client = AlpacaClient()
    assets = client.assets()
    values: list[tuple[Any, ...]] = []
    for asset in assets:
        symbol = str(asset.get("symbol") or "").upper().strip()
        if not _valid_symbol(symbol):
            continue
        exchange = str(asset.get("exchange") or "")
        otc = exchange.upper().startswith("OTC") or exchange.upper() == "OTC"
        current_active = str(asset.get("status") or "").lower() == "active"
        current_tradable = bool(asset.get("tradable"))
        legacy = current_active and current_tradable and (settings.include_otc or not otc)
        expanded = (settings.include_otc or not otc)
        values.append(
            (
                partition["run_id"], asset.get("id"), symbol, asset.get("name"), exchange,
                asset.get("status"), current_active, current_tradable, bool(asset.get("fractionable")),
                bool(asset.get("shortable")), bool(asset.get("easy_to_borrow")), bool(asset.get("marginable")),
                otc, legacy, expanded, Jsonb(asset),
            )
        )
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            insert into instruments(
                run_id,alpaca_asset_id,symbol,name,exchange,alpaca_status,current_active,current_tradable,
                fractionable,shortable,easy_to_borrow,marginable,otc,legacy_universe_eligible,
                expanded_universe_eligible,metadata
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,symbol) do update set
                alpaca_asset_id=excluded.alpaca_asset_id,name=excluded.name,exchange=excluded.exchange,
                alpaca_status=excluded.alpaca_status,current_active=excluded.current_active,
                current_tradable=excluded.current_tradable,fractionable=excluded.fractionable,
                shortable=excluded.shortable,easy_to_borrow=excluded.easy_to_borrow,
                marginable=excluded.marginable,otc=excluded.otc,
                legacy_universe_eligible=excluded.legacy_universe_eligible,
                expanded_universe_eligible=excluded.expanded_universe_eligible,
                metadata=excluded.metadata,updated_at=now()
            """,
            values,
        )
        conn.commit()
    complete(str(partition["id"]), row_count=len(values))


def process_massive_reference(partition: dict[str, Any]) -> None:
    """Enrich only symbols belonging to this run, checkpointed by symbol index."""
    symbols = [str(item).upper() for item in (partition.get("params") or {}).get("symbols", []) if item]
    if not symbols:
        # Retire the v1.1.0/v1.1.1 all-catalogue partition safely.
        complete(
            str(partition["id"]),
            row_count=0,
            cursor={"finished": True, "retired_legacy_all_tickers": True},
        )
        return

    client = MassiveClient()
    cursor = partition.get("cursor") or {}
    next_index = max(0, min(int(cursor.get("next_index") or 0), len(symbols)))
    examined = int(cursor.get("examined") or next_index)
    matched = int(cursor.get("matched") or 0)
    not_found = int(cursor.get("not_found") or 0)
    invalid = int(cursor.get("invalid") or 0)
    checkpoint_size = 10
    pending: list[tuple[Any, ...]] = []

    def flush(checkpoint_index: int) -> None:
        nonlocal pending
        checkpoint_cursor = {
            "next_index": checkpoint_index,
            "examined": examined,
            "matched": matched,
            "not_found": not_found,
            "invalid": invalid,
        }
        with connection() as conn, conn.cursor() as cur:
            if pending:
                cur.executemany(
                    """
                    update instruments
                       set massive_type=coalesce(%s,massive_type),
                           massive_active=coalesce(%s,massive_active),
                           massive_primary_exchange=coalesce(%s,massive_primary_exchange),
                           massive_cik=coalesce(%s,massive_cik),
                           massive_composite_figi=coalesce(%s,massive_composite_figi),
                           common_stock_sensitivity=coalesce(%s,common_stock_sensitivity),
                           metadata=metadata || %s,updated_at=now()
                     where run_id=%s and symbol=%s
                    """,
                    pending,
                )
            cur.execute(
                """
                update work_partitions
                   set cursor=%s,row_count=%s,heartbeat_at=now(),updated_at=now()
                 where id=%s
                """,
                (Jsonb(checkpoint_cursor), matched, partition["id"]),
            )
            conn.commit()
        pending = []

    for index in range(next_index, len(symbols)):
        if is_cancelled(str(partition["run_id"])):
            raise RuntimeError("Run cancelled")
        symbol = symbols[index]
        try:
            row = client.ticker_reference(symbol, active=True)
            lookup_status = "active"
            if row is None:
                row = client.ticker_reference(symbol, active=False)
                lookup_status = "inactive" if row is not None else "not_found"
        except InvalidTickerParameter:
            row = None
            lookup_status = "invalid_ticker_parameter"

        examined += 1
        if lookup_status == "invalid_ticker_parameter":
            invalid += 1
            pending.append(
                (
                    None, None, None, None, None, None,
                    Jsonb({
                        "massive_lookup": {
                            "status": lookup_status,
                            "symbol": symbol,
                            "app_version": "1.1.4",
                            "research_impact": "excluded_from_massive_reference_sensitivity_only",
                        }
                    }),
                    partition["run_id"],
                    symbol,
                )
            )
        elif row is not None:
            matched += 1
            ticker_type = row.get("type")
            pending.append(
                (
                    ticker_type,
                    bool(row.get("active", lookup_status == "active")),
                    row.get("primary_exchange"),
                    row.get("cik"),
                    row.get("composite_figi"),
                    ticker_type in COMMON_STOCK_TYPES,
                    Jsonb({
                        "massive": row,
                        "massive_lookup": {"status": lookup_status, "app_version": "1.1.4"},
                    }),
                    partition["run_id"],
                    symbol,
                )
            )
        else:
            not_found += 1
            pending.append(
                (
                    None, None, None, None, None, None,
                    Jsonb({
                        "massive_lookup": {
                            "status": "not_found",
                            "symbol": symbol,
                            "app_version": "1.1.4",
                        }
                    }),
                    partition["run_id"],
                    symbol,
                )
            )

        checkpoint_index = index + 1
        if len(pending) >= checkpoint_size or checkpoint_index == len(symbols):
            flush(checkpoint_index)

    complete(
        str(partition["id"]),
        row_count=matched,
        cursor={
            "next_index": len(symbols),
            "examined": examined,
            "matched": matched,
            "not_found": not_found,
            "invalid": invalid,
            "finished": True,
        },
    )

def process_calendar(partition: dict[str, Any]) -> None:
    params = partition["params"]
    start, end = date.fromisoformat(params["start"]), date.fromisoformat(params["end"])
    # Fetch beyond the phase end so a forced-overnight position on the final
    # research date still receives a valid next-session diagnostic timestamp.
    api_rows = AlpacaClient().calendar(start, end + timedelta(days=10))
    parsed: list[tuple[date, datetime, datetime, dict[str, Any]]] = []
    for row in api_rows:
        trade_date = date.fromisoformat(row["date"])
        parsed.append(
            (trade_date,alpaca_session_timestamp(trade_date,row["open"]),
             alpaca_session_timestamp(trade_date,row["close"]),row)
        )
    next_open = {parsed[i][0]: parsed[i + 1][1] for i in range(len(parsed) - 1)}
    values: list[tuple[Any, ...]] = []
    for trade_date,session_open,session_close,row in parsed:
        if not (start <= trade_date <= end):
            continue
        values.append(
            (partition["run_id"],partition["phase"],trade_date,session_open,session_close,
             decision_timestamp(trade_date),next_open.get(trade_date),Jsonb(row))
        )
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            insert into market_sessions(
                run_id,phase,trade_date,session_open,session_close,decision_ts,next_session_open,metadata
            ) values (%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,phase,trade_date) do update set
                session_open=excluded.session_open,session_close=excluded.session_close,
                decision_ts=excluded.decision_ts,next_session_open=excluded.next_session_open,
                metadata=excluded.metadata
            """,
            values,
        )
        conn.commit()
    complete(str(partition["id"]), row_count=len(values))


def process_splits(partition: dict[str, Any]) -> None:
    start = date.fromisoformat(partition["params"]["start"])
    end = date.fromisoformat(partition["params"]["end"])
    client = MassiveClient()
    next_url = (partition.get("cursor") or {}).get("next_url")
    total = int(partition.get("row_count") or 0)
    while True:
        payload = client.splits_page(start, end, next_url)
        values: list[tuple[Any, ...]] = []
        for row in payload.get("results") or []:
            symbol = str(row.get("ticker") or "").upper()
            execution_date = row.get("execution_date")
            if not symbol or not execution_date:
                continue
            values.append(
                (partition["run_id"],symbol,"split",date.fromisoformat(execution_date),
                 row.get("split_from"),row.get("split_to"),"massive",Jsonb(row))
            )
        if values:
            _upsert_splits(values)
            total += len(values)
        next_url = payload.get("next_url")
        heartbeat(str(partition["id"]), cursor={"next_url": next_url}, row_count=total)
        if is_cancelled(str(partition["run_id"])):
            raise RuntimeError("Run cancelled")
        if not next_url:
            break
    complete(str(partition["id"]), row_count=total)


def _upsert_splits(values: list[tuple[Any, ...]]) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            insert into corporate_actions(run_id,symbol,action_type,execution_date,split_from,split_to,source,metadata)
            values (%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,symbol,action_type,execution_date) do update set
                split_from=excluded.split_from,split_to=excluded.split_to,metadata=excluded.metadata
            """,
            values,
        )
        conn.commit()


def _bar_rows(payload: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    bars = payload.get("bars") or {}
    if isinstance(bars, dict):
        for symbol, rows in bars.items():
            for row in rows or []:
                yield symbol, row
    elif isinstance(bars, list):
        for row in bars:
            symbol = row.get("S") or row.get("symbol")
            if symbol:
                yield symbol, row


def process_daily_bars(partition: dict[str, Any]) -> None:
    params = partition["params"]
    symbols = list(params["symbols"])
    phase_start = date.fromisoformat(params["start"])
    phase_end = date.fromisoformat(params["end"])
    start_dt = datetime.combine(phase_start - timedelta(days=10), time.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(phase_end + timedelta(days=2), time.min, tzinfo=timezone.utc)
    token = (partition.get("cursor") or {}).get("page_token")
    total = int(partition.get("row_count") or 0)
    client = AlpacaClient()
    for payload in client.bars_pages(symbols, "1Day", start_dt, end_dt, page_token=token):
        values: list[tuple[Any, ...]] = []
        for symbol, row in _bar_rows(payload):
            ts = parse_timestamp(row["t"])
            values.append(
                (
                    partition["run_id"], partition["phase"], symbol, ts.date(), ts,
                    row.get("o"), row.get("h"), row.get("l"), row.get("c"), row.get("v"),
                    row.get("vw"), row.get("n"), settings.alpaca_feed,
                )
            )
        if values:
            with connection() as conn, conn.cursor() as cur:
                cur.executemany(
                    """
                    insert into daily_bars(
                        run_id,phase,symbol,trade_date,ts,open,high,low,close,volume,vwap,trade_count,source_feed
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    on conflict(run_id,phase,symbol,trade_date) do update set
                        ts=excluded.ts,open=excluded.open,high=excluded.high,low=excluded.low,
                        close=excluded.close,volume=excluded.volume,vwap=excluded.vwap,
                        trade_count=excluded.trade_count,source_feed=excluded.source_feed
                    """,
                    values,
                )
                conn.commit()
            total += len(values)
        token = payload.get("next_page_token")
        heartbeat(str(partition["id"]), cursor={"page_token": token}, row_count=total)
        if is_cancelled(str(partition["run_id"])):
            raise RuntimeError("Run cancelled")
    complete(str(partition["id"]), row_count=total)


def process_decision_snapshot(partition: dict[str, Any]) -> None:
    params = partition["params"]
    symbols = list(params["symbols"])
    trade_date = date.fromisoformat(params["trade_date"])
    decision_ts = parse_timestamp(params["decision_ts"])
    start_dt = decision_ts - timedelta(minutes=settings.decision_lookback_minutes)
    latest: dict[str, dict[str, Any]] = {}
    client = AlpacaClient()
    for payload in client.bars_pages(symbols, "1Min", start_dt, decision_ts, limit=10000):
        for symbol, row in _bar_rows(payload):
            ts = parse_timestamp(row["t"])
            if ts + timedelta(minutes=1) <= decision_ts:
                current = latest.get(symbol)
                if current is None or parse_timestamp(current["t"]) < ts:
                    latest[symbol] = row

    context_rows = fetch_all(
        """
        select i.symbol,i.legacy_universe_eligible,i.expanded_universe_eligible,i.common_stock_sensitivity,
               (select db.close from daily_bars db
                 where db.run_id=i.run_id and db.phase=%s and db.symbol=i.symbol and db.trade_date < %s
                 order by db.trade_date desc limit 1) previous_close,
               exists(select 1 from corporate_actions ca
                       where ca.run_id=i.run_id and ca.symbol=i.symbol and ca.execution_date=%s) split_excluded
          from instruments i where i.run_id=%s and i.symbol=any(%s)
        """,
        (partition["phase"], trade_date, trade_date, partition["run_id"], symbols),
    )
    context = {row["symbol"]: row for row in context_rows}
    threshold = PROTOCOL["signal"]["threshold_pct"]
    values: list[tuple[Any, ...]] = []
    verify: list[tuple[str, dict[str, Any]]] = []
    for symbol in symbols:
        ctx = context.get(symbol, {})
        bar = latest.get(symbol)
        previous_close = ctx.get("previous_close")
        bar_ts = parse_timestamp(bar["t"]) if bar else None
        close = float(bar["c"]) if bar and bar.get("c") is not None else None
        high = float(bar["h"]) if bar and bar.get("h") is not None else None
        proxy = ((close / previous_close - 1) * 100) if close and previous_close and previous_close > 0 else None
        proxy_high = ((high / previous_close - 1) * 100) if high and previous_close and previous_close > 0 else None
        age = int((decision_ts - (bar_ts + timedelta(minutes=1))).total_seconds()) if bar_ts else None
        exact_required = bool(
            proxy_high is not None and proxy_high > threshold and ctx.get("expanded_universe_eligible")
            and not ctx.get("split_excluded")
        )
        flags: list[str] = []
        if bar is None:
            flags.append("no_completed_bar_in_lookback")
        if previous_close is None:
            flags.append("missing_previous_close")
        if ctx.get("split_excluded"):
            flags.append("split_execution_date")
        if age is not None and age > 300:
            flags.append("stale_decision_bar")
        values.append(
            (
                partition["run_id"], partition["phase"], trade_date, symbol, decision_ts,
                bar_ts, bar.get("o") if bar else None, high, bar.get("l") if bar else None, close,
                bar.get("v") if bar else None, bar.get("vw") if bar else None, bar.get("n") if bar else None,
                previous_close, proxy, proxy_high, age, bool(ctx.get("split_excluded")),
                bool(ctx.get("legacy_universe_eligible")), bool(ctx.get("expanded_universe_eligible")),
                bool(ctx.get("common_stock_sensitivity")), exact_required, Jsonb(flags),
            )
        )
        if exact_required:
            verify.append((symbol, {
                "trade_date": trade_date.isoformat(), "symbol": symbol,
                "decision_ts": decision_ts.isoformat(), "tranche_key": params.get("tranche_key"),
            }))
    with connection() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            insert into decision_snapshots(
                run_id,phase,trade_date,symbol,decision_ts,latest_bar_ts,latest_bar_open,latest_bar_high,
                latest_bar_low,latest_bar_close,latest_bar_volume,latest_bar_vwap,latest_bar_trade_count,
                previous_close,proxy_return_pct,proxy_high_return_pct,bar_age_seconds,split_excluded,
                legacy_universe_eligible,expanded_universe_eligible,common_stock_sensitivity,
                exact_verification_required,quality_flags
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,phase,trade_date,symbol) do update set
                decision_ts=excluded.decision_ts,latest_bar_ts=excluded.latest_bar_ts,
                latest_bar_open=excluded.latest_bar_open,latest_bar_high=excluded.latest_bar_high,
                latest_bar_low=excluded.latest_bar_low,latest_bar_close=excluded.latest_bar_close,
                latest_bar_volume=excluded.latest_bar_volume,latest_bar_vwap=excluded.latest_bar_vwap,
                latest_bar_trade_count=excluded.latest_bar_trade_count,previous_close=excluded.previous_close,
                proxy_return_pct=excluded.proxy_return_pct,proxy_high_return_pct=excluded.proxy_high_return_pct,
                bar_age_seconds=excluded.bar_age_seconds,split_excluded=excluded.split_excluded,
                legacy_universe_eligible=excluded.legacy_universe_eligible,
                expanded_universe_eligible=excluded.expanded_universe_eligible,
                common_stock_sensitivity=excluded.common_stock_sensitivity,
                exact_verification_required=excluded.exact_verification_required,
                quality_flags=excluded.quality_flags
            """,
            values,
        )
        conn.commit()
    for symbol, verify_params in verify:
        tranche_key = str(verify_params.get("tranche_key") or "legacy")
        enqueue(
            str(partition["run_id"]), partition["phase"], "signal_verify",
            f"{tranche_key}|{trade_date}:{symbol}", verify_params, priority=35,
        )
    complete(str(partition["id"]), row_count=len(values))


def process_signal_verify(partition: dict[str, Any]) -> None:
    params = partition["params"]
    symbol = params["symbol"]
    trade_date = date.fromisoformat(params["trade_date"])
    decision_ts = parse_timestamp(params["decision_ts"])
    start = decision_ts - timedelta(seconds=PROTOCOL["signal"]["maximum_signal_trade_age_seconds_primary"])
    last_trade: dict[str, Any] | None = None
    for payload in AlpacaClient().trades_pages(symbol, start, decision_ts):
        for row in payload.get("trades") or []:
            if not price_updating_trade(row):
                continue
            ts = parse_timestamp(row["t"])
            if ts <= decision_ts and (last_trade is None or parse_timestamp(last_trade["t"]) < ts):
                last_trade = row
    snapshot = fetch_one(
        "select * from decision_snapshots where run_id=%s and phase=%s and trade_date=%s and symbol=%s",
        (partition["run_id"], partition["phase"], trade_date, symbol),
    )
    if not snapshot:
        raise RuntimeError("Decision snapshot missing")
    previous_close = float(snapshot["previous_close"])
    trade_ts = parse_timestamp(last_trade["t"]) if last_trade else None
    price = float(last_trade["p"]) if last_trade and last_trade.get("p") is not None else None
    age = int((decision_ts - trade_ts).total_seconds()) if trade_ts else None
    exact_return = (price / previous_close - 1) * 100 if price and previous_close > 0 else None
    qualifies = bool(
        exact_return is not None
        and exact_return > PROTOCOL["signal"]["threshold_pct"]
        and age is not None
        and age <= PROTOCOL["signal"]["maximum_signal_trade_age_seconds_primary"]
    )
    flags = list(snapshot.get("quality_flags") or [])
    if not last_trade:
        flags.append("no_sip_trade_within_signal_age_limit")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into signal_triggers(
                run_id,phase,trade_date,symbol,decision_ts,previous_close,exact_signal_trade_ts,
                exact_signal_price,exact_return_pct,signal_trade_age_seconds,qualifies,quality_flags
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,phase,trade_date,symbol) do update set
                exact_signal_trade_ts=excluded.exact_signal_trade_ts,
                exact_signal_price=excluded.exact_signal_price,exact_return_pct=excluded.exact_return_pct,
                signal_trade_age_seconds=excluded.signal_trade_age_seconds,qualifies=excluded.qualifies,
                quality_flags=excluded.quality_flags
            """,
            (
                partition["run_id"], partition["phase"], trade_date, symbol, decision_ts, previous_close,
                trade_ts, price, exact_return, age, qualifies, Jsonb(flags),
            ),
        )
        conn.commit()
    complete(str(partition["id"]), row_count=1)


def process_select_date(partition: dict[str, Any]) -> None:
    trade_date = date.fromisoformat(partition["params"]["trade_date"])
    session = fetch_one(
        "select * from market_sessions where run_id=%s and phase=%s and trade_date=%s",
        (partition["run_id"], partition["phase"], trade_date),
    )
    if not session:
        raise RuntimeError("Market session missing")
    triggers = fetch_all(
        """
        select st.*,ds.latest_bar_volume,ds.latest_bar_close,ds.common_stock_sensitivity,
               ds.legacy_universe_eligible,ds.expanded_universe_eligible
          from signal_triggers st
          join decision_snapshots ds using(run_id,phase,trade_date,symbol)
         where st.run_id=%s and st.phase=%s and st.trade_date=%s and st.qualifies=true
         order by st.exact_return_pct desc,st.symbol asc
        """,
        (partition["run_id"], partition["phase"], trade_date),
    )
    cap = PROTOCOL["portfolio"]["maximum_signal_trades_per_day"]
    selected = [row for row in triggers if row["legacy_universe_eligible"]][:cap]
    common_selected = [
        row for row in triggers if row["legacy_universe_eligible"] and row["common_stock_sensitivity"]
    ][:cap]
    expanded_selected = [row for row in triggers if row["expanded_universe_eligible"]][:cap]
    with connection() as conn, conn.cursor() as cur:
        for rank, trigger in enumerate(selected, 1):
            cur.execute("update signal_triggers set selected=true,selected_rank=%s where id=%s", (rank, trigger["id"]))
        conn.commit()

    snapshots = fetch_all(
        """
        select ds.*,
               (select db.volume*db.close from daily_bars db
                 where db.run_id=ds.run_id and db.phase=ds.phase and db.symbol=ds.symbol
                   and db.trade_date < ds.trade_date order by db.trade_date desc limit 1) prior_day_dollar_volume
          from decision_snapshots ds
         where ds.run_id=%s and ds.phase=%s and ds.trade_date=%s
           and ds.legacy_universe_eligible=true and ds.split_excluded=false
           and ds.latest_bar_close>0 and ds.previous_close>0 and coalesce(ds.bar_age_seconds,999999)<=300
           and not exists (
               select 1 from signal_triggers st where st.run_id=ds.run_id and st.phase=ds.phase
                 and st.trade_date=ds.trade_date and st.symbol=ds.symbol and st.qualifies=true
           )
        """,
        (partition["run_id"], partition["phase"], trade_date),
    )
    candidates = {row["symbol"]: row for row in snapshots}
    used: set[str] = {row["symbol"] for row in selected}
    created = 0
    for trigger in selected:
        source_snapshot = fetch_one(
            "select * from decision_snapshots where run_id=%s and phase=%s and trade_date=%s and symbol=%s",
            (partition["run_id"], partition["phase"], trade_date, trigger["symbol"]),
        )
        if not source_snapshot:
            continue
        created += _insert_target(
            partition, session, trigger["symbol"], "signal", trigger, source_snapshot, 0.0
        )
        used.add(trigger["symbol"])

        scored: list[tuple[float, str, dict[str, Any]]] = []
        source_price = float(trigger["exact_signal_price"])
        source_volume = max(float(source_snapshot.get("latest_bar_volume") or 0), 1.0)
        source_prior = fetch_one(
            "select volume*close as dv from daily_bars where run_id=%s and phase=%s and symbol=%s and trade_date<%s order by trade_date desc limit 1",
            (partition["run_id"], partition["phase"], trigger["symbol"], trade_date),
        )
        source_prior_dv = max(float((source_prior or {}).get("dv") or 0), 1.0)
        for symbol, row in candidates.items():
            if symbol in used:
                continue
            price = float(row["latest_bar_close"])
            volume = max(float(row.get("latest_bar_volume") or 0), 1.0)
            price_score = abs(math.log(price / source_price))
            volume_score = abs(math.log(volume / source_volume))
            prior_dv = max(float(row.get("prior_day_dollar_volume") or 0), 1.0)
            prior_score = abs(math.log(prior_dv / source_prior_dv))
            score = price_score + 0.35 * volume_score + 0.35 * prior_score
            scored.append((score, symbol, row))
        if scored:
            scored.sort(key=lambda x: (x[0], x[1]))
            score, symbol, row = scored[0]
            created += _insert_target(partition, session, symbol, "liquidity_matched", trigger, row, score)
            used.add(symbol)

        remaining = [(symbol, row) for symbol, row in candidates.items() if symbol not in used]
        if remaining:
            remaining.sort(
                key=lambda item: hashlib.sha256(
                    f"{partition['run_id']}:{partition['phase']}:{trade_date}:{trigger['id']}:{item[0]}".encode()
                ).hexdigest()
            )
            symbol, row = remaining[0]
            created += _insert_target(partition, session, symbol, "random", trigger, row, None)
            used.add(symbol)
    # Sensitivity populations are independently ranked. Filtering the primary top-five
    # after selection would incorrectly omit common stocks or inactive historical names
    # ranked just below ETFs/ADRs in the primary population.
    for cohort, cohort_rows in (("common_stock_signal", common_selected), ("expanded_signal", expanded_selected)):
        for trigger in cohort_rows:
            snapshot = fetch_one(
                "select * from decision_snapshots where run_id=%s and phase=%s and trade_date=%s and symbol=%s",
                (partition["run_id"], partition["phase"], trade_date, trigger["symbol"]),
            )
            if snapshot:
                created += _insert_target(partition, session, trigger["symbol"], cohort, trigger, snapshot, 0.0)

    # A genuine signal may not occur in the ten-day smoke window. On the first
    # smoke session only, collect one clearly labelled non-research probe so the
    # deployment proves raw SIP Storage, simulation and report generation without
    # fabricating a qualifying strategy observation.
    run = fetch_one("select run_kind from research_runs where id=%s", (partition["run_id"],))
    first_session = fetch_one(
        "select min(trade_date) first_date from market_sessions where run_id=%s and phase=%s",
        (partition["run_id"], partition["phase"]),
    )
    if run and run["run_kind"] == "smoke" and first_session and first_session["first_date"] == trade_date:
        probe = fetch_one(
            """
            select * from decision_snapshots
             where run_id=%s and phase=%s and trade_date=%s
               and legacy_universe_eligible=true and split_excluded=false
               and latest_bar_close>0 and previous_close>0 and coalesce(bar_age_seconds,999999)<=300
             order by case symbol when 'AAPL' then 0 when 'MSFT' then 1 else 2 end,symbol
             limit 1
            """,
            (partition["run_id"], partition["phase"], trade_date),
        )
        if probe:
            with connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    insert into signal_triggers(
                        run_id,phase,trade_date,symbol,decision_ts,previous_close,exact_signal_trade_ts,
                        exact_signal_price,exact_return_pct,signal_trade_age_seconds,qualifies,quality_flags
                    ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,false,%s)
                    on conflict(run_id,phase,trade_date,symbol) do update set
                        quality_flags=case
                            when signal_triggers.quality_flags ? 'smoke_pipeline_probe_not_a_signal'
                            then signal_triggers.quality_flags
                            else signal_triggers.quality_flags || excluded.quality_flags
                        end
                    returning *
                    """,
                    (
                        partition["run_id"],partition["phase"],trade_date,probe["symbol"],session["decision_ts"],
                        probe["previous_close"],probe["latest_bar_ts"],probe["latest_bar_close"],
                        probe["proxy_return_pct"],probe["bar_age_seconds"],Jsonb(["smoke_pipeline_probe_not_a_signal"]),
                    ),
                )
                probe_trigger = cur.fetchone()
                conn.commit()
            if probe_trigger:
                created += _insert_target(
                    partition, session, probe["symbol"], "smoke_probe", probe_trigger, probe, None
                )

    complete(str(partition["id"]), row_count=created)


def _insert_target(
    partition: dict[str, Any],
    session: dict[str, Any],
    symbol: str,
    cohort: str,
    trigger: dict[str, Any],
    snapshot: dict[str, Any],
    match_score: float | None,
) -> int:
    decision_price = (
        float(trigger["exact_signal_price"])
        if cohort in {"signal", "common_stock_signal", "expanded_signal"}
        else float(snapshot["latest_bar_close"])
    )
    prior_minute_dollar_volume = float(snapshot.get("latest_bar_volume") or 0) * float(snapshot.get("latest_bar_close") or 0)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into execution_targets(
                run_id,phase,trade_date,symbol,cohort,source_trigger_id,decision_ts,session_close,
                next_session_open,previous_close,decision_price,prior_minute_dollar_volume,
                common_stock_sensitivity,match_score,metadata
            ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,phase,trade_date,symbol,cohort,source_trigger_id) do nothing
            returning id
            """,
            (
                partition["run_id"], partition["phase"], session["trade_date"], symbol, cohort,
                trigger["id"], session["decision_ts"], session["session_close"], session["next_session_open"],
                snapshot["previous_close"], decision_price, prior_minute_dollar_volume,
                bool(snapshot.get("common_stock_sensitivity")), match_score,
                Jsonb({"source_trigger_symbol": trigger["symbol"], "source_trigger_return_pct": trigger["exact_return_pct"]}),
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return 1 if row else 0


def process_execution_raw(partition: dict[str, Any]) -> None:
    target_id = partition["params"]["execution_target_id"]
    data_type = partition["params"]["data_type"]
    target = fetch_one("select * from execution_targets where id=%s", (target_id,))
    if not target:
        raise RuntimeError("Execution target missing")
    start = parse_timestamp(target["decision_ts"]) - timedelta(minutes=2)
    end = parse_timestamp(target["session_close"]) + timedelta(minutes=5)
    cursor = partition.get("cursor") or {}
    page_token = cursor.get("page_token")
    page_index = int(cursor.get("page_index") or 0)
    total = int(partition.get("row_count") or 0)
    client = AlpacaClient()
    storage = StorageClient()
    iterator = (
        client.trades_pages(target["symbol"], start, end, page_token=page_token)
        if data_type == "trades"
        else client.quotes_pages(target["symbol"], start, end, page_token=page_token)
    )
    for payload in iterator:
        rows = payload.get(data_type) or []
        raw = "".join(json.dumps(row, separators=(",", ":"), default=str) + "\n" for row in rows).encode()
        compressed = gzip.compress(raw, compresslevel=6)
        object_path = (
            f"runs/{partition['run_id']}/{partition['phase']}/raw/{target['trade_date']}/"
            f"{target['symbol']}/{target_id}/{data_type}-{page_index:06d}.jsonl.gz"
        )
        size, digest = storage.upload_bytes(object_path, compressed, "application/gzip")
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                insert into raw_objects(
                    run_id,phase,execution_target_id,data_type,page_index,start_ts,end_ts,object_path,
                    row_count,size_bytes,sha256,source_feed
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict(execution_target_id,data_type,page_index) do update set
                    object_path=excluded.object_path,row_count=excluded.row_count,size_bytes=excluded.size_bytes,
                    sha256=excluded.sha256
                """,
                (
                    partition["run_id"], partition["phase"], target_id, data_type, page_index,
                    start, end, object_path, len(rows), size, digest, settings.alpaca_feed,
                ),
            )
            conn.commit()
        total += len(rows)
        page_index += 1
        next_token = payload.get("next_page_token")
        heartbeat(
            str(partition["id"]),
            cursor={"page_token": next_token, "page_index": page_index},
            row_count=total,
        )
        if is_cancelled(str(partition["run_id"])):
            raise RuntimeError("Run cancelled")
    complete(str(partition["id"]), row_count=total, cursor={"finished": True, "page_index": page_index})


def _iter_raw(target_id: str, data_type: str) -> Iterator[dict[str, Any]]:
    storage = StorageClient()
    objects = fetch_all(
        "select * from raw_objects where execution_target_id=%s and data_type=%s order by page_index",
        (target_id, data_type),
    )
    for obj in objects:
        payload = gzip.decompress(storage.download_bytes(obj["object_path"]))
        for line in payload.splitlines():
            if line:
                yield json.loads(line)


def process_simulate(partition: dict[str, Any]) -> None:
    target_id = partition["params"]["execution_target_id"]
    target = fetch_one("select * from execution_targets where id=%s", (target_id,))
    if not target:
        raise RuntimeError("Execution target missing")
    raw_source_target_id = str(
        partition.get("params", {}).get("raw_source_target_id")
        or (target.get("metadata") or {}).get("raw_source_target_id")
        or target_id
    )
    results = simulate_target(
        target,
        _iter_raw(raw_source_target_id, "trades"),
        _iter_raw(raw_source_target_id, "quotes"),
    )
    with connection() as conn, conn.cursor() as cur:
        for result in results:
            cur.execute(
                """
                insert into trade_results(
                    run_id,phase,execution_target_id,scenario,cohort,trade_date,symbol,fill_status,
                    requested_notional,shares,entry_ts,entry_ask,entry_price,entry_spread_bps,
                    entry_slippage_bps,exit_reason,exit_ts,exit_bid,exit_price,exit_spread_bps,
                    exit_slippage_bps,gross_pnl,fees,net_pnl,net_return_pct,
                    maximum_adverse_excursion_pct,maximum_favourable_excursion_pct,target_hit,
                    stop_triggered,forced_overnight,unresolved,common_stock_sensitivity,quality_flags,metadata
                ) values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                          %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                on conflict(execution_target_id,scenario) do update set
                    fill_status=excluded.fill_status,shares=excluded.shares,entry_ts=excluded.entry_ts,
                    entry_ask=excluded.entry_ask,entry_price=excluded.entry_price,
                    entry_spread_bps=excluded.entry_spread_bps,entry_slippage_bps=excluded.entry_slippage_bps,
                    exit_reason=excluded.exit_reason,exit_ts=excluded.exit_ts,exit_bid=excluded.exit_bid,
                    exit_price=excluded.exit_price,exit_spread_bps=excluded.exit_spread_bps,
                    exit_slippage_bps=excluded.exit_slippage_bps,gross_pnl=excluded.gross_pnl,
                    fees=excluded.fees,net_pnl=excluded.net_pnl,net_return_pct=excluded.net_return_pct,
                    maximum_adverse_excursion_pct=excluded.maximum_adverse_excursion_pct,
                    maximum_favourable_excursion_pct=excluded.maximum_favourable_excursion_pct,
                    target_hit=excluded.target_hit,stop_triggered=excluded.stop_triggered,
                    forced_overnight=excluded.forced_overnight,unresolved=excluded.unresolved,
                    quality_flags=excluded.quality_flags,metadata=excluded.metadata
                """,
                (
                    partition["run_id"], partition["phase"], target_id, result["scenario"], target["cohort"],
                    target["trade_date"], target["symbol"], result["fill_status"], result["requested_notional"],
                    result["shares"], result["entry_ts"], result["entry_ask"], result["entry_price"],
                    result["entry_spread_bps"], result["entry_slippage_bps"], result["exit_reason"],
                    result["exit_ts"], result["exit_bid"], result["exit_price"], result["exit_spread_bps"],
                    result["exit_slippage_bps"], result["gross_pnl"], result["fees"], result["net_pnl"],
                    result["net_return_pct"], result["maximum_adverse_excursion_pct"],
                    result["maximum_favourable_excursion_pct"], result["target_hit"], result["stop_triggered"],
                    result["forced_overnight"], result["unresolved"], target["common_stock_sensitivity"],
                    Jsonb(result["quality_flags"]), Jsonb(result["metadata"]),
                ),
            )
        conn.commit()
    if any(r["forced_overnight"] for r in results) and target.get("next_session_open"):
        tranche_key = str(partition.get("params", {}).get("tranche_key") or "legacy")
        enqueue(
            str(partition["run_id"]), partition["phase"], "overnight_followup",
            f"{tranche_key}|{target_id}",
            {"execution_target_id": str(target_id), "tranche_key": tranche_key}, priority=70,
        )
    complete(str(partition["id"]), row_count=len(results))


def process_overnight_followup(partition: dict[str, Any]) -> None:
    target_id = partition["params"]["execution_target_id"]
    target = fetch_one("select * from execution_targets where id=%s", (target_id,))
    if not target or not target.get("next_session_open"):
        complete(str(partition["id"]), row_count=0)
        return
    start = parse_timestamp(target["next_session_open"])
    end = start + timedelta(minutes=30)
    first_quote: dict[str, Any] | None = None
    for payload in AlpacaClient().quotes_pages(target["symbol"], start, end):
        for row in payload.get("quotes") or []:
            bp = row.get("bp")
            ap = row.get("ap")
            if bp and ap and float(bp) > 0 and float(ap) >= float(bp):
                first_quote = row
                break
        if first_quote:
            break
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from trade_results where execution_target_id=%s and forced_overnight=true",
            (target_id,),
        )
        rows = cur.fetchall()
        for row in rows:
            metadata = dict(row.get("metadata") or {})
            if first_quote and row.get("shares") and row.get("entry_price"):
                bid = float(first_quote["bp"])
                ask = float(first_quote["ap"])
                scenario = PROTOCOL["execution_scenarios"][row["scenario"]]
                spread = max(0.0, ask - bid)
                slip = max(bid * scenario["slippage_bps_floor"] / 10000.0, spread * scenario["spread_fraction"])
                exit_price = max(0.0, bid - slip)
                gross = (exit_price - float(row["entry_price"])) * float(row["shares"])
                metadata["secondary_forced_overnight"] = {
                    "exit_ts": first_quote["t"], "bid": bid, "exit_price": exit_price, "gross_pnl": gross,
                }
            else:
                metadata["secondary_forced_overnight"] = {"status": "no_executable_quote_within_30m"}
            cur.execute("update trade_results set metadata=%s where id=%s", (Jsonb(metadata), row["id"]))
        conn.commit()
    complete(str(partition["id"]), row_count=len(rows))


def process_tranche_report(partition: dict[str, Any]) -> None:
    from app.interim_reporting import build_tranche_reports

    result = build_tranche_reports(
        str(partition["run_id"]), partition["phase"], partition["params"]
    )
    complete(str(partition["id"]), row_count=result["trade_count"])


def process_report(partition: dict[str, Any]) -> None:
    from app.reporting import build_phase_report

    report = build_phase_report(str(partition["run_id"]), partition["phase"])
    complete(str(partition["id"]), row_count=report["trade_count"])
