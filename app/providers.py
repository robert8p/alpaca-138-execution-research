from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterator

from app.config import get_settings
from app.http import request_json
from app.rate_limit import RateLimiter


class AlpacaClient:
    trading_base = "https://paper-api.alpaca.markets"
    data_base = "https://data.alpaca.markets"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.limiter = RateLimiter(self.settings.alpaca_requests_per_minute)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        self.limiter.wait()
        return request_json(
            "GET",
            url,
            headers=self.settings.alpaca_headers,
            params=params,
            timeout=self.settings.http_timeout_seconds,
        )

    def assets(self) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.trading_base}/v2/assets",
            {"status": "all", "asset_class": "us_equity"},
        )
        return list(data or [])

    def calendar(self, start: date, end: date) -> list[dict[str, Any]]:
        data = self._get(
            f"{self.trading_base}/v2/calendar",
            {"start": start.isoformat(), "end": end.isoformat()},
        )
        return list(data or [])

    def bars_pages(
        self,
        symbols: list[str],
        timeframe: str,
        start: datetime,
        end: datetime,
        *,
        adjustment: str = "raw",
        limit: int = 10000,
        page_token: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        token = page_token
        while True:
            params: dict[str, Any] = {
                "symbols": ",".join(symbols),
                "timeframe": timeframe,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "adjustment": adjustment,
                "feed": self.settings.alpaca_feed,
                "sort": "asc",
                "limit": limit,
            }
            if token:
                params["page_token"] = token
            payload = self._get(f"{self.data_base}/v2/stocks/bars", params)
            yield payload
            token = payload.get("next_page_token")
            if not token:
                break

    def trades_pages(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        page_token: str | None = None,
        limit: int = 10000,
    ) -> Iterator[dict[str, Any]]:
        token = page_token
        while True:
            params: dict[str, Any] = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "feed": self.settings.alpaca_feed,
                "sort": "asc",
                "limit": limit,
            }
            if token:
                params["page_token"] = token
            payload = self._get(f"{self.data_base}/v2/stocks/{symbol}/trades", params)
            yield payload
            token = payload.get("next_page_token")
            if not token:
                break

    def quotes_pages(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        *,
        page_token: str | None = None,
        limit: int = 10000,
    ) -> Iterator[dict[str, Any]]:
        token = page_token
        while True:
            params: dict[str, Any] = {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "feed": self.settings.alpaca_feed,
                "sort": "asc",
                "limit": limit,
            }
            if token:
                params["page_token"] = token
            payload = self._get(f"{self.data_base}/v2/stocks/{symbol}/quotes", params)
            yield payload
            token = payload.get("next_page_token")
            if not token:
                break


class MassiveClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.limiter = RateLimiter(self.settings.massive_requests_per_minute)

    def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        self.limiter.wait()
        merged = dict(params or {})
        merged.setdefault("apiKey", self.settings.massive_api_key.get_secret_value())
        return request_json("GET", url, params=merged, timeout=self.settings.http_timeout_seconds)

    def ticker_reference(self, symbol: str, *, active: bool) -> dict[str, Any] | None:
        """Return an exact active/inactive ticker match without scanning the catalogue."""
        payload = self._get(
            f"{self.settings.massive_base_url.rstrip('/')}/v3/reference/tickers",
            {
                "ticker": symbol,
                "market": "stocks",
                "active": str(active).lower(),
                "limit": 10,
                "sort": "ticker",
                "order": "asc",
            },
        )
        for row in payload.get("results") or []:
            if str(row.get("ticker") or "").upper() == symbol.upper():
                return row
        return None

    def ticker_page(self, active: bool, next_url: str | None = None) -> dict[str, Any]:
        url = next_url or f"{self.settings.massive_base_url.rstrip('/')}/v3/reference/tickers"
        params = None if next_url else {
            "market": "stocks",
            "active": str(active).lower(),
            "limit": 1000,
            "sort": "ticker",
            "order": "asc",
        }
        return self._get(url, params)

    def all_tickers(self, active: bool) -> Iterator[dict[str, Any]]:
        next_url: str | None = None
        while True:
            payload = self.ticker_page(active, next_url)
            yield from payload.get("results") or []
            next_url = payload.get("next_url")
            if not next_url:
                break

    def splits_page(self, start: date, end: date, next_url: str | None = None) -> dict[str, Any]:
        url = next_url or f"{self.settings.massive_base_url.rstrip('/')}/stocks/v1/splits"
        params = None if next_url else {
            "execution_date.gte": start.isoformat(),
            "execution_date.lte": end.isoformat(),
            "limit": 1000,
            "sort": "execution_date",
            "order": "asc",
        }
        return self._get(url, params)

    def splits(self, start: date, end: date) -> Iterator[dict[str, Any]]:
        next_url: str | None = None
        while True:
            payload = self.splits_page(start, end, next_url)
            yield from payload.get("results") or []
            next_url = payload.get("next_url")
            if not next_url:
                break
