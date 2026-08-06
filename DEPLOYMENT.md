# Deployment — v1.1.5 Alpaca invalid-symbol hotfix

1. Suspend `alpaca-138-research-worker`; do not cancel the run.
2. Replace the GitHub repository contents with v1.1.5, preserving `.git`.
3. Commit and push: `Skip invalid Alpaca market-data symbols v1.1.5`.
4. Deploy `alpaca-138-research-web` and confirm `/health` reports `1.1.5`.
5. Resume and deploy `alpaca-138-research-worker`.
6. In the UI, select **Retry and resume** once.

No migration, manual SQL, new run or protocol change is required. The failed partition resumes in place. `E018385` is audited as an Alpaca market-data format exclusion and the remaining symbols in batch 00039 continue.
