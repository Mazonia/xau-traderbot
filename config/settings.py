"""
XAUUSD AI Trading Bot - Settings Configuration

Centralized configuration using Pydantic Settings.
Loads from .env file and trading_params.yaml.
"""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


# ── Project Paths ──────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
MODELS_DIR = PROJECT_ROOT / "ai" / "models"

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)

# Common env_file config for all sub-settings
_ENV_FILE = str(CONFIG_DIR / ".env")
_COMMON_CONFIG = {
    "env_file": _ENV_FILE,
    "env_file_encoding": "utf-8",
    "extra": "ignore",
}


def load_trading_params() -> dict:
    """Load trading parameters from YAML config file."""
    params_path = CONFIG_DIR / "trading_params.yaml"
    if params_path.exists():
        with open(params_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


class MT5Settings(BaseSettings):
    """MetaTrader 5 connection settings."""

    login: int = Field(default=0, alias="MT5_LOGIN")
    password: str = Field(default="", alias="MT5_PASSWORD")
    server: str = Field(default="Exness-MT5Real", alias="MT5_SERVER")
    path: str = Field(
        default=r"C:\Program Files\MetaTrader 5\terminal64.exe",
        alias="MT5_PATH",
    )
    timeout: int = 60_000  # Connection timeout in ms

    @field_validator("login", mode="before")
    @classmethod
    def parse_login(cls, v: Any) -> int:
        if isinstance(v, str):
            v = v.strip()
            if not v.isdigit():
                return 0
            return int(v)
        return int(v) if v else 0

    model_config = _COMMON_CONFIG


class GeminiSettings(BaseSettings):
    """Google Gemini AI settings."""

    api_key: str = Field(default="", alias="GEMINI_API_KEY")
    model: str = "gemini-3.6-flash"
    max_tokens: int = 2048
    temperature: float = 0.3  # Low temp for factual analysis

    model_config = _COMMON_CONFIG


class NewsSettings(BaseSettings):
    """News API settings."""

    finnhub_api_key: str = Field(default="", alias="FINNHUB_API_KEY")
    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")

    model_config = _COMMON_CONFIG


class TelegramSettings(BaseSettings):
    """Telegram bot settings."""

    bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    model_config = _COMMON_CONFIG


class DashboardSettings(BaseSettings):
    """Web dashboard settings."""

    secret_key: str = Field(default="change-me-in-production", alias="DASHBOARD_SECRET_KEY")
    username: str = Field(default="admin", alias="DASHBOARD_USERNAME")
    password: str = Field(default="", alias="DASHBOARD_PASSWORD")
    host: str = Field(default="127.0.0.1", alias="DASHBOARD_HOST")
    port: int = 8080

    model_config = _COMMON_CONFIG


class DatabaseSettings(BaseSettings):
    """Database settings."""

    url: str = Field(
        default=f"sqlite:///{DATA_DIR / 'trading_bot.db'}",
        alias="DATABASE_URL",
    )
    echo: bool = False  # Set True for SQL debug logging

    model_config = _COMMON_CONFIG


class Settings(BaseSettings):
    """Master settings — aggregates all sub-settings."""

    # Sub-settings
    mt5: MT5Settings = MT5Settings()
    gemini: GeminiSettings = GeminiSettings()
    news: NewsSettings = NewsSettings()
    telegram: TelegramSettings = TelegramSettings()
    dashboard: DashboardSettings = DashboardSettings()
    database: DatabaseSettings = DatabaseSettings()

    # Trading parameters (loaded from YAML)
    trading_params: dict[str, Any] = Field(default_factory=load_trading_params)

    # Global flags
    demo_mode: bool = True  # Start in demo mode for safety
    log_level: str = "INFO"

    model_config = {
        "env_file": _ENV_FILE,
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    # ── Convenience accessors ────────────────────────────────────────────

    @property
    def symbol(self) -> str:
        suffix = self.trading_params.get("symbol_suffix", "")
        return self.trading_params.get("symbol", "XAUUSD") + suffix

    @property
    def risk_params(self) -> dict:
        return self.trading_params.get("risk", {})

    @property
    def scalping_params(self) -> dict:
        return self.trading_params.get("scalping", {})

    @property
    def day_trading_params(self) -> dict:
        return self.trading_params.get("day_trading", {})

    @property
    def swing_trading_params(self) -> dict:
        return self.trading_params.get("swing_trading", {})

    @property
    def regime_params(self) -> dict:
        return self.trading_params.get("regime", {})

    @property
    def ai_params(self) -> dict:
        return self.trading_params.get("ai", {})

    @property
    def news_params(self) -> dict:
        return self.trading_params.get("news", {})

    @property
    def confluence_weights(self) -> dict:
        return self.trading_params.get("confluence", {})

    @property
    def trailing_stop_params(self) -> dict:
        return self.trading_params.get("trailing_stop", {})

    @property
    def session_config(self) -> dict:
        return self.trading_params.get("sessions", {})


# ── Singleton ──────────────────────────────────────────────────────────────
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the singleton settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
