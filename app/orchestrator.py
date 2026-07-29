from __future__ import annotations

from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from app.db import connection, fetch_all, fetch_one
from app.protocol import APP_VERSION, PROTOCOL, period_dates, protocol_hash
from app.queue import enqueue


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
        return run_id


def start_run(run_id: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update research_runs
               set status='running',cancel_requested=false,started_at=coalesce(started_at,now()),updated_at=now()
             where id=%s and status in ('created','cancelled','failed')
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
            update research_runs
               set current_phase='confirmation',status='confirmation_running',confirmation_unlocked_at=now(),
                   confirmation_protocol_hash=%s,cancel_requested=false,updated_at=now()
             where id=%s
            """,
            (protocol_hash(), run_id),
        )
        conn.commit()


def _stage_counts(run_id: str, phase: str, stage: str) -> dict[str, int]:
    row = fetch_one(
        """
        select count(*)::int total,
               count(*) filter(where status='completed')::int completed,
               count(*) filter(where status='failed')::int failed,
               count(*) filter(where status='running')::int running,
               count(*) filter(where status='queued')::int queued
          from work_partitions where run_id=%s and phase=%s and stage=%s
        """,
        (run_id, phase, stage),
    )
    return row or {"total": 0, "completed": 0, "failed": 0, "running": 0, "queued": 0}


def _all_complete(run_id: str, phase: str, stage: str) -> bool:
    counts = _stage_counts(run_id, phase, stage)
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
    phase_start = run["primary_start"] if phase == "primary" else run["confirmation_start"]
    phase_end = run["primary_end"] if phase == "primary" else run["confirmation_end"]

    # Confirmation is invalid if code or protocol changes after the user unlocks it.
    # This prevents a deployed hotfix from silently changing the sealed test.
    current_hash = protocol_hash()
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

    # Shared catalogue is always recorded under primary.
    if _stage_counts(run_id, "primary", "catalogue")["total"] == 0:
        enqueue(run_id, "primary", "catalogue", "all-assets", {}, priority=5)
        return
    if not _all_complete(run_id, "primary", "catalogue"):
        return

    if _stage_counts(run_id, "primary", "massive_reference")["total"] == 0:
        enqueue(run_id, "primary", "massive_reference", "all-tickers", {}, priority=10)
    if _stage_counts(run_id, phase, "calendar")["total"] == 0:
        enqueue(
            run_id, phase, "calendar", f"{phase_start}:{phase_end}",
            {"start": phase_start.isoformat(), "end": phase_end.isoformat()}, priority=5,
        )
    if not _all_complete(run_id, phase, "calendar"):
        _update_progress(run_id, phase)
        return

    if _stage_counts(run_id, phase, "splits")["total"] == 0:
        enqueue(
            run_id, phase, "splits", f"{phase_start}:{phase_end}",
            {"start": phase_start.isoformat(), "end": phase_end.isoformat()}, priority=10,
        )
    if not _all_complete(run_id, phase, "splits"):
        _update_progress(run_id, phase)
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

    if _stage_counts(run_id, phase, "daily_bars")["total"] == 0:
        for index, group in enumerate(_batch(symbols, settings.symbol_batch_size_daily)):
            enqueue(
                run_id, phase, "daily_bars", f"batch-{index:05d}",
                {"symbols": group, "start": phase_start.isoformat(), "end": phase_end.isoformat()}, priority=20,
            )
    if not _all_complete(run_id, phase, "daily_bars"):
        _update_progress(run_id, phase)
        return

    sessions = fetch_all(
        "select * from market_sessions where run_id=%s and phase=%s order by trade_date",
        (run_id, phase),
    )
    if not _all_complete(run_id, "primary", "massive_reference"):
        _update_progress(run_id, phase)
        return

    if _stage_counts(run_id, phase, "decision_snapshot")["total"] == 0:
        groups = _batch(symbols, settings.symbol_batch_size_decision)
        for session in sessions:
            for index, group in enumerate(groups):
                enqueue(
                    run_id, phase, "decision_snapshot",
                    f"{session['trade_date']}:{index:05d}",
                    {
                        "trade_date": session["trade_date"].isoformat(),
                        "decision_ts": session["decision_ts"].isoformat(),
                        "symbols": group,
                    },
                    priority=30,
                )
    if not _all_complete(run_id, phase, "decision_snapshot"):
        _update_progress(run_id, phase)
        return

    # Exact verification partitions are created by decision processors. A date can
    # be selected only when all of them have completed.
    for session in sessions:
        trade_date = session["trade_date"].isoformat()
        date_decision = fetch_one(
            """
            select count(*)::int total,count(*) filter(where status='completed')::int completed
              from work_partitions
             where run_id=%s and phase=%s and stage='decision_snapshot' and partition_key like %s
            """,
            (run_id, phase, trade_date + ":%"),
        )
        if not date_decision or date_decision["total"] == 0 or date_decision["total"] != date_decision["completed"]:
            continue
        pending_verify = fetch_one(
            """
            select count(*)::int total,
                   count(*) filter(where status='completed')::int completed
              from work_partitions
             where run_id=%s and phase=%s and stage='signal_verify' and partition_key like %s
            """,
            (run_id, phase, trade_date + ":%"),
        )
        if pending_verify and pending_verify["total"] != pending_verify["completed"]:
            continue
        enqueue(
            run_id, phase, "select_date", trade_date,
            {"trade_date": trade_date}, priority=40,
        )

    if not _all_complete(run_id, phase, "select_date"):
        _update_progress(run_id, phase)
        return

    targets = fetch_all(
        """
        select id,trade_date,symbol,cohort,metadata
          from execution_targets
         where run_id=%s and phase=%s
         order by trade_date,symbol,
                  case cohort when 'signal' then 0 when 'common_stock_signal' then 1
                              when 'expanded_signal' then 2 when 'liquidity_matched' then 3 else 4 end,
                  id
        """,
        (run_id, phase),
    )
    # The same symbol-day may appear in the primary and sensitivity cohorts. Raw
    # SIP trades/quotes are identical, so download them once and let all cohort
    # simulations reference the durable source target.
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
                    cur.execute(
                        "update execution_targets set metadata=%s where id=%s",
                        (Jsonb(metadata), target_id),
                    )
            for data_type in ("trades", "quotes"):
                if not fetch_one(
                    "select status from work_partitions where run_id=%s and phase=%s and stage='execution_raw' and partition_key=%s",
                    (run_id, phase, f"{source_id}:{data_type}"),
                ):
                    enqueue(
                        run_id, phase, "execution_raw", f"{source_id}:{data_type}",
                        {"execution_target_id": source_id, "data_type": data_type}, priority=50,
                    )
        conn.commit()

    raw_status = {
        str(row["source_id"]): (int(row["raw_total"]), int(row["raw_completed"]))
        for row in fetch_all(
            """
            select split_part(partition_key,':',1) source_id,
                   count(*)::int raw_total,
                   count(*) filter(where status='completed')::int raw_completed
              from work_partitions
             where run_id=%s and phase=%s and stage='execution_raw'
             group by split_part(partition_key,':',1)
            """,
            (run_id, phase),
        )
    }
    for target in targets:
        target_id = str(target["id"])
        source_id = raw_source_by_target[target_id]
        raw_total, raw_completed = raw_status.get(source_id, (0, 0))
        if raw_total == 2 and raw_completed == 2:
            enqueue(
                run_id, phase, "simulate", target_id,
                {"execution_target_id": target_id, "raw_source_target_id": source_id}, priority=60,
            )

    if targets and not _all_complete(run_id, phase, "simulate"):
        _update_progress(run_id, phase)
        return

    overnight = _stage_counts(run_id, phase, "overnight_followup")
    if overnight["total"] > 0 and overnight["completed"] != overnight["total"]:
        _update_progress(run_id, phase)
        return

    if _stage_counts(run_id, phase, "report")["total"] == 0:
        enqueue(run_id, phase, "report", phase, {}, priority=90)
    _update_progress(run_id, phase)


def _update_progress(run_id: str, phase: str) -> None:
    stages = [
        "catalogue", "massive_reference", "calendar", "splits", "daily_bars",
        "decision_snapshot", "signal_verify", "select_date", "execution_raw", "simulate",
        "overnight_followup", "report",
    ]
    progress: dict[str, Any] = {stage: _stage_counts(run_id, "primary" if stage in {"catalogue", "massive_reference"} else phase, stage) for stage in stages}
    progress["phase"] = phase
    with connection() as conn, conn.cursor() as cur:
        cur.execute("update research_runs set progress=%s,updated_at=now() where id=%s", (Jsonb(progress), run_id))
        conn.commit()
