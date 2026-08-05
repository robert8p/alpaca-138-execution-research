# Troubleshooting — v1.1.1

## The percentage has not moved

A progress bar advances when a partition completes. Check the heartbeat panel:

- **Worker active:** the partition heartbeat is recent.
- **Possible stale partition:** heartbeat is older than the configured 20-minute threshold.
- **Worker between partitions:** no partition is currently claimed.

Also inspect Render worker logs for `Processing partition`, `Partition completed`, `Partition failed` or `Worker loop error`.

## A quarter appears stuck after simulations

The app waits for all raw SIP, simulation and overnight-follow-up partitions before creating the tranche report. Inspect failed or queued partitions in Supabase. Do not start another full run.

## Run status is failed

1. Read the last error in the dashboard or Render logs.
2. Correct the credential, entitlement, quota or database issue.
3. Select **Retry and resume**.

Attempts and cursors are reset only for failed/cancelled partitions. Completed work remains untouched.

## Old v1.0 run reports protocol mismatch

This is expected after upgrading. Quarterly looks and futility stopping constitute a new protocol. Create a new v1.1 full run. Migration 002 permits one full run per protocol hash, so the old run remains preserved.

## Early futility stopped the study

This is a final pre-registered rejection for this protocol, not a technical failure. Download the latest cumulative report. The confirmation period remains inaccessible.

## A quarter is profitable but the app continues

Correct behaviour. Positive interim results cannot validate the strategy. All eight primary quarters must complete and the final primary gate must pass.

## Render Blueprint rejects maxShutdownDelaySeconds

Use the v1.1 package. The worker has a persistent disk and therefore does not include `maxShutdownDelaySeconds`.

## HTTP 429

Reduce the relevant request limit, redeploy the worker and resume the same run. Do not clear the database.

## Missing table research_tranches

Deploy the web service first and verify migration `002_quarterly_tranches.sql` completed before starting the worker.

## UI remains at 86% while Massive reference shows millions of rows

This is the v1.1.0 active/inactive ticker pagination-loop defect. A fresh heartbeat does not mean useful progress: the same first inactive-ticker page is being processed repeatedly. Upgrade to v1.1.1, preserve the partition cursor, requeue the affected partition after stopping the old worker, and resume.
