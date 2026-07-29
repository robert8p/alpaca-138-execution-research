import pytest

from app.config import Settings


def test_web_validation_rejects_placeholders(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "change-me")
    monkeypatch.setenv("SESSION_SECRET", "short")
    settings = Settings()
    with pytest.raises(RuntimeError):
        settings.validate_web()


def test_worker_validation_requires_provider_keys(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "")
    monkeypatch.setenv("ALPACA_API_SECRET", "")
    monkeypatch.setenv("MASSIVE_API_KEY", "")
    settings = Settings()
    with pytest.raises(RuntimeError):
        settings.validate_worker()


def test_worker_validation_accepts_explicit_entitlements(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "test-massive")
    monkeypatch.setenv("ALPACA_FEED", "sip")
    monkeypatch.setenv("ALPACA_SIP_CONFIRMED", "true")
    monkeypatch.setenv("MASSIVE_ALL_HISTORY_CONFIRMED", "true")
    settings = Settings()
    settings.validate_worker()


def test_worker_validation_rejects_unconfirmed_entitlements(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_API_SECRET", "test-secret")
    monkeypatch.setenv("MASSIVE_API_KEY", "test-massive")
    monkeypatch.setenv("ALPACA_FEED", "sip")
    monkeypatch.setenv("ALPACA_SIP_CONFIRMED", "false")
    monkeypatch.setenv("MASSIVE_ALL_HISTORY_CONFIRMED", "false")
    settings = Settings()
    with pytest.raises(RuntimeError, match="ALPACA_SIP_CONFIRMED"):
        settings.validate_worker()
