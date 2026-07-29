# Alpaca 13.8% Execution Research Lab v1.0.0

A completely independent, deployable research application that mines the historical US-equity data needed to test one frozen signal:

> At 17:00 Europe/London, buy up to five stocks whose last available SIP trade is strictly more than 13.776879223878035% above the previous regular-session close.

It then performs an execution-aware historical backtest using SIP trades and NBBO quotes. It contains no order-placement code.

## Why this app exists

The earlier matched-control study showed unusually strong discrimination, but could not establish market-wide signal frequency, fillability or profitability. This app tests those missing questions directly across the full Alpaca universe and a previously unused historical period.

## Research design

- Exact frozen signal and threshold.
- Primary 2024–2025 test.
- Locked 1 January–19 April 2026 confirmation.
- Full decision-time cross-section; no future-high or future-volume prefilter.
- Exact SIP trade verification at the decision time.
- Maximum five signals each day, ranked by exact return.
- Optimistic, base and conservative NBBO execution scenarios.
- Same-date liquidity-matched and deterministic random controls.
- Effective-dated SEC, FINRA TAF and CAT LLC fees; broker-specific extras are disclosed as unmodelled.
- Common-stock-only and expanded-universe sensitivities.
- Whole-share execution only; fractional eligibility is not assumed historically.
- Pre-registered profitability, uncertainty, drawdown and concentration gates.

See `FROZEN_PROTOCOL.md`.

## Resume and recovery

Every expensive unit is an idempotent database partition with:

- a unique run/phase/stage/key;
- a durable page cursor;
- saved row count;
- heartbeat and stale-worker reclamation;
- exponential retry up to eight attempts;
- compressed raw-page objects in private Supabase Storage;
- deterministic inserts and exports.

A Render restart resumes the same run. Use **Retry and resume** after a permanent failure; do not create a replacement run.

## Services

- `alpaca-138-research-web`: password-protected research dashboard, migrations and signed report downloads.
- `alpaca-138-research-worker`: catalogue, historical mining, exact signal verification, raw SIP collection, simulations and reports.

The smoke run adds one explicitly labelled `smoke_probe` on its first session when needed. It proves the raw-data and simulation plumbing but is never treated as a qualifying signal or included in strategy P&L.
- A new Supabase project used only by this app.

## Output package

Each phase creates a private ZIP containing:

- `BACKTEST_REPORT.md`;
- `backtest_triggers.csv/.parquet`;
- `backtest_trades.csv/.parquet`;
- `backtest_days.csv/.parquet`;
- `strategy_summary.csv/.parquet`;
- `preregistered_execution_spec.json`;
- `profitability_gate.json`;
- `data_quality.json`;
- `manifest.json`.

## Required data plans

- Alpaca historical SIP access through Algo Trader Plus.
- Massive Stocks Starter or higher, because complete split history is required from January 2024. The app refuses to start until both entitlements are explicitly acknowledged in the worker environment.

## Deployment

Follow `DEPLOYMENT.md`. Begin with the smoke test. Do not open the confirmation period unless the dashboard exposes the locked-confirmation button after a primary pass.
