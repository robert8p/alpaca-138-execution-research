# Alpaca 13.8% Execution Research Lab v1.1.5

## v1.1.5 Alpaca invalid-symbol repair

Alpaca's multi-symbol bars endpoint rejects the synthetic/internal asset symbol `E018385`. In prior releases, that permanent HTTP 400 caused the complete 100-symbol Daily Bars partition to retry eight times and fail.

v1.1.5 converts only Alpaca HTTP 400 responses containing `invalid symbol: <ticker>` into an audited per-symbol coverage exclusion. It then:

- marks the affected instrument in metadata;
- removes it from all later market-data cohorts;
- restarts the reduced multi-symbol request safely;
- idempotently upserts any already-downloaded bars;
- recomputes the partition's unique row count;
- applies the same protection to Decision Snapshot requests.

Other HTTP 400 responses still fail normally. Existing runs, quarterly checkpoints and completed partitions remain intact.

## Research integrity

The frozen threshold, execution assumptions, quarterly sequence, futility rule and protocol hash are unchanged. This is an operational data-quality repair, not a strategy change.

## Upgrade

Suspend the worker, deploy v1.1.5 to the web service, confirm `/health` reports `1.1.5`, then resume and deploy the worker. Select **Retry and resume** once. No migration or new run is required.
