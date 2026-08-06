# Build validation — v1.1.4

- Operational change: treat Massive HTTP 400 `Invalid ticker parameter` as an audited per-symbol coverage exclusion rather than a retryable partition failure.
- Verified failing production case: Alpaca symbol `OPP-C` at saved cursor index 50.
- Research protocol version: 1.1.0, unchanged.
- Protocol hash: `ddce449bdd0c6dc6f720e67ff6964bb1dbbe37d6b7429c5455eded1afd630ca2`, unchanged.
- Existing research runs and completed partitions resume in place.
- No database migration required.
