from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from typing import Any, Iterator, Sequence

from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings

_settings = get_settings()
_pool = ConnectionPool(
    conninfo=_settings.db_dsn,
    min_size=1,
    max_size=_settings.db_pool_size,
    kwargs={"row_factory": dict_row, "autocommit": False},
    open=False,
)


def open_pool() -> None:
    if _pool.closed:
        _pool.open(wait=True)


def close_pool() -> None:
    if not _pool.closed:
        _pool.close()


@contextlib.contextmanager
def connection() -> Iterator[Connection[Any]]:
    open_pool()
    with _pool.connection() as conn:
        yield conn


def fetch_one(sql: str, params: Sequence[Any] | None = None) -> dict[str, Any] | None:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
        conn.rollback()
        return row


def fetch_all(sql: str, params: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        conn.rollback()
        return list(rows)


def execute(sql: str, params: Sequence[Any] | None = None) -> int:
    with connection() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        count = cur.rowcount
        conn.commit()
        return count


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
