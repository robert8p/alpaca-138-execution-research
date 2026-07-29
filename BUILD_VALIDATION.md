# Build validation

## Offline validation completed

- Python source compilation: passed.
- 47 deterministic tests: passed.
- Jinja template parsing: passed.
- Render Blueprint structure: passed.
- Protocol hash stability and confirmation lock: passed.
- DST conversion and early-close handling: passed.
- Trade-condition filtering: passed.
- Round-lot quote-size conversion: passed.
- Entry-window liquidity waiting: passed.
- Stop election outside fresh NBBO rejection: passed.
- Realistic gap-through-stop execution: passed.
- Delayed executable forward-return diagnostics: passed.
- MAE/MFE termination at actual exit: passed.
- Net-profit concentration calculation: passed.
- Effective-dated SEC, FINRA TAF and CAT LLC schedules: passed.
- Stale-partition recovery and manual exhausted-attempt reset: passed.
- Smoke-probe labelling/idempotency: passed.
- Shared raw SIP cache across sensitivity cohorts: passed.

## Credential-dependent checks not executed

The build environment has no access to the user's Alpaca, Massive, Supabase or Render credentials. Therefore these must be proved by the supplied smoke run after deployment:

- live historical SIP entitlement;
- live Massive all-history split entitlement;
- Supabase migration and private bucket creation;
- raw-page upload/download;
- end-to-end report generation;
- measured provider throughput and final storage use.

No synthetic result is presented as evidence for or against the 13.776879% hypothesis.
