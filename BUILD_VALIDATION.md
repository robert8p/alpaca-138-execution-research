# Build validation — v1.1.0

## Offline validation completed

- Python source compilation: passed.
- 53 deterministic tests: passed.
- Jinja template parsing: passed.
- Render Blueprint structure: passed.
- Persistent-disk Blueprint conflict removed: passed.
- Protocol hash stability and confirmation lock: passed.
- Eight locked primary tranches: passed.
- Negative-only futility specification: passed.
- Deterministic lower and upper date-block bootstrap bounds: passed.
- Strong-negative futility trigger test: passed.
- No positive early-validation route: passed.
- Standalone and cumulative report architecture: passed.
- Heartbeat and stale-partition UI: passed.
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
- Shared raw SIP cache across sensitivity cohorts: passed.

## Credential-dependent checks not executed

The build environment has no access to Alpaca, Massive, Supabase or Render credentials. The smoke run must prove:

- live historical SIP entitlement;
- live Massive all-history entitlement;
- migrations 001 and 002;
- private Storage creation and uploads;
- tranche report generation;
- measured provider throughput and storage use.

No synthetic result is presented as evidence for or against the strategy.
