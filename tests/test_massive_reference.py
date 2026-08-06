from __future__ import annotations

from contextlib import contextmanager

from app import processors


class _Cursor:
    rowcount = 1
    batches: list[list[tuple]] = []

    def execute(self, *_args, **_kwargs):
        return None

    def executemany(self, _sql, values):
        self.batches.append(list(values))
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _Connection:
    def cursor(self):
        return _Cursor()

    def commit(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


@contextmanager
def _connection():
    yield _Connection()


class _Massive:
    calls: list[tuple[str, bool]] = []

    def ticker_reference(self, symbol: str, *, active: bool):
        self.calls.append((symbol, active))
        if symbol == "AAA" and active:
            return {
                "ticker": "AAA",
                "type": "CS",
                "active": True,
                "primary_exchange": "XNAS",
                "cik": "1",
                "composite_figi": "FIGI1",
            }
        if symbol == "OLD" and not active:
            return {
                "ticker": "OLD",
                "type": "CS",
                "active": False,
                "primary_exchange": "XNYS",
                "cik": "2",
                "composite_figi": "FIGI2",
            }
        return None


def test_massive_reference_looks_up_only_run_symbols_with_inactive_fallback(monkeypatch):
    _Massive.calls = []
    _Cursor.batches = []
    completed = []
    monkeypatch.setattr(processors, "MassiveClient", _Massive)
    monkeypatch.setattr(processors, "connection", _connection)
    monkeypatch.setattr(processors, "is_cancelled", lambda _run_id: False)
    monkeypatch.setattr(processors, "complete", lambda *args, **kwargs: completed.append((args, kwargs)))

    processors.process_massive_reference(
        {
            "id": "partition",
            "run_id": "run",
            "params": {"symbols": ["AAA", "OLD", "MISS"]},
            "cursor": {},
        }
    )

    assert _Massive.calls == [
        ("AAA", True),
        ("OLD", True),
        ("OLD", False),
        ("MISS", True),
        ("MISS", False),
    ]
    assert completed[0][1]["row_count"] == 2
    assert completed[0][1]["cursor"] == {
        "next_index": 3,
        "examined": 3,
        "matched": 2,
        "not_found": 1,
        "finished": True,
    }
    assert sum(len(batch) for batch in _Cursor.batches) == 3


def test_massive_reference_resumes_from_saved_symbol_index(monkeypatch):
    _Massive.calls = []
    _Cursor.batches = []
    completed = []
    monkeypatch.setattr(processors, "MassiveClient", _Massive)
    monkeypatch.setattr(processors, "connection", _connection)
    monkeypatch.setattr(processors, "is_cancelled", lambda _run_id: False)
    monkeypatch.setattr(processors, "heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(processors, "complete", lambda *args, **kwargs: completed.append((args, kwargs)))

    processors.process_massive_reference(
        {
            "id": "partition",
            "run_id": "run",
            "params": {"symbols": ["AAA", "OLD"]},
            "cursor": {"next_index": 1, "examined": 1, "matched": 1, "not_found": 0},
        }
    )

    assert _Massive.calls == [("OLD", True), ("OLD", False)]
    assert completed[0][1]["row_count"] == 2
    assert completed[0][1]["cursor"]["next_index"] == 2


def test_legacy_all_tickers_partition_is_retired_without_api_calls(monkeypatch):
    completed = []

    class _MustNotConstruct:
        def __init__(self):
            raise AssertionError("Legacy partition must not call Massive")

    monkeypatch.setattr(processors, "MassiveClient", _MustNotConstruct)
    monkeypatch.setattr(processors, "complete", lambda *args, **kwargs: completed.append((args, kwargs)))

    processors.process_massive_reference(
        {"id": "legacy", "run_id": "run", "params": {}, "cursor": {"processed": 772600}}
    )

    assert completed[0][1]["row_count"] == 0
    assert completed[0][1]["cursor"]["retired_legacy_all_tickers"] is True


def test_massive_client_exact_lookup_sets_symbol_and_active_filters(monkeypatch):
    from app.providers import MassiveClient

    client = MassiveClient()
    calls = []

    def fake_get(url, params=None):
        calls.append((url, params))
        return {"results": [{"ticker": "AAA", "active": params["active"] == "true"}]}

    monkeypatch.setattr(client, "_get", fake_get)
    row = client.ticker_reference("AAA", active=False)

    assert row["ticker"] == "AAA"
    assert calls[0][0].endswith("/v3/reference/tickers")
    assert calls[0][1]["ticker"] == "AAA"
    assert calls[0][1]["active"] == "false"
    assert calls[0][1]["market"] == "stocks"
