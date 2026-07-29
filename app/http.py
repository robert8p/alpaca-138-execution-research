from __future__ import annotations

import random
import time
from typing import Any

import httpx


class ApiError(RuntimeError):
    pass


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, Any] | None = None,
    timeout: float = 60.0,
    attempts: int = 6,
) -> Any:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(method, url, headers=headers, params=params)
            if response.status_code == 429 or response.status_code >= 500:
                retry_after = float(response.headers.get("retry-after", "0") or 0)
                delay = max(retry_after, min(30.0, 0.75 * (2**attempt))) + random.random() * 0.25
                time.sleep(delay)
                continue
            if response.status_code >= 400:
                raise ApiError(f"HTTP {response.status_code} for {url}: {response.text[:1000]}")
            return response.json()
        except (httpx.TimeoutException, httpx.NetworkError, ApiError) as exc:
            last = exc
            if isinstance(exc, ApiError) and "HTTP 4" in str(exc) and "429" not in str(exc):
                raise
            time.sleep(min(30.0, 0.75 * (2**attempt)) + random.random() * 0.25)
    raise ApiError(f"Request failed after {attempts} attempts: {url}: {last}")
