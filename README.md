# Alpaca 13.8% Execution Research Lab v1.1.4

## v1.1.4 invalid ticker repair

Massive may reject certain Alpaca preferred-share, right or unit symbols with HTTP 400 `Invalid ticker parameter`. These symbols are now audited as provider-format coverage exclusions and skipped without failing their entire 100-symbol partition. The frozen protocol and existing run remain unchanged.

Operational hotfix for the frozen v1.1.0 quarterly research protocol.

## v1.1.4 SQL wildcard repair

v1.1.2 correctly replaced the global Massive catalogue crawl with exact-symbol batches, but the stage-count query embedded a literal `%` wildcard inside a parameterised psycopg query. Psycopg interpreted it as invalid placeholder syntax and the worker loop failed before it could enqueue or process the new batches.

v1.1.4 binds `symbol-batch-%` as a normal SQL parameter. The research protocol, threshold, execution assumptions, tranche sequence and protocol hash are unchanged. Existing runs resume in place.

## Recovery

Suspend the worker, deploy v1.1.4 to the web service, confirm `/health` reports `1.1.4`, then resume and deploy the worker. No migration, manual SQL, new run or cancellation is required.

See `DEPLOYMENT.md` for the short procedure.
