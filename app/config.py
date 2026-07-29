from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: SecretStr = Field(alias="DATABASE_URL")
    supabase_url: str = Field(alias="SUPABASE_URL")
    supabase_service_role_key: SecretStr = Field(alias="SUPABASE_SERVICE_ROLE_KEY")
    storage_bucket: str = Field(default="alpaca-138-research", alias="STORAGE_BUCKET")

    alpaca_api_key: SecretStr = Field(default="", alias="ALPACA_API_KEY")
    alpaca_api_secret: SecretStr = Field(default="", alias="ALPACA_API_SECRET")
    alpaca_feed: str = Field(default="sip", alias="ALPACA_FEED")
    alpaca_sip_confirmed: bool = Field(default=False, alias="ALPACA_SIP_CONFIRMED")
    alpaca_requests_per_minute: int = Field(default=8000, ge=1, le=10000, alias="ALPACA_REQUESTS_PER_MINUTE")
    include_otc: bool = Field(default=False, alias="INCLUDE_OTC")

    massive_api_key: SecretStr = Field(default="", alias="MASSIVE_API_KEY")
    massive_base_url: str = Field(default="https://api.massive.com", alias="MASSIVE_BASE_URL")
    massive_all_history_confirmed: bool = Field(default=False, alias="MASSIVE_ALL_HISTORY_CONFIRMED")
    massive_requests_per_minute: int = Field(default=600, ge=1, le=6000, alias="MASSIVE_REQUESTS_PER_MINUTE")

    app_username: str = Field(default="rob", alias="APP_USERNAME")
    app_password: SecretStr = Field(default="", alias="APP_PASSWORD")
    session_secret: SecretStr = Field(default="", alias="SESSION_SECRET")

    db_pool_size: int = Field(default=4, ge=1, le=20, alias="DB_POOL_SIZE")
    worker_poll_seconds: float = Field(default=2.0, ge=0.5, le=60, alias="WORKER_POLL_SECONDS")
    stale_partition_minutes: int = Field(default=20, ge=5, le=240, alias="STALE_PARTITION_MINUTES")
    max_partition_attempts: int = Field(default=8, ge=1, le=25, alias="MAX_PARTITION_ATTEMPTS")
    symbol_batch_size_daily: int = Field(default=100, ge=10, le=500, alias="SYMBOL_BATCH_SIZE_DAILY")
    symbol_batch_size_decision: int = Field(default=150, ge=10, le=300, alias="SYMBOL_BATCH_SIZE_DECISION")
    decision_lookback_minutes: int = Field(default=60, ge=5, le=180, alias="DECISION_LOOKBACK_MINUTES")
    temp_data_dir: str = Field(default="/var/data", alias="TEMP_DATA_DIR")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    http_timeout_seconds: float = Field(default=60.0, ge=10, le=300, alias="HTTP_TIMEOUT_SECONDS")
    signed_url_seconds: int = Field(default=3600, ge=60, le=86400, alias="SIGNED_URL_SECONDS")

    smoke_symbols: str = Field(default="AAPL,MSFT,TSLA,NVDA,AMD,SPY,QQQ,IWM", alias="SMOKE_SYMBOLS")

    @property
    def db_dsn(self) -> str:
        return self.database_url.get_secret_value()

    @property
    def service_key(self) -> str:
        return self.supabase_service_role_key.get_secret_value()

    @property
    def alpaca_headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.alpaca_api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": self.alpaca_api_secret.get_secret_value(),
        }

    def validate_web(self) -> None:
        missing: list[str] = []
        password = self.app_password.get_secret_value()
        secret = self.session_secret.get_secret_value()
        if not password or password.lower() in {"password", "change-me", "secret", "replace_me"}:
            missing.append("APP_PASSWORD")
        if len(secret) < 32 or secret.lower().startswith("replace"):
            missing.append("SESSION_SECRET")
        if missing:
            raise RuntimeError(f"Missing or insecure web settings: {', '.join(missing)}")


    def validate_worker(self) -> None:
        missing: list[str] = []
        if not self.alpaca_api_key.get_secret_value():
            missing.append("ALPACA_API_KEY")
        if not self.alpaca_api_secret.get_secret_value():
            missing.append("ALPACA_API_SECRET")
        if not self.massive_api_key.get_secret_value():
            missing.append("MASSIVE_API_KEY")
        if self.alpaca_feed.lower() != "sip" or not self.alpaca_sip_confirmed:
            missing.append("ALPACA_SIP_CONFIRMED=true")
        if not self.massive_all_history_confirmed:
            missing.append("MASSIVE_ALL_HISTORY_CONFIRMED=true")
        if missing:
            raise RuntimeError(f"Missing worker settings: {', '.join(missing)}")

    @property
    def smoke_symbol_list(self) -> list[str]:
        return [item.strip().upper() for item in self.smoke_symbols.split(",") if item.strip()]

    def ensure_temp_dir(self) -> Path:
        path = Path(self.temp_data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
