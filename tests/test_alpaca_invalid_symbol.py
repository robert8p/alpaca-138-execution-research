from __future__ import annotations

from datetime import datetime, timezone

from app import processors
from app.http import ApiError
from app.providers import AlpacaClient, InvalidAlpacaSymbol


def test_alpaca_bars_converts_only_invalid_symbol_400(monkeypatch):
    client = AlpacaClient()
    monkeypatch.setattr(
        client,
        "_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ApiError('HTTP 400 for https://data.alpaca.markets/v2/stocks/bars: {"message":"invalid symbol: E018385"}')
        ),
    )

    try:
        list(
            client.bars_pages(
                ["DVN", "E018385"],
                "1Day",
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 4, 1, tzinfo=timezone.utc),
            )
        )
    except InvalidAlpacaSymbol as exc:
        assert exc.symbol == "E018385"
    else:
        raise AssertionError("Expected InvalidAlpacaSymbol")


def test_alpaca_bars_does_not_hide_other_400_errors(monkeypatch):
    client = AlpacaClient()
    monkeypatch.setattr(
        client,
        "_get",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ApiError("HTTP 400: malformed timeframe")),
    )

    try:
        list(
            client.bars_pages(
                ["DVN"],
                "1Day",
                datetime(2024, 1, 1, tzinfo=timezone.utc),
                datetime(2024, 4, 1, tzinfo=timezone.utc),
            )
        )
    except ApiError as exc:
        assert "malformed timeframe" in str(exc)
    else:
        raise AssertionError("Expected original ApiError")


def test_daily_bars_excludes_invalid_symbol_and_continues(monkeypatch):
    calls: list[list[str]] = []
    exclusions: list[tuple[str, str, str]] = []
    heartbeats: list[dict] = []
    completed: list[dict] = []

    class _Alpaca:
        def bars_pages(self, symbols, *_args, **_kwargs):
            calls.append(list(symbols))
            if "E018385" in symbols:
                raise InvalidAlpacaSymbol("E018385")
            yield {"bars": {}, "next_page_token": None}

    monkeypatch.setattr(processors, "AlpacaClient", _Alpaca)
    monkeypatch.setattr(
        processors,
        "_exclude_invalid_alpaca_market_data_symbol",
        lambda run_id, symbol, endpoint: exclusions.append((run_id, symbol, endpoint)),
    )
    monkeypatch.setattr(processors, "_daily_bar_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(processors, "heartbeat", lambda _id, **kwargs: heartbeats.append(kwargs))
    monkeypatch.setattr(processors, "complete", lambda _id, **kwargs: completed.append(kwargs))
    monkeypatch.setattr(processors, "is_cancelled", lambda _run_id: False)

    processors.process_daily_bars(
        {
            "id": "partition",
            "run_id": "run",
            "phase": "primary",
            "row_count": 0,
            "cursor": {},
            "params": {
                "symbols": ["DVN", "E018385", "EA"],
                "start": "2024-01-01",
                "end": "2024-03-31",
            },
        }
    )

    assert calls == [["DVN", "E018385", "EA"], ["DVN", "EA"]]
    assert exclusions == [("run", "E018385", "v2/stocks/bars")]
    assert heartbeats[0]["cursor"]["last_invalid_symbol"] == "E018385"
    assert completed[0]["cursor"] == {"finished": True, "invalid_symbols": ["E018385"]}


def test_daily_bars_resumes_with_saved_invalid_symbols(monkeypatch):
    calls: list[list[str]] = []
    completed: list[dict] = []

    class _Alpaca:
        def bars_pages(self, symbols, *_args, **_kwargs):
            calls.append(list(symbols))
            yield {"bars": {}, "next_page_token": None}

    monkeypatch.setattr(processors, "AlpacaClient", _Alpaca)
    monkeypatch.setattr(processors, "_daily_bar_count", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(processors, "heartbeat", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(processors, "complete", lambda _id, **kwargs: completed.append(kwargs))
    monkeypatch.setattr(processors, "is_cancelled", lambda _run_id: False)

    processors.process_daily_bars(
        {
            "id": "partition",
            "run_id": "run",
            "phase": "primary",
            "row_count": 0,
            "cursor": {"invalid_symbols": ["E018385"]},
            "params": {
                "symbols": ["DVN", "E018385", "EA"],
                "start": "2024-01-01",
                "end": "2024-03-31",
            },
        }
    )

    assert calls == [["DVN", "EA"]]
    assert completed[0]["cursor"]["invalid_symbols"] == ["E018385"]
