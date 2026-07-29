from __future__ import annotations

import json
import os
import socket
import traceback
from datetime import timedelta
from typing import Any

from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db import connection, utc_now

settings = get_settings()
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"


def enqueue(
    run_id: str,
    phase: str,
    stage: str,
    partition_key: str,
    params: dict[str, Any],
    *,
    priority: int = 100,
) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            insert into work_partitions(run_id,phase,stage,partition_key,params,priority,max_attempts)
            values (%s,%s,%s,%s,%s,%s,%s)
            on conflict(run_id,phase,stage,partition_key) do nothing
            """,
            (run_id, phase, stage, partition_key, Jsonb(params), priority, settings.max_partition_attempts),
        )
        conn.commit()


def claim() -> dict[str, Any] | None:
    stale_before = utc_now() - timedelta(minutes=settings.stale_partition_minutes)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update work_partitions
               set status='queued',worker_id=null,heartbeat_at=null,updated_at=now(),
                   last_error=coalesce(last_error,'') || E'\nReclaimed stale running partition'
             where status='running' and heartbeat_at < %s
            """,
            (stale_before,),
        )
        cur.execute(
            """
            select p.*
              from work_partitions p
              join research_runs r on r.id=p.run_id
             where p.status='queued'
               and (p.next_attempt_at is null or p.next_attempt_at <= now())
               and r.cancel_requested=false
               and r.status in ('running','confirmation_running')
             order by p.priority asc,p.created_at asc
             for update skip locked
             limit 1
            """
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        cur.execute(
            """
            update work_partitions
               set status='running',worker_id=%s,heartbeat_at=now(),started_at=coalesce(started_at,now()),
                   attempts=attempts+1,updated_at=now()
             where id=%s
             returning *
            """,
            (WORKER_ID, row["id"]),
        )
        claimed = cur.fetchone()
        conn.commit()
        return claimed


def heartbeat(partition_id: str, *, cursor: dict[str, Any] | None = None, row_count: int | None = None) -> None:
    fields = ["heartbeat_at=now()", "updated_at=now()"]
    params: list[Any] = []
    if cursor is not None:
        fields.append("cursor=%s")
        params.append(Jsonb(cursor))
    if row_count is not None:
        fields.append("row_count=%s")
        params.append(row_count)
    params.append(partition_id)
    with connection() as conn, conn.cursor() as cur:
        cur.execute(f"update work_partitions set {','.join(fields)} where id=%s", params)
        conn.commit()


def complete(partition_id: str, *, row_count: int = 0, cursor: dict[str, Any] | None = None) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update work_partitions
               set status='completed',completed_at=now(),heartbeat_at=now(),updated_at=now(),
                   row_count=%s,cursor=%s,last_error=null
             where id=%s
            """,
            (row_count, Jsonb(cursor or {"finished": True}), partition_id),
        )
        conn.commit()


def fail(partition: dict[str, Any], exc: BaseException) -> None:
    attempts = int(partition.get("attempts") or 1)
    max_attempts = int(partition.get("max_attempts") or settings.max_partition_attempts)
    retry = attempts < max_attempts
    delay_seconds = min(1800, 15 * (2 ** min(attempts - 1, 7)))
    error = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))[-12000:]
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update work_partitions
               set status=%s,last_error=%s,worker_id=null,heartbeat_at=now(),updated_at=now(),
                   next_attempt_at=case when %s then now()+(%s || ' seconds')::interval else null end
             where id=%s
            """,
            ("queued" if retry else "failed", error, retry, delay_seconds, partition["id"]),
        )
        if not retry:
            cur.execute(
                "update research_runs set status='failed',error=%s,updated_at=now() where id=%s",
                (f"Permanent partition failure: {partition['stage']} {partition['partition_key']}", partition["run_id"]),
            )
        conn.commit()


def is_cancelled(run_id: str) -> bool:
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select cancel_requested from research_runs where id=%s", (run_id,))
        row = cur.fetchone()
        conn.rollback()
        return bool(row and row["cancel_requested"])


def cancel_running_for_run(run_id: str) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "update work_partitions set status='cancelled',updated_at=now() where run_id=%s and status in ('queued','running')",
            (run_id,),
        )
        conn.commit()
