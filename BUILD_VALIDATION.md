# Build validation — v1.1.5

- Operational change: Alpaca HTTP 400 `invalid symbol` errors are audited per symbol rather than exhausting a full multi-symbol Daily Bars or Decision Snapshot partition.
- Verified production case: `E018385` inside `2024_q1|batch-00039`.
- The rejected symbol is removed from later market-data cohorts; the remaining symbols continue idempotently.
- Daily-bar page tokens are reset only when the query symbol set changes; previously written rows are upserted and the final unique count is recomputed.
- Research protocol version: 1.1.0, unchanged.
- Protocol hash: `ddce449bdd0c6dc6f720e67ff6964bb1dbbe37d6b7429c5455eded1afd630ca2`, unchanged.
- Existing runs and completed partitions resume in place.
- No database migration required.
- 70 offline tests passed.
