# Alpaca 13.8% Execution Research Lab v1.1.1

A separate, research-only application that mines historical Alpaca SIP and Massive reference data and tests one frozen finding:

> At 17:00 Europe/London, select up to five US equities whose last eligible SIP trade is strictly more than 13.776879223878035% above the previous regular-session close.

The app has no trading capability.


## v1.1.1 operational fix

- Corrects the Massive active/inactive ticker pagination transition.
- Prevents the first inactive-ticker page from being fetched repeatedly.
- Preserves and resumes the saved Massive page cursor.
- Resets the displayed Massive reference row counter to actual pages processed after resume.
- Does not change the frozen v1.1.0 research protocol or its protocol hash.
- Existing v1.1.0 quarterly runs can resume under v1.1.1; no new run is required.

## What changed in v1.1.1

The 2024–2025 primary period is processed in eight pre-registered three-month tranches:

1. 2024 Q1
2. 2024 Q2
3. 2024 Q3
4. 2024 Q4
5. 2025 Q1
6. 2025 Q2
7. 2025 Q3
8. 2025 Q4

After every tranche the app creates:

- a standalone-quarter report;
- a cumulative report from 1 January 2024 through that quarter;
- a data-quality summary;
- the full trade-level export;
- a pre-registered early-futility assessment.

A favourable interim report can never validate the strategy. Only completion of all eight quarters and passage of the complete frozen primary gate can unlock the 2026 confirmation period.

## Pre-registered early-futility rule

The study stops automatically and is classified `rejected_early_for_futility` only when cumulative results satisfy every condition:

- at least 30 completed base-case trades;
- at least 15 independent trading dates;
- at least 10 symbols;
- negative base-case net P&L;
- negative base-case mean return;
- negative conservative-case net P&L;
- the upper end of the date-block bootstrap 95% confidence interval is non-positive.

This is a negative-only stopping rule. There is no positive early-stopping or early-validation rule.

## Execution cases

The signal and execution assumptions remain frozen:

- US$500 requested position;
- maximum five trades per day;
- 5/30/60-second optimistic/base/conservative reaction delays;
- SIP NBBO execution and displayed-liquidity constraints;
- additional adverse slippage by scenario;
- 5% stop from actual fill with realistic gap execution;
- target at 150% of the previous close;
- 15:55 New York time exit;
- effective-dated regulatory fees;
- no leverage or position recycling.

See `FROZEN_PROTOCOL.md` for the complete specification.

## Resume behaviour

Every expensive operation is stored as an idempotent `work_partitions` row with:

- a unique partition key including the tranche;
- status and attempt count;
- durable API cursor;
- row count;
- heartbeat;
- automatic stale-worker recovery;
- exponential retry;
- manual **Retry and resume** for exhausted attempts.

Completed quarters, data pages, simulations and reports are not repeated after a normal restart.

## UI

The responsive control room shows:

- current phase and quarter;
- active partition and heartbeat age;
- a visible stale-partition warning;
- stage-level progress;
- the locked eight-quarter sequence;
- standalone and cumulative report downloads;
- futility status;
- safe cancel/resume controls;
- final primary and confirmation reports.

## Independent infrastructure

Deploy with its own:

- private GitHub repository;
- Supabase project;
- Render web service;
- Render background worker;
- Storage bucket.

It must not share tables, workers or migrations with the Market Data Miner.

## Important v1.0 upgrade rule

Adding quarterly looks and a futility rule changes the pre-registered protocol. Existing v1.0 full runs remain preserved but cannot be continued as valid v1.1 studies. Migration 002 permits one full run per immutable protocol hash, so create a new v1.1 full run after deployment.

A v1.0 smoke test may simply be replaced with a new v1.1 smoke test.
