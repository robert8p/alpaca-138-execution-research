# Troubleshooting — v1.1.2

## Massive Reference shows hundreds of thousands or millions of rows

That is the retired catalogue-wide implementation. Suspend the worker and deploy v1.1.2. Migration 003 retires `all-tickers`; no manual SQL requeue and no new research run are required.

## Massive Reference now shows many partitions

Correct behaviour. Each `symbol-batch-*` partition contains up to 100 symbols already present in this run. The row count represents symbols matched by Massive, while the cursor separately records symbols examined and not found.

## The overall percentage decreased after deployment

This can happen once because the old single Massive partition is replaced by the true number of symbol batches. It does not mean completed Daily Bars were lost. Check that their completed count is unchanged.

## The percentage has not moved

Check the active partition heartbeat and cursor. During Massive enrichment, `next_index` should advance from 0 toward 100. A heartbeat under 20 minutes is active; a stale partition is reclaimed automatically.

## Run status is failed

Read the last error, correct the credential, entitlement, provider quota or database problem, then select **Retry and resume**. Completed work remains complete.

## HTTP 429

Reduce `MASSIVE_REQUESTS_PER_MINUTE`, redeploy the worker and resume the same run.

## Missing migration 003

Deploy the web service before the worker and confirm `/health` lists `003_massive_symbol_batches.sql`.
