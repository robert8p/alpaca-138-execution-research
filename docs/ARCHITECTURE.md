# Architecture

## Independence boundary

This application has no dependency on the Market Data Miner or any earlier gainer scanner. It expects:

- a new private GitHub repository;
- a new Supabase project and private Storage bucket;
- one new Render web service;
- one new Render background worker.

Only the market-data provider accounts may be reused. Their account-level rate limits remain shared.

## Research workflow

```text
Alpaca asset catalogue + Massive reference catalogue
                         ↓
Alpaca calendar + Massive split history
                         ↓
Raw SIP daily bars for every selected symbol
                         ↓
Decision-time one-minute cross-section at 17:00 Europe/London
                         ↓
Exact last eligible SIP-trade verification
                         ↓
Daily rank and maximum-five selection
                         ↓
Raw SIP trades and quotes for signal, sensitivity and control targets
                         ↓
Optimistic / base / conservative execution simulation
                         ↓
Frozen gate, audit tables and private report ZIP
```

A daily bar's future high is never used to decide which symbol-day enters the signal test. One-minute bars completed by the decision timestamp are only an efficient, non-lookahead screen for exact trade verification.

## Resume model

`work_partitions` is the durable queue. Each item has a unique `(run_id, phase, stage, partition_key)` key, attempts, page cursor, row count and heartbeat. Workers claim with `FOR UPDATE SKIP LOCKED`.

- API pages are checkpointed after durable database/Storage writes.
- Stale running partitions are reclaimed.
- Automatic retries use exponential backoff.
- Manual **Retry and resume** resets exhausted attempts without deleting completed work.
- Cancelled queued/running work is marked for safe requeue.
- Raw trades/quotes are compressed in Supabase Storage and indexed in PostgreSQL.
- Duplicate symbol-days across the primary and sensitivity cohorts share the same raw SIP cache.

## Sealed confirmation

The confirmation period cannot be queued until the primary gate passes. The complete protocol is canonicalised and SHA-256 hashed. The hash is checked at unlock, during confirmation orchestration and when the report is built. Any mismatch produces `invalid_process`.

## Security

- Browser access uses a password-protected session.
- The Supabase service-role key is server-side only.
- Storage is private and reports are delivered through expiring signed URLs.
- No order-placement endpoint or broker trading method exists.
