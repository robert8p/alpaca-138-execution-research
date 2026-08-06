# Alpaca 13.8% Execution Research Lab v1.1.2

A separate, research-only application that mines historical Alpaca SIP and Massive reference data and tests one frozen finding:

> At 17:00 Europe/London, select up to five US equities whose last eligible SIP trade is strictly more than 13.776879223878035% above the previous regular-session close.

The app has no trading capability.

## v1.1.2 operational repair

v1.1.0 attempted to enrich the study by crawling Massive's complete active and inactive ticker catalogues. v1.1.1 corrected an infinite page transition, but the catalogue-wide design still examined hundreds of thousands of irrelevant rows.

v1.1.2 replaces that stage with exact-symbol, resumable batches:

- only symbols already present in the run are queried;
- each symbol is checked as active, with an inactive fallback only when necessary;
- partitions contain 100 run symbols by default;
- progress checkpoints every 10 symbols;
- row counts represent instruments actually matched, not unrelated API rows examined;
- the legacy `all-tickers` partition is retired automatically by migration 003;
- completed catalogue, calendar, split and Daily Bars partitions are preserved;
- the frozen v1.1.0 protocol and protocol hash are unchanged;
- the existing quarterly run resumes; no new run is required.

## Quarterly evidence sequence

The 2024–2025 primary period is processed through eight pre-registered three-month tranches:

1. 2024 Q1
2. 2024 Q2
3. 2024 Q3
4. 2024 Q4
5. 2025 Q1
6. 2025 Q2
7. 2025 Q3
8. 2025 Q4

After every tranche the app creates standalone and cumulative reports. Favourable interim evidence cannot validate the strategy. Only the complete primary gate can unlock the 2026 confirmation period.

## Resume behaviour

Every expensive operation is an idempotent `work_partitions` row with a durable cursor, row count, heartbeat, retry state and unique partition key. Massive reference batches save `next_index`, `examined`, `matched` and `not_found` after every ten symbols.

## Independent infrastructure

Deploy with its own private GitHub repository, Supabase project, Render web service, Render background worker and Storage bucket. It must not share infrastructure with the Market Data Miner.

See `FROZEN_PROTOCOL.md` for the immutable research specification and `DEPLOYMENT.md` for the upgrade sequence.
