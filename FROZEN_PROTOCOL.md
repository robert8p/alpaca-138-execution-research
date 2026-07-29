# Frozen research protocol — v1.1.0

## Research question

At 17:00 Europe/London, does buying up to five US equities whose last eligible SIP trade is strictly more than 13.776879223878035% above the previous regular-session close produce positive, robust, executable intraday returns?

## Locked signal

- Long only.
- Decision timestamp: exactly 17:00 Europe/London, converted by date to New York time.
- Comparison: strictly greater than 13.776879223878035%.
- Denominator: previous regular-session close.
- Numerator: last qualifying SIP trade at or before the decision timestamp.
- Maximum signal-trade age: 300 seconds.
- Maximum five selections per date, ranked by exact return descending.
- No future-high, future-volume or future-liquidity prefilter.

## Primary sequence

The primary period remains 1 January 2024 through 31 December 2025, but is processed sequentially as eight locked tranches:

| Sequence | Tranche | Start | End |
|---:|---|---|---|
| 1 | 2024 Q1 | 2024-01-01 | 2024-03-31 |
| 2 | 2024 Q2 | 2024-04-01 | 2024-06-30 |
| 3 | 2024 Q3 | 2024-07-01 | 2024-09-30 |
| 4 | 2024 Q4 | 2024-10-01 | 2024-12-31 |
| 5 | 2025 Q1 | 2025-01-01 | 2025-03-31 |
| 6 | 2025 Q2 | 2025-04-01 | 2025-06-30 |
| 7 | 2025 Q3 | 2025-07-01 | 2025-09-30 |
| 8 | 2025 Q4 | 2025-10-01 | 2025-12-31 |

Each completed tranche produces both standalone and cumulative reports.

## Interim interpretation

- A positive quarter is descriptive and may only support continuing.
- A positive cumulative interim report cannot pass the primary gate.
- Confirmation cannot be opened before all eight quarters complete.
- No threshold, stop, target, ranking, universe, reaction time, cost or gate may be altered between tranches.

## Early-futility rule

The app automatically stops the primary study only when cumulative evidence meets all of these locked conditions:

1. At least 30 completed base-case trades.
2. At least 15 independent dates.
3. At least 10 symbols.
4. Base-case net P&L is negative.
5. Base-case mean net return is negative.
6. Conservative-case net P&L is negative.
7. The upper bound of the date-block bootstrap 95% confidence interval for mean base-case return is no greater than zero.

The resulting classification is `rejected_early_for_futility`. Confirmation remains sealed.

## Full primary gate

If futility is not triggered, all eight quarters must complete. The original primary gate remains unchanged, including minimum sample size, positive net P&L, profit factor, mean and median return, conservative survival, top-winner exclusion, positive lower bootstrap bound, drawdown, loss streak, unresolved exits and concentration limits.

## Locked confirmation

- Period: 1 January 2026 through 19 April 2026.
- It can be opened only after the complete primary gate passes.
- The app rechecks the protocol hash at unlock and throughout confirmation.
- The excluded discovery period starts 20 April 2026.

## Execution

The optimistic, base and conservative cases remain exactly those encoded in `app/protocol.py`, including reaction delays, SIP quote freshness, displayed capacity, volume participation, slippage, 5% stop, 150%-of-previous-close target, 15:55 ET exit and effective-dated fees.

## Protocol hash

The canonical JSON in `app/protocol.py` is SHA-256 hashed. Quarterly boundaries and the futility rule are part of that hash. A code or protocol change after confirmation unlock produces `invalid_process`.
