# Architecture — v1.1.2

## Research boundary

The app is research-only. The threshold, execution scenarios, quarterly sequence, futility gate and confirmation lock are hard-coded in `app/protocol.py` and protected by the protocol hash.

## Durable orchestration

Every unit of work is an idempotent database partition. Workers claim partitions with `FOR UPDATE SKIP LOCKED`, checkpoint cursors and row counts, and automatically reclaim stale work.

## Massive reference enrichment

After the Alpaca catalogue is stored, the orchestrator selects only symbols belonging to the run and creates `symbol-batch-*` partitions. Each partition contains up to `SYMBOL_BATCH_SIZE_MASSIVE` symbols.

For each symbol:

1. Query Massive's All Tickers endpoint with the exact ticker and `active=true`.
2. If no exact result exists, query the same ticker with `active=false`.
3. Update only that run's matching instrument.
4. Checkpoint every ten symbols.

The worker never crawls Massive's global ticker catalogue. Migration 003 retires legacy `all-tickers` partitions from v1.1.0/v1.1.1.

## Existing data preservation

The operational migration does not alter the frozen protocol or delete research facts. Completed Alpaca Daily Bars, calendars, corporate actions and catalogue rows remain intact.
