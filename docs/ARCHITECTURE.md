# Architecture — v1.1.1

## Isolation

The application uses its own GitHub repository, Supabase project and Render web/worker services. It has no runtime dependency on the Market Data Miner.

## Control plane

The web service:

- applies migrations;
- authenticates the dashboard;
- creates smoke and full runs;
- exposes progress, heartbeat and tranche state;
- signs private Storage report downloads;
- controls cancel, resume and confirmation unlock.

## Worker

One resumable worker performs:

1. shared Alpaca catalogue;
2. shared Massive reference reconstruction;
3. tranche calendar and splits;
4. tranche daily bars;
5. decision-time cross-sections;
6. exact SIP signal verification;
7. daily signal/control selection;
8. raw SIP trades and quotes;
9. execution simulations;
10. overnight diagnostics;
11. standalone and cumulative tranche reports;
12. final phase report after all required tranches.

## Quarterly state machine

```text
2024 Q1 → interim reports → futility check
    ↓ continue only
2024 Q2 → interim reports → futility check
    ↓
...
    ↓
2025 Q4 → final primary report → frozen gate
    ↓ only if PASS
2026 locked confirmation → final confirmation report
```

`research_tranches` stores each locked period, status, report paths, metrics and futility assessment. Work partition keys are prefixed by tranche, preventing collisions and making each quarter independently resumable.

## Early stopping

Only the cumulative base and conservative signal cohorts feed the futility rule. Controls and standalone-quarter results cannot stop or validate the study. Early stopping is automatic only when every hard-coded negative condition passes.

## Storage

- PostgreSQL: catalogues, sessions, bars, decision snapshots, triggers, targets, partition checkpoints, trade results, tranche state and report indexes.
- Supabase Storage: compressed raw SIP pages and signed report ZIPs.
- Render disk: temporary resumable processing files under `/var/data`.

## Integrity

The protocol hash includes the hypothesis, universes, execution scenarios, primary and confirmation dates, quarterly boundaries, complete gate and futility rule. Confirmation is invalidated if the hash changes after unlock.
