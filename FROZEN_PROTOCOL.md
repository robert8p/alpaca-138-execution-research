# Frozen execution protocol

The application tests one previously discovered signal and does not perform further strategy discovery.

## Signal

At exactly **17:00 Europe/London**, identify every primary-universe US equity whose last SIP trade available at or before that decision time is strictly greater than **13.776879223878035%** above its previous regular-session close.

- The previous close and decision-time price are raw prices.
- A split effective on the tested date excludes that symbol-day.
- The exact signal trade must be no more than 300 seconds old.
- The daily ranking is descending by exact return; at most five signal trades are selected.
- Every qualifier is retained, including unselected qualifiers.

## Historical isolation

- Primary replication: 1 January 2024–31 December 2025.
- Locked confirmation: 1 January 2026–19 April 2026.
- The April–July 2026 discovery/validation/sealed-test period is excluded.
- The confirmation phase can be opened only if the primary phase passes every frozen gate and the protocol hash is unchanged.

## Universe

The primary result reproduces the earlier methodology: the complete set of current Alpaca US-equity assets that are active and tradable when the run catalogue is captured, excluding OTC unless separately entitled.

The report also includes:

- a Massive-classified common-stock sensitivity;
- an expanded active/inactive Alpaca market-data sensitivity.

These are sensitivities, not replacements for the primary population.

## Execution

All scenarios request US$500, use whole shares, and require the requested order to be small relative to the preceding minute's dollar volume. Fractional fills are not modelled because point-in-time fractional eligibility cannot be reconstructed reliably.

| Scenario | Reaction | Additional adverse slippage | Displayed-size requirement |
|---|---:|---:|---:|
| Optimistic | 5 seconds | Greater of 5 bps or 10% of spread | 1× shares |
| Base | 30 seconds | Greater of 10 bps or 25% of spread | 1× shares |
| Conservative | 60 seconds | Greater of 25 bps or 50% of spread | 2× shares |

Entry uses the first valid SIP NBBO ask during the five-second entry window. Quotes must be no more than one second old. Missing, locked/crossed or insufficiently sized quotes do not fill.

## Exits

- Stop trigger: 5% below actual entry fill.
- Profit target: 150% of previous regular-session close.
- Time exit: 15:55 America/New_York.
- Triggered exits use the first fresh, sufficiently sized executable bid with scenario slippage.
- A halt or missing executable bid through the close is forced overnight exposure and remains unresolved for the intraday profitability gate.
- A secondary next-session quote is recorded diagnostically but does not repair the intraday result.

## Costs

The simulation applies effective-dated SEC Section 31 fees, FINRA TAF rates/caps and the official CAT LLC per-share schedule on both entry and exit. SEC and TAF are rounded up to the cent. Additional broker-specific fees are disclosed as unmodelled rather than altered through environment variables.

## Controls

Each selected signal receives one same-date liquidity-matched control and one deterministic random control. Controls are executed under the same assumptions, but are not included in portfolio P&L.

## Acceptance gate

The frozen gate includes minimum sample breadth, positive base-case P&L and mean/median returns, profit factor of at least 1.25, nonnegative conservative P&L, positive P&L after removing the three largest winners, a positive date-block bootstrap lower bound, maximum drawdown of US$5,000, concentration limits, no more than ten consecutive losses and no more than 1% unresolved exits.

Passing both phases means **validated for paper testing**, not live trading.

The machine-readable source of truth is `app/protocol.py`; every run stores its SHA-256 protocol hash.
