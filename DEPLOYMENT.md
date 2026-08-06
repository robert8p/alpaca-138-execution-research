# Deployment — v1.1.3 psycopg wildcard hotfix

1. Suspend `alpaca-138-research-worker` in Render.
2. Replace the GitHub repository contents with v1.1.3, preserving the hidden `.git` folder.
3. Commit and push: `Fix Massive stage SQL wildcard v1.1.3`.
4. Deploy `alpaca-138-research-web` first.
5. Confirm `/health` reports version `1.1.3`, database `ok`, and the same protocol hash as before. There is no new migration.
6. Resume `alpaca-138-research-worker` and deploy the latest commit.
7. Watch for `massive_reference` partitions named `symbol-batch-00000`, `symbol-batch-00001`, and so on.

Do not cancel the research run and do not run manual SQL. Existing completed partitions and the current 2024 Q1 run are preserved.
