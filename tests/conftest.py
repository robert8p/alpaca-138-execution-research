from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# The offline packaging image omits the PostgreSQL wheel. Production installs the
# pinned dependency from requirements.txt; unit tests that do not touch a database
# use a minimal import stub.
try:
    import psycopg  # noqa: F401
except ModuleNotFoundError:
    import types
    psycopg = types.ModuleType("psycopg")
    psycopg.Connection = object
    rows = types.ModuleType("psycopg.rows")
    rows.dict_row = object()
    json_mod = types.ModuleType("psycopg.types.json")
    class Jsonb:
        def __init__(self, value): self.value = value
    json_mod.Jsonb = Jsonb
    types_mod = types.ModuleType("psycopg.types")
    types_mod.json = json_mod
    pool_mod = types.ModuleType("psycopg_pool")
    class ConnectionPool:
        def __init__(self, *args, **kwargs): self.closed = True
        def open(self, *args, **kwargs): self.closed = False
        def close(self): self.closed = True
        def connection(self): raise RuntimeError("offline test database stub")
    pool_mod.ConnectionPool = ConnectionPool
    sys.modules.update({
        "psycopg": psycopg, "psycopg.rows": rows, "psycopg.types": types_mod,
        "psycopg.types.json": json_mod, "psycopg_pool": pool_mod,
    })

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/test")
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
os.environ.setdefault("APP_PASSWORD", "strong-test-password")
os.environ.setdefault("SESSION_SECRET", "0123456789abcdef0123456789abcdef")
os.environ.setdefault("ALPACA_API_KEY", "test-alpaca-key")
os.environ.setdefault("ALPACA_API_SECRET", "test-alpaca-secret")
os.environ.setdefault("MASSIVE_API_KEY", "test-massive-key")
os.environ.setdefault("TEMP_DATA_DIR", "/tmp/alpaca-138-tests")
