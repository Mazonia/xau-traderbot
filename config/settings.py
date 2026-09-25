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

    # ── Trading Modes ────────────────────────────────────────────────────
    @property
    def active_mode(self) -> str:
        """Get the current active trading mode (safe, moderate, aggressive)."""
        return str(self.trading_params.get("active_mode", "moderate")).lower().strip()

    @property
    def trading_modes(self) -> dict:
        """Get all defined trading mode presets."""
        return self.trading_params.get("trading_modes", {})

    @property
    def active_mode_config(self) -> dict:
        """Get the configuration dictionary for the currently active mode."""
        modes = self.trading_modes
        return modes.get(self.active_mode, modes.get("moderate", {}))

    def set_active_mode(self, mode_name: str) -> bool:
        """
        Switch active trading mode and persist to trading_params.yaml.
        Valid modes: 'safe', 'moderate', 'aggressive'.
        """
        clean_name = mode_name.lower().strip()
        modes = self.trading_modes
        if clean_name not in modes:
            return False

        self.trading_params["active_mode"] = clean_name

        # Persist to YAML file
        params_path = CONFIG_DIR / "trading_params.yaml"
        if params_path.exists():
            try:
                with open(params_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                data["active_mode"] = clean_name
                with open(params_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(data, f, sort_keys=False)
            except Exception as e:
                import logging
                logging.getLogger("Settings").error(f"Failed to persist active mode to YAML: {e}")

        return True

    # ── Convenience accessors ────────────────────────────────────────────

    @property
    def symbol(self) -> str:
        suffix = self.trading_params.get("symbol_suffix", "")
        return self.trading_params.get("symbol", "XAUUSD") + suffix

    @property
    def risk_params(self) -> dict:
        params = dict(self.trading_params.get("risk", {}))
        mode_cfg = self.active_mode_config
        if mode_cfg:
            if "max_risk_per_trade_pct" in mode_cfg:
                params["max_risk_per_trade_pct"] = mode_cfg["max_risk_per_trade_pct"]
            if "max_daily_loss_pct" in mode_cfg:
                params["max_daily_loss_pct"] = mode_cfg["max_daily_loss_pct"]
            if "max_concurrent_trades" in mode_cfg:
                params["max_concurrent_trades"] = mode_cfg["max_concurrent_trades"]
            if "max_spread_points" in mode_cfg:
                params["max_spread_points"] = mode_cfg["max_spread_points"]
            if "default_lot_size" in mode_cfg:
                params["default_lot_size"] = mode_cfg["default_lot_size"]
            if "max_lot_size" in mode_cfg:
                params["max_lot_size"] = mode_cfg["max_lot_size"]
            if "max_slippage_points" in mode_cfg:
                params["max_slippage_points"] = mode_cfg["max_slippage_points"]
        return params

    @property
    def scalping_params(self) -> dict:
        params = dict(self.trading_params.get("scalping", {}))
        mode_cfg = self.active_mode_config
        if mode_cfg:
            if "scalping_min_confluence" in mode_cfg:
                params["min_confluence_score"] = mode_cfg["scalping_min_confluence"]
            if "pullback_tolerance_pct" in mode_cfg:
                params["pullback_tolerance_pct"] = mode_cfg["pullback_tolerance_pct"]
            if "min_technical_score" in mode_cfg:
                params["min_technical_score"] = mode_cfg["min_technical_score"]
            if "allow_counter_trend" in mode_cfg:
                params["allow_counter_trend"] = mode_cfg["allow_counter_trend"]
            if "active_sessions" in mode_cfg:
                params["active_sessions"] = mode_cfg["active_sessions"]
        return params

    @property
    def day_trading_params(self) -> dict:
        params = dict(self.trading_params.get("day_trading", {}))
        mode_cfg = self.active_mode_config
        if mode_cfg:
            if "day_trading_min_confluence" in mode_cfg:
                params["min_confluence_score"] = mode_cfg["day_trading_min_confluence"]
            if "min_technical_score" in mode_cfg:
                params["min_technical_score"] = mode_cfg["min_technical_score"]
            if "allow_counter_trend" in mode_cfg:
                params["allow_counter_trend"] = mode_cfg["allow_counter_trend"]
            if "active_sessions" in mode_cfg:
                params["active_sessions"] = mode_cfg["active_sessions"]
        return params

    @property
    def swing_trading_params(self) -> dict:
        params = dict(self.trading_params.get("swing_trading", {}))
        mode_cfg = self.active_mode_config
        if mode_cfg:
            if "swing_trading_min_confluence" in mode_cfg:
                params["min_confluence_score"] = mode_cfg["swing_trading_min_confluence"]
            if "min_technical_score" in mode_cfg:
                params["min_technical_score"] = mode_cfg["min_technical_score"]
            if "allow_counter_trend" in mode_cfg:
                params["allow_counter_trend"] = mode_cfg["allow_counter_trend"]
            if "active_sessions" in mode_cfg:
                params["active_sessions"] = mode_cfg["active_sessions"]
        return params

    @property
    def regime_params(self) -> dict:
        params = dict(self.trading_params.get("regime", {}))
        mode_cfg = self.active_mode_config
        if mode_cfg and "regime_strictness" in mode_cfg:
            params["regime_strictness"] = mode_cfg["regime_strictness"]
        return params

    @property
    def ai_params(self) -> dict:
        params = dict(self.trading_params.get("ai", {}))
        mode_cfg = self.active_mode_config
        if mode_cfg and "min_ai_confidence" in mode_cfg:
            params["prediction_confidence_threshold"] = mode_cfg["min_ai_confidence"]
        return params

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
