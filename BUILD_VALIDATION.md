# Build validation — v1.1.3

- Operational change: bind the Massive `LIKE` wildcard through psycopg parameters.
- Research protocol version: 1.1.0, unchanged.
- Protocol hash: `ddce449bdd0c6dc6f720e67ff6964bb1dbbe37d6b7429c5455eded1afd630ca2`, unchanged.
- Regression coverage includes the exact `_stage_counts(..., massive_reference)` query and parameter tuple.
- Offline tests: 61 passed.
- No database migration required.
- Existing research runs resume in place.
