from __future__ import annotations

from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from app.db import connection, fetch_all, fetch_one
from app.protocol import APP_VERSION, PROTOCOL, period_dates, protocol_hash
from app.queue import enqueue
from app.tranches import current_tranche, partition_prefix, scoped_key, seed_tranches


def create_run(run_kind: str) -> str:
    if run_kind not in {"smoke", "full"}:
        raise ValueError("run_kind must be smoke or full")
    if run_kind == "smoke":
        primary_start, primary_end = date(2024, 1, 2), date(2024, 1, 12)
        confirmation_start = confirmation_end = None
    else:
        primary_start, primary_end = period_dates("primary")
        confirmation_start, confirmation_end = period_dates("confirmation")
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into research_runs(
                run_kind,status,current_phase,primary_start,primary_end,confirmation_start,confirmation_end,
                protocol,protocol_hash,app_version
            ) values (%s,'created','primary',%s,%s,%s,%s,%s,%s,%s)
            returning id
            """,
            (
                run_kind, primary_start, primary_end, confirmation_start, confirmation_end,
                Jsonb(PROTOCOL), protocol_hash(), APP_VERSION,
            ),
        )
        run_id = str(cur.fetchone()["id"])
        conn.commit()
    seed_tranches(run_id, run_kind)
    return run_id


def start_run(run_id: str) -> None:
    run = fetch_one(
        "select run_kind,current_phase,current_tranche_key,protocol_hash from research_runs where id=%s",
        (run_id,),
    )
    if not run:
        raise ValueError("Run not found")
    if run["protocol_hash"] != protocol_hash():
        raise ValueError("This run belongs to an older frozen protocol; create a new v1.1 run")
    seed_tranches(run_id, run["run_kind"])
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update research_runs
               set status=case when current_phase='confirmation' then 'confirmation_running' else 'running' end,
                   cancel_requested=false,started_at=coalesce(started_at,now()),error=null,updated_at=now()
             where id=%s and status in ('created','cancelled','failed','quarter_complete')
            """,
            (run_id,),
        )
        cur.execute(
            """
            update work_partitions
               set status='queued',attempts=0,next_attempt_at=null,last_error=null,worker_id=null,
                   heartbeat_at=null,updated_at=now()
             where run_id=%s and status in ('failed','cancelled')
            """,
            (run_id,),
        )
        cur.execute(
            """
            update research_tranches
               set status='running',started_at=coalesce(started_at,now()),updated_at=now()
             where run_id=%s and tranche_key=(select current_tranche_key from research_runs where id=%s)
               and status in ('cancelled','failed','locked')
            """,
            (run_id,run_id),
        )
        conn.commit()

def cancel_run(run_id: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "update research_runs set cancel_requested=true,status='cancelled',updated_at=now() where id=%s",
            (run_id,),
        )
        cur.execute(
            "update work_partitions set status='cancelled',updated_at=now() where run_id=%s and status in ('queued','running')",
            (run_id,),
        )
        cur.execute(
            """
            update research_tranches set status='cancelled',updated_at=now()
             where run_id=%s and status='running'
            """,
            (run_id,),
        )
        conn.commit()

def unlock_confirmation(run_id: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select * from research_runs where id=%s for update", (run_id,))
        run = cur.fetchone()
        if not run:
            raise ValueError("Run not found")
        if run["run_kind"] != "full":
            raise ValueError("Smoke tests do not have a confirmation phase")
        if run["status"] not in {"primary_complete", "confirmation_locked"}:
            raise ValueError("Primary phase is not complete")
        if not run["primary_gate_passed"]:
            raise ValueError("Primary gate failed; confirmation remains sealed")
        if run["protocol_hash"] != protocol_hash():
            raise ValueError("Protocol hash mismatch; opening confirmation would be invalid")
        cur.execute(
            """
            update research_tranches
               set status='running',started_at=coalesce(started_at,now()),updated_at=now()
             where run_id=%s and phase='confirmation' and sequence_no=1 and status='locked'
            returning tranche_key
            """,
            (run_id,),
        )
        tranche = cur.fetchone()
        if not tranche:
            raise ValueError("Confirmation tranche is unavailable")
        cur.execute(
            """
            update research_runs
               set current_phase='confirmation',current_tranche_key=%s,status='confirmation_running',
                   confirmation_unlocked_at=now(),confirmation_protocol_hash=%s,cancel_requested=false,updated_at=now()
             where id=%s
            """,
            (tranche["tranche_key"], protocol_hash(), run_id),
        )
        conn.commit()


def _stage_counts(run_id: str, phase: str, stage: str, tranche_key: str | None = None) -> dict[str, int]:
    scope_sql = " and partition_key like %s" if tranche_key else ""
    params: tuple[Any, ...] = (run_id, phase, stage, partition_prefix(tranche_key) + "%") if tranche_key else (run_id, phase, stage)
    row = fetch_one(
        f"""
        select count(*)::int total,
               count(*) filter(where status='completed')::int completed,
               count(*) filter(where status='failed')::int failed,
               count(*) filter(where status='running')::int running,
               count(*) filter(where status='queued')::int queued
          from work_partitions where run_id=%s and phase=%s and stage=%s{scope_sql}
        """,
        params,
    )
    return row or {"total": 0, "completed": 0, "failed": 0, "running": 0, "queued": 0}


def _all_complete(run_id: str, phase: str, stage: str, tranche_key: str | None = None) -> bool:
    counts = _stage_counts(run_id, phase, stage, tranche_key)
    return counts["total"] > 0 and counts["completed"] == counts["total"]

def _batch(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def advance_all() -> None:
    runs = fetch_all(
        "select * from research_runs where status in ('running','confirmation_running') and cancel_requested=false order by created_at"
    )
    for run in runs:
        advance_run(run)


def advance_run(run: dict[str, Any]) -> None:
    from app.config import get_settings

    settings = get_settings()
    run_id = str(run["id"])
    phase = run["current_phase"]

    current_hash = protocol_hash()
    if run.get("protocol_hash") != current_hash:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update research_runs
                   set status='failed',final_classification='invalid_process',
                       error='Protocol hash does not match app v1.1.1; create a new staged run',updated_at=now()
                 where id=%s
                """,
                (run_id,),
            )
            conn.commit()
        return
    seed_tranches(run_id, run["run_kind"])
    if phase == "confirmation" and (
        run.get("protocol_hash") != current_hash
        or run.get("confirmation_protocol_hash") != current_hash
    ):
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                update research_runs
                   set status='failed',final_classification='invalid_process',
                       error='Protocol hash changed after confirmation unlock',updated_at=now()
                 where id=%s
                """,
                (run_id,),
            )
            conn.commit()
        return

    tranche = current_tranche(run_id, phase, run.get("current_tranche_key"))
    if not tranche:
        remaining = fetch_one(
            "select count(*)::int total from research_tranches where run_id=%s and phase=%s and status not in ('completed','futility_stopped')",
            (run_id, phase),
        )
        if remaining and int(remaining["total"]) == 0:
            if _stage_counts(run_id, phase, "report")["total"] == 0:
                enqueue(run_id, phase, "report", f"{phase}-final", {}, priority=95)
            _update_progress(run_id, phase, None)
        return

    tranche_key = tranche["tranche_key"]
    phase_start = tranche["start_date"]
    phase_end = tranche["end_date"]

    if _stage_counts(run_id, "primary", "catalogue")["total"] == 0:
        enqueue(run_id, "primary", "catalogue", "all-assets", {}, priority=5)
        return
    if not _all_complete(run_id, "primary", "catalogue"):
        return

    if _stage_counts(run_id, "primary", "massive_reference")["total"] == 0:
        enqueue(run_id, "primary", "massive_reference", "all-tickers", {}, priority=10)
    if _stage_counts(run_id, phase, "calendar", tranche_key)["total"] == 0:
        enqueue(
            run_id, phase, "calendar", scoped_key(tranche_key, f"{phase_start}:{phase_end}"),
            {"start": phase_start.isoformat(), "end": phase_end.isoformat(), "tranche_key": tranche_key}, priority=5,
        )
    if not _all_complete(run_id, phase, "calendar", tranche_key):
        _update_progress(run_id, phase, tranche_key)
        return

    if _stage_counts(run_id, phase, "splits", tranche_key)["total"] == 0:
        enqueue(
            run_id, phase, "splits", scoped_key(tranche_key, f"{phase_start}:{phase_end}"),
            {"start": phase_start.isoformat(), "end": phase_end.isoformat(), "tranche_key": tranche_key}, priority=10,
        )
    if not _all_complete(run_id, phase, "splits", tranche_key):
        _update_progress(run_id, phase, tranche_key)
        return

    if run["run_kind"] == "smoke":
        smoke = settings.smoke_symbol_list
        symbols = [r["symbol"] for r in fetch_all(
            "select symbol from instruments where run_id=%s and symbol=any(%s) order by symbol",
            (run_id, smoke),
        )]
    else:
        symbols = [r["symbol"] for r in fetch_all(
            "select symbol from instruments where run_id=%s and expanded_universe_eligible=true order by symbol",
            (run_id,),
        )]
    if not symbols:
        with connection() as conn, conn.cursor() as cur:
            cur.execute(
                "update research_runs set status='failed',error='No eligible Alpaca symbols were catalogued',updated_at=now() where id=%s",
                (run_id,),
            )
            conn.commit()
        return

    if _stage_counts(run_id, phase, "daily_bars", tranche_key)["total"] == 0:
        for index, group in enumerate(_batch(symbols, settings.symbol_batch_size_daily)):
            enqueue(
                run_id, phase, "daily_bars", scoped_key(tranche_key, f"batch-{index:05d}"),
                {"symbols": group, "start": phase_start.isoformat(), "end": phase_end.isoformat(), "tranche_key": tranche_key}, priority=20,
            )
    if not _all_complete(run_id, phase, "daily_bars", tranche_key):
        _update_progress(run_id, phase, tranche_key)
        return

    sessions = fetch_all(
        "select * from market_sessions where run_id=%s and phase=%s and trade_date between %s and %s order by trade_date",
        (run_id, phase, phase_start, phase_end),
    )
    if not _all_complete(run_id, "primary", "massive_reference"):
        _update_progress(run_id, phase, tranche_key)
        return

    if _stage_counts(run_id, phase, "decision_snapshot", tranche_key)["total"] == 0:
        groups = _batch(symbols, settings.symbol_batch_size_decision)
        for session in sessions:
            for index, group in enumerate(groups):
                enqueue(
                    run_id, phase, "decision_snapshot",
                    scoped_key(tranche_key, f"{session['trade_date']}:{index:05d}"),
                    {
                        "trade_date": session["trade_date"].isoformat(),
                        "decision_ts": session["decision_ts"].isoformat(),
                        "symbols": group,"tranche_key": tranche_key,
                    },
                    priority=30,
                )
    if not _all_complete(run_id, phase, "decision_snapshot", tranche_key):
        _update_progress(run_id, phase, tranche_key)
        return

    for session in sessions:
        trade_date = session["trade_date"].isoformat()
        date_prefix = scoped_key(tranche_key, trade_date)
        date_decision = fetch_one(
            """
            select count(*)::int total,count(*) filter(where status='completed')::int completed
              from work_partitions
             where run_id=%s and phase=%s and stage='decision_snapshot' and partition_key like %s
            """,
            (run_id, phase, date_prefix + ":%"),
        )
        if not date_decision or date_decision["total"] == 0 or date_decision["total"] != date_decision["completed"]:
            continue
        pending_verify = fetch_one(
            """
            select count(*)::int total,count(*) filter(where status='completed')::int completed
              from work_partitions
             where run_id=%s and phase=%s and stage='signal_verify' and partition_key like %s
            """,
            (run_id, phase, date_prefix + ":%"),
        )
        if pending_verify and pending_verify["total"] != pending_verify["completed"]:
            continue
        enqueue(
            run_id, phase, "select_date", scoped_key(tranche_key, trade_date),
            {"trade_date": trade_date,"tranche_key": tranche_key}, priority=40,
        )

    if not _all_complete(run_id, phase, "select_date", tranche_key):
        _update_progress(run_id, phase, tranche_key)
        return

    targets = fetch_all(
        """
        select id,trade_date,symbol,cohort,metadata
          from execution_targets
         where run_id=%s and phase=%s and trade_date between %s and %s
         order by trade_date,symbol,
                  case cohort when 'signal' then 0 when 'common_stock_signal' then 1
                              when 'expanded_signal' then 2 when 'liquidity_matched' then 3 else 4 end,id
        """,
        (run_id, phase, phase_start, phase_end),
    )
    # The same symbol-day may appear in primary and sensitivity cohorts. Raw SIP
    # data are identical, so one durable source object is shared across cohorts.
    grouped: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    for target in targets:
        grouped.setdefault((target["trade_date"], target["symbol"]), []).append(target)
    raw_source_by_target: dict[str, str] = {}
    with connection() as conn, conn.cursor() as cur:
        for group in grouped.values():
            source_id = str(group[0]["id"])
            for target in group:
                target_id = str(target["id"])
                raw_source_by_target[target_id] = source_id
                metadata = dict(target.get("metadata") or {})
                if metadata.get("raw_source_target_id") != source_id:
                    metadata["raw_source_target_id"] = source_id
                    cur.execute("update execution_targets set metadata=%s where id=%s", (Jsonb(metadata), target_id))
            for data_type in ("trades", "quotes"):
                key = scoped_key(tranche_key, f"{source_id}:{data_type}")
                if not fetch_one(
                    "select status from work_partitions where run_id=%s and phase=%s and stage='execution_raw' and partition_key=%s",
                    (run_id, phase, key),
                ):
                    enqueue(
                        run_id, phase, "execution_raw", key,
                        {"execution_target_id": source_id,"data_type": data_type,"tranche_key": tranche_key}, priority=50,
                    )
        conn.commit()

    raw_status = {
        str(row["source_id"]): (int(row["raw_total"]), int(row["raw_completed"]))
        for row in fetch_all(
            """
            select split_part(partition_key,':',1) source_with_prefix,
                   split_part(split_part(partition_key,':',1),'|',2) source_id,
                   count(*)::int raw_total,count(*) filter(where status='completed')::int raw_completed
              from work_partitions
             where run_id=%s and phase=%s and stage='execution_raw' and partition_key like %s
             group by split_part(partition_key,':',1)
            """,
            (run_id, phase, partition_prefix(tranche_key) + "%"),
        )
    }
    for target in targets:
        target_id = str(target["id"])
        source_id = raw_source_by_target[target_id]
        raw_total, raw_completed = raw_status.get(source_id, (0, 0))
        if raw_total == 2 and raw_completed == 2:
            enqueue(
                run_id, phase, "simulate", scoped_key(tranche_key, target_id),
                {"execution_target_id": target_id,"raw_source_target_id": source_id,"tranche_key": tranche_key}, priority=60,
            )

    if targets and not _all_complete(run_id, phase, "simulate", tranche_key):
        _update_progress(run_id, phase, tranche_key)
        return

    overnight = _stage_counts(run_id, phase, "overnight_followup", tranche_key)
    if overnight["total"] > 0 and overnight["completed"] != overnight["total"]:
        _update_progress(run_id, phase, tranche_key)
        return

    if _stage_counts(run_id, phase, "tranche_report", tranche_key)["total"] == 0:
        enqueue(
            run_id, phase, "tranche_report", scoped_key(tranche_key, tranche_key),
            {
                "tranche_key": tranche_key,"sequence_no": tranche["sequence_no"],"label": tranche["label"],
                "start": phase_start.isoformat(),"end": phase_end.isoformat(),
            }, priority=90,
        )
    _update_progress(run_id, phase, tranche_key)

def _update_progress(run_id: str, phase: str, tranche_key: str | None = None) -> None:
    stages = [
        "catalogue", "massive_reference", "calendar", "splits", "daily_bars",
        "decision_snapshot", "signal_verify", "select_date", "execution_raw", "simulate",
        "overnight_followup", "tranche_report", "report",
    ]
    progress: dict[str, Any] = {}
    for stage in stages:
        shared = stage in {"catalogue", "massive_reference", "report"}
        progress[stage] = _stage_counts(
            run_id,"primary" if stage in {"catalogue", "massive_reference"} else phase,stage,
            None if shared else tranche_key,
        )
    progress["phase"] = phase
    progress["tranche_key"] = tranche_key
    with connection() as conn, conn.cursor() as cur:
        cur.execute("update research_runs set progress=%s,updated_at=now() where id=%s", (Jsonb(progress), run_id))
        conn.commit()

