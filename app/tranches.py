from __future__ import annotations

from datetime import date
from typing import Any

from psycopg.types.json import Jsonb

from app.db import connection, fetch_all, fetch_one
from app.protocol import PROTOCOL, protocol_hash


PRIMARY_TRANCHES: tuple[dict[str, Any], ...] = tuple(PROTOCOL["quarterly_tranches"]["primary"])
CONFIRMATION_TRANCHES: tuple[dict[str, Any], ...] = tuple(PROTOCOL["quarterly_tranches"]["confirmation"])


def partition_prefix(tranche_key: str) -> str:
    return f"{tranche_key}|"


def scoped_key(tranche_key: str, key: str) -> str:
    return partition_prefix(tranche_key) + key


def seed_tranches(run_id: str, run_kind: str) -> None:
    if run_kind == "smoke":
        definitions = [
            {
                "phase": "primary",
                "tranche_key": "smoke",
                "sequence_no": 1,
                "label": "Smoke test",
                "start": "2024-01-02",
                "end_inclusive": "2024-01-12",
            }
        ]
    else:
        definitions = [
            {"phase": "primary", **item} for item in PRIMARY_TRANCHES
        ] + [
            {"phase": "confirmation", **item} for item in CONFIRMATION_TRANCHES
        ]
    with connection() as conn, conn.cursor() as cur:
        cur.execute("select count(*)::int total from research_tranches where run_id=%s", (run_id,))
        already_seeded = int(cur.fetchone()["total"]) > 0
        for item in definitions:
            cur.execute(
                """
                insert into research_tranches(
                    run_id,phase,tranche_key,sequence_no,label,start_date,end_date,status,protocol_hash
                ) values (%s,%s,%s,%s,%s,%s,%s,'locked',%s)
                on conflict(run_id,phase,tranche_key) do nothing
                """,
                (
                    run_id,item["phase"],item["tranche_key"],item["sequence_no"],item["label"],
                    date.fromisoformat(item["start"]),date.fromisoformat(item["end_inclusive"]),protocol_hash(),
                ),
            )
        if not already_seeded:
            first = definitions[0]
            cur.execute(
                """
                update research_tranches
                   set status='running',started_at=coalesce(started_at,now()),updated_at=now()
                 where run_id=%s and phase=%s and tranche_key=%s and status='locked'
                """,
                (run_id, first["phase"], first["tranche_key"]),
            )
            cur.execute(
                "update research_runs set current_tranche_key=%s where id=%s and current_tranche_key is null",
                (first["tranche_key"], run_id),
            )
        conn.commit()


def current_tranche(run_id: str, phase: str, current_key: str | None = None) -> dict[str, Any] | None:
    if current_key:
        row = fetch_one(
            "select * from research_tranches where run_id=%s and phase=%s and tranche_key=%s and status='running'",
            (run_id, phase, current_key),
        )
        if row:
            return row
    return fetch_one(
        """
        select * from research_tranches
         where run_id=%s and phase=%s and status='running'
         order by sequence_no limit 1
        """,
        (run_id, phase),
    )


def tranche_rows(run_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        "select * from research_tranches where run_id=%s order by phase,sequence_no",
        (run_id,),
    )


def mark_tranche_complete(
    run_id: str,
    tranche_key: str,
    *,
    standalone_path: str,
    cumulative_path: str,
    standalone_metrics: dict[str, Any],
    cumulative_metrics: dict[str, Any],
    futility: dict[str, Any],
) -> None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            update research_tranches
               set status=%s,standalone_report_object_path=%s,cumulative_report_object_path=%s,
                   standalone_metrics=%s,cumulative_metrics=%s,futility_assessment=%s,
                   completed_at=now(),updated_at=now()
             where run_id=%s and tranche_key=%s
            """,
            (
                "futility_stopped" if futility.get("stop") else "completed",
                standalone_path,cumulative_path,Jsonb(standalone_metrics),Jsonb(cumulative_metrics),
                Jsonb(futility),run_id,tranche_key,
            ),
        )
        conn.commit()


def advance_to_next_tranche(run_id: str, phase: str, completed_sequence: int) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            select * from research_tranches
             where run_id=%s and phase=%s and sequence_no>%s and status='locked'
             order by sequence_no limit 1 for update
            """,
            (run_id, phase, completed_sequence),
        )
        row = cur.fetchone()
        if not row:
            conn.commit()
            return None
        cur.execute(
            """
            update research_tranches
               set status='running',started_at=coalesce(started_at,now()),updated_at=now()
             where id=%s
            """,
            (row["id"],),
        )
        cur.execute(
            """
            update research_runs
               set current_tranche_key=%s,status=%s,updated_at=now()
             where id=%s
            """,
            (row["tranche_key"], "confirmation_running" if phase == "confirmation" else "running", run_id),
        )
        conn.commit()
        return row


def finalise_tranche(
    run_id: str,
    phase: str,
    tranche_key: str,
    sequence_no: int,
    *,
    standalone_path: str,
    cumulative_path: str,
    standalone_metrics: dict[str, Any],
    cumulative_metrics: dict[str, Any],
    futility: dict[str, Any],
) -> dict[str, Any]:
    """Atomically complete one tranche and choose the next state.

    The row lock makes report-partition retries idempotent: a retry after the
    transition has committed cannot activate or skip an additional tranche.
    """
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            "select * from research_tranches where run_id=%s and phase=%s and tranche_key=%s for update",
            (run_id, phase, tranche_key),
        )
        tranche = cur.fetchone()
        if not tranche:
            raise RuntimeError("Research tranche missing")
        if tranche["status"] in {"completed", "futility_stopped"}:
            conn.commit()
            return {"already_finalised": True, "next_tranche_key": None}

        cur.execute(
            """
            update research_tranches
               set status=%s,standalone_report_object_path=%s,cumulative_report_object_path=%s,
                   standalone_metrics=%s,cumulative_metrics=%s,futility_assessment=%s,
                   completed_at=now(),updated_at=now()
             where id=%s
            """,
            (
                "futility_stopped" if futility.get("stop") else "completed",
                standalone_path,cumulative_path,Jsonb(standalone_metrics),Jsonb(cumulative_metrics),
                Jsonb(futility),tranche["id"],
            ),
        )
        cur.execute("select cancel_requested from research_runs where id=%s for update", (run_id,))
        run = cur.fetchone()
        cancelled = bool(run and run["cancel_requested"])

        if futility.get("stop"):
            cur.execute(
                """
                update research_runs
                   set status='early_futility_stopped',early_futility_stopped=true,
                       early_futility_reason=%s,final_classification='rejected_early_for_futility',
                       current_tranche_key=null,completed_at=now(),updated_at=now()
                 where id=%s
                """,
                (Jsonb(futility),run_id),
            )
            conn.commit()
            return {"already_finalised": False, "next_tranche_key": None, "futility_stopped": True}

        cur.execute(
            """
            update research_runs
               set completed_primary_tranches=case when %s='primary' then greatest(completed_primary_tranches,%s)
                                                  else completed_primary_tranches end,
                   updated_at=now()
             where id=%s
            """,
            (phase,sequence_no,run_id),
        )
        cur.execute(
            """
            select * from research_tranches
             where run_id=%s and phase=%s and sequence_no>%s and status='locked'
             order by sequence_no limit 1 for update
            """,
            (run_id,phase,sequence_no),
        )
        next_row=cur.fetchone()
        if next_row:
            if not cancelled:
                cur.execute(
                    """
                    update research_tranches
                       set status='running',started_at=coalesce(started_at,now()),updated_at=now()
                     where id=%s
                    """,
                    (next_row["id"],),
                )
            cur.execute(
                """
                update research_runs
                   set current_tranche_key=%s,
                       status=case when %s then status when %s='confirmation' then 'confirmation_running' else 'running' end,
                       updated_at=now()
                 where id=%s
                """,
                (next_row["tranche_key"],cancelled,phase,run_id),
            )
        else:
            cur.execute(
                "update research_runs set current_tranche_key=null,updated_at=now() where id=%s",
                (run_id,),
            )
        conn.commit()
        return {
            "already_finalised": False,
            "next_tranche_key": str(next_row["tranche_key"]) if next_row else None,
            "cancelled": cancelled,
        }
