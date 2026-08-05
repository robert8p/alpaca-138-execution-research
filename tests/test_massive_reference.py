from __future__ import annotations

from contextlib import contextmanager

from app import processors


class _Cursor:
    rowcount = 1

    def execute(self, *_args, **_kwargs):
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
    calls: list[tuple[bool, str | None]] = []

    def ticker_page(self, active: bool, next_url: str | None = None):
        self.calls.append((active, next_url))
        if active and next_url is None:
            return {"results": [{"ticker": "AAA", "type": "CS", "active": True}], "next_url": "active-2"}
        if active and next_url == "active-2":
            return {"results": [{"ticker": "AAB", "type": "CS", "active": True}], "next_url": None}
        if not active and next_url is None:
            return {"results": [{"ticker": "OLD", "type": "CS", "active": False}], "next_url": "inactive-2"}
        if not active and next_url == "inactive-2":
            return {"results": [{"ticker": "OLDER", "type": "CS", "active": False}], "next_url": None}
        raise AssertionError((active, next_url))


def test_massive_reference_follows_each_groups_next_url(monkeypatch):
    _Massive.calls = []
    heartbeats = []
    completed = []
    monkeypatch.setattr(processors, "MassiveClient", _Massive)
    monkeypatch.setattr(processors, "connection", _connection)
    monkeypatch.setattr(processors, "is_cancelled", lambda _run_id: False)
    monkeypatch.setattr(processors, "heartbeat", lambda *args, **kwargs: heartbeats.append((args, kwargs)))
    monkeypatch.setattr(processors, "complete", lambda *args, **kwargs: completed.append((args, kwargs)))

    processors.process_massive_reference(
        {"id": "partition", "run_id": "run", "cursor": {}, "row_count": 16_337_603}
    )

    assert _Massive.calls == [
        (True, None),
        (True, "active-2"),
        (False, None),
        (False, "inactive-2"),
    ]
    assert completed[0][1]["row_count"] == 4
    assert completed[0][1]["cursor"]["finished"] is True
    assert heartbeats[-1][1]["cursor"]["active_index"] == 2


def test_massive_reference_resumes_inactive_cursor_without_restarting_first_page(monkeypatch):
    _Massive.calls = []
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
            "cursor": {"active_index": 1, "next_url": "inactive-2"},
            "row_count": 16_337_603,
        }
    )

    assert _Massive.calls == [(False, "inactive-2")]
    assert completed[0][1]["row_count"] == 1
