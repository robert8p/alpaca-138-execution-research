from __future__ import annotations

import hashlib
from pathlib import Path

from app.db import connection


def run_migrations() -> None:
    root = Path(__file__).resolve().parents[1] / "migrations"
    with connection() as conn, conn.cursor() as cur:
        cur.execute(
            """
            create table if not exists schema_migrations (
                filename text primary key,
                sha256 text not null,
                applied_at timestamptz not null default now()
            )
            """
        )
        conn.commit()

    for path in sorted(root.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        with connection() as conn, conn.cursor() as cur:
            cur.execute("select sha256 from schema_migrations where filename=%s", (path.name,))
            row = cur.fetchone()
            if row:
                if row["sha256"] != digest:
                    raise RuntimeError(f"Applied migration changed: {path.name}")
                conn.rollback()
                continue
            cur.execute(sql)
            cur.execute(
                "insert into schema_migrations(filename,sha256) values (%s,%s)",
                (path.name, digest),
            )
            conn.commit()


if __name__ == "__main__":
    run_migrations()
    print("Migrations complete")
