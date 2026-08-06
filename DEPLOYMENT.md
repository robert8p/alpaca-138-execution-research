# Deployment — v1.1.4 Massive invalid-symbol hotfix

1. Suspend `alpaca-138-research-worker`.
2. Replace the GitHub repository contents with v1.1.4, preserving `.git`.
3. Commit and push: `Skip unsupported Massive ticker formats v1.1.4`.
4. Deploy `alpaca-138-research-web` and confirm `/health` reports `1.1.4`.
5. Resume and deploy `alpaca-138-research-worker`.
6. In the UI, select **Retry and resume** once to reset the exhausted `symbol-batch-00100` partition.

No new run, migration or manual SQL is required. The cursor remains at index 50; the fixed worker records `OPP-C` as `invalid_ticker_parameter`, advances to index 51 and completes the rest of the batch.
