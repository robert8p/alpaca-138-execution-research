# Troubleshooting

## The web service exits immediately

Check `APP_PASSWORD` and `SESSION_SECRET`. The password cannot be a placeholder and the session secret must contain at least 32 characters.

## The worker exits immediately

The worker requires `ALPACA_API_KEY`, `ALPACA_API_SECRET` and `MASSIVE_API_KEY`.

## The progress bar appears stationary

Open the stage details. Large all-symbol bar and decision partitions can run for a long time while their page cursor advances. Check the worker log for current partition keys and Supabase `work_partitions.heartbeat_at`.

## A run failed after hours or days

Select **Retry and resume** on the same run. Completed partitions, raw pages and simulations are idempotent and are not repeated unnecessarily.

## The full-run button produces a database uniqueness error

The schema permits one full confirmatory run. Use the existing run. This blocks accidental repeated testing of the same historical periods.

## Confirmation cannot be opened

That is deliberate unless every primary gate passed. A positive P&L alone is insufficient.

## A forced overnight trade has a later price in metadata

The later quote is diagnostic only. The trade remains unresolved for the intraday gate because the intended 15:55 ET liquidation was not executable.

## Fee or quantity questions

Research fee schedules are hard-coded and included in the protocol hash. Do not add a fee environment variable. The primary simulation uses whole shares only; historical fractional eligibility is not inferred from current asset metadata.
