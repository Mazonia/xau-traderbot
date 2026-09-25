"""
Base Strategy — Abstract class for all trading strategies.

Every strategy must implement:
- analyze(): Process market data and indicators
- generate_signal(): Produce a BUY/SELL/HOLD signal with confidence
- get_sl_tp(): Calculate stop-loss and take-profit levels
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import pandas as pd


class SignalDirection(Enum):
    """Trading signal direction."""
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


@dataclass
class TradingSignal:
    """Represents a trading signal from a strategy."""

    direction: SignalDirection
    strategy: str
    timeframe: str
    confidence: float = 0.0          # 0-100 score
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    risk_reward_ratio: float = 0.0
    technical_score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_actionable(self) -> bool:
        """Whether this signal suggests opening a trade."""
        return self.direction != SignalDirection.HOLD and self.confidence > 0

    @property
    def strategy_name(self) -> str:
        """Alias for self.strategy."""
        return self.strategy

    def __repr__(self):
        return (
            f"<Signal {self.direction.value} | {self.strategy} {self.timeframe} | "
            f"confidence={self.confidence:.1f} | RR={self.risk_reward_ratio:.1f}>"
        )


class BaseStrategy(ABC):
    """
    Abstract base class for all trading strategies.

    Subclasses must implement:
    - analyze(df): Process data and return analysis dict
    - generate_signal(df, analysis): Produce a TradingSignal
    - get_sl_tp(df, direction): Return (stop_loss, take_profit) tuple
    """

    def __init__(self, name: str, params: dict):
        self.name = name
        self.params = params
        self.enabled = params.get("enabled", True)
        self._last_active_mode: Optional[str] = None
        self._min_confluence_score_override: Optional[float] = None
        self._default_sessions = params.get("active_sessions", [])
        self._last_signal: Optional[TradingSignal] = None

    def _check_mode_sync(self):
        """Ensure overrides are reset if the trading mode changes."""
        try:
            from config.settings import get_settings
            current_mode = get_settings().active_mode
            if getattr(self, "_last_active_mode", None) != current_mode:
                self._last_active_mode = current_mode
                self._min_confluence_score_override = None
        except Exception:
            pass

    def clear_overrides(self):
        """Explicitly clear temporary confluence overrides."""
        self._min_confluence_score_override = None

    @property
    def min_confluence_score(self) -> float:
        self._check_mode_sync()
        if self._min_confluence_score_override is not None:
            return self._min_confluence_score_override
        try:
            from config.settings import get_settings
            settings = get_settings()
            if self.name == "scalping":
                return float(settings.scalping_params.get("min_confluence_score", 50.0))
            elif self.name == "day_trading":
                return float(settings.day_trading_params.get("min_confluence_score", 55.0))
            elif self.name == "swing_trading":
                return float(settings.swing_trading_params.get("min_confluence_score", 60.0))
        except Exception:
            pass
        return float(self.params.get("min_confluence_score", 65.0))

    @min_confluence_score.setter
    def min_confluence_score(self, val: float):
        self._min_confluence_score_override = val

    @property
    def active_sessions(self) -> list[str]:
        try:
            from config.settings import get_settings
            settings = get_settings()
            if self.name == "scalping":
                return settings.scalping_params.get("active_sessions", self._default_sessions)
            elif self.name == "day_trading":
                return settings.day_trading_params.get("active_sessions", self._default_sessions)
            elif self.name == "swing_trading":
                return settings.swing_trading_params.get("active_sessions", self._default_sessions)
        except Exception:
            pass
        return self._default_sessions

    @active_sessions.setter
    def active_sessions(self, val: list[str]):
        self._default_sessions = val

    @property
    def min_technical_score(self) -> float:
        """Threshold for the strategy itself to emit a directional signal instead of HOLD."""
        try:
            from config.settings import get_settings
            settings = get_settings()
            if self.name == "scalping":
                return float(settings.scalping_params.get("min_technical_score", 35.0))
            elif self.name == "day_trading":
                return float(settings.day_trading_params.get("min_technical_score", 35.0))
            elif self.name == "swing_trading":
                return float(settings.swing_trading_params.get("min_technical_score", 35.0))
        except Exception:
            pass
        return 35.0

    @abstractmethod
    def analyze(self, df: pd.DataFrame) -> dict:
        """
        Analyze market data and compute strategy-specific indicators.

        Args:
            df: OHLCV DataFrame with technical indicators already added.

        Returns:
            Analysis dict with strategy-specific metrics.
        """
        pass

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, analysis: dict) -> TradingSignal:
        """
        Generate a trading signal based on the analysis.

        Args:
            df: OHLCV DataFrame with indicators.
            analysis: Output from self.analyze().

        Returns:
            TradingSignal with direction, confidence, SL/TP, and reasons.
        """
        pass

    @abstractmethod
    def get_sl_tp(
        self,
        df: pd.DataFrame,
        direction: SignalDirection,
        entry_price: float,
    ) -> tuple[float, float]:
        """
        Calculate stop-loss and take-profit levels.

        Args:
            df: OHLCV DataFrame with ATR calculated.
            direction: BUY or SELL
            entry_price: The expected entry price.

        Returns:
            Tuple of (stop_loss, take_profit) prices.
        """
        pass

    def run(self, df: pd.DataFrame) -> TradingSignal:
        """
        Full strategy pipeline: analyze → generate signal.

        This is the main entry point called by the bot.
        """
        if not self.enabled:
            return TradingSignal(
                direction=SignalDirection.HOLD,
                strategy=self.name,
                timeframe="",
                reasons=["Strategy is disabled"],
            )

        if len(df) < 200:  # Need enough data for indicators
            return TradingSignal(
                direction=SignalDirection.HOLD,
                strategy=self.name,
                timeframe="",
                reasons=["Insufficient data for analysis"],
            )

        analysis = self.analyze(df)
        signal = self.generate_signal(df, analysis)
        self._last_signal = signal
        return signal

    @property
    def last_signal(self) -> Optional[TradingSignal]:
        return self._last_signal
