# Deployment — v1.1.2 exact-symbol Massive repair

## Resume the currently affected run

1. Suspend `alpaca-138-research-worker` in Render and wait until it stops.
2. Replace the GitHub repository contents with v1.1.2 while preserving the hidden `.git` folder.
3. Commit and push.
4. Deploy `alpaca-138-research-web` first.
5. Confirm `/health` reports version `1.1.2`, database `ok`, and latest migration `003_massive_symbol_batches.sql`.
6. Resume and deploy `alpaca-138-research-worker`.
7. Do not cancel the run and do not create another run.

Migration 003 retires the legacy `massive_reference / all-tickers` partition automatically. The worker then creates exact-symbol batches from the instruments already in the run. Existing completed work is not deleted.

## Expected UI after the repair

Massive Reference changes from one giant partition to many small partitions, usually about one partition per 100 run symbols. The overall percentage may temporarily decrease because the UI now represents the real remaining work. Daily Bars should still show the same completed count as before.

A healthy active Massive partition should show no more than 100 matched rows. Its cursor records:

```json
{
  "next_index": 40,
  "examined": 40,
  "matched": 37,
  "not_found": 3
}
```

## Environment variable

The Blueprint adds:

```text
SYMBOL_BATCH_SIZE_MASSIVE=100
```

No credential changes are required.

## New deployment

1. Create a separate Supabase project and private GitHub repository.
2. Upload this ZIP's contents to the repository root.
3. Create a Render Blueprint from the repository.
4. Enter the Supabase, Alpaca and Massive credentials.
5. Deploy the web service first so migrations 001–003 run.
6. Confirm `/health` reports version `1.1.2` and database `ok`.
7. Deploy the worker.
8. Run the smoke test before starting a full study.

## Health check

Expected structure:

```json
{
  "status": "ok",
  "version": "1.1.2",
  "role": "research_only_no_trading",
  "database": "ok",
  "latest_migration": {
    "filename": "003_massive_symbol_batches.sql"
  },
  "protocol_hash": "..."
}
```

The protocol hash must remain unchanged from v1.1.0/v1.1.1.

## Verify the repaired stage in Supabase

```sql
select partition_key,status,row_count,cursor,heartbeat_at,
       now()-heartbeat_at as heartbeat_age
from work_partitions
where run_id=(select id from research_runs order by created_at desc limit 1)
  and stage='massive_reference'
order by partition_key;
```

Expected:

- `all-tickers` is completed with `retired_legacy_all_tickers=true`;
- new `symbol-batch-00000`, `symbol-batch-00001`, etc. partitions exist;
- each completed batch has `examined` no greater than the batch size;
- the active batch has a fresh heartbeat and advancing `next_index`.

## Render configuration

### Web

```text
Type: Web Service
Runtime: Docker
Plan: Starter
Pre-deploy: python -m app.migrate
Health: /health
```

### Worker

```text
Type: Background Worker
Runtime: Docker
Plan: Pro
Command: python -m app.worker
Disk: 10 GB mounted at /var/data
Instances: 1
```

The worker intentionally has no `maxShutdownDelaySeconds`, because Render does not support that field on a service with a persistent disk.
