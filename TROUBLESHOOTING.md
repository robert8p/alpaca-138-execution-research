# Troubleshooting — v1.1.5

## Daily Bars fails with `invalid symbol`

Deploy v1.1.5. Alpaca may catalogue synthetic/internal symbols that its historical stock-bars endpoint rejects. The worker now audits the rejected symbol, excludes it from later market-data cohorts and continues the rest of the batch.

## Expected recovery for the production case

`2024_q1|batch-00039` resumes after excluding `E018385`. The other symbols are downloaded normally. Use **Retry and resume** once after the worker is running v1.1.5.

## Other HTTP 400 errors

They are not silently ignored. Inspect `work_partitions.last_error`, because malformed dates, feed entitlement errors or other bad requests remain genuine failures.
