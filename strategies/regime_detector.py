"""
Market Regime Detector

Classifies the current market state to determine which strategy to activate:
- STRONG_TREND: ADX > 40 → Swing trading preferred
- MODERATE_TREND: 25 < ADX < 40 → Day trading preferred
- RANGING: ADX < 25 → Scalping or pause
- HIGH_VOLATILITY: ATR in top percentile → Reduce position size
- NEWS_EVENT: Upcoming high-impact event → Pause trading
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import get_settings


class MarketRegime(Enum):
    """Market regime classifications."""
    STRONG_TREND_UP = "STRONG_TREND_UP"
    STRONG_TREND_DOWN = "STRONG_TREND_DOWN"
    MODERATE_TREND_UP = "MODERATE_TREND_UP"
    MODERATE_TREND_DOWN = "MODERATE_TREND_DOWN"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    NEWS_EVENT = "NEWS_EVENT"


@dataclass
class RegimeAnalysis:
    """Result of regime detection."""
    regime: MarketRegime
    adx_value: float = 0.0
    trend_direction: str = "NEUTRAL"   # UP, DOWN, NEUTRAL
    volatility_percentile: float = 50.0
    volatility_label: str = "NORMAL"   # LOW, NORMAL, HIGH
    recommended_strategies: list[str] = None
    position_size_modifier: float = 1.0  # Multiplier for position sizing
    should_trade: bool = True
    reasons: list[str] = None

    def __post_init__(self):
        if self.recommended_strategies is None:
            self.recommended_strategies = []
        if self.reasons is None:
            self.reasons = []


class RegimeDetector:
    """
    Detects the current market regime using ADX, ATR percentiles,
    and trend analysis to recommend which strategy to activate.
    """

    def __init__(self):
        settings = get_settings()
        params = settings.regime_params

        self.adx_trending = params.get("adx_trending_threshold", 25)
        self.adx_strong = params.get("adx_strong_trend_threshold", 40)
        self.atr_lookback = params.get("atr_lookback_period", 100)
        self.high_vol_pct = params.get("high_volatility_percentile", 80)
        self.low_vol_pct = params.get("low_volatility_percentile", 20)
        self._news_pause_active = False

    def analyze(self, df: pd.DataFrame) -> RegimeAnalysis:
        """
        Analyze the current market regime.

        Args:
            df: DataFrame with ADX, ATR, and EMA indicators computed.

        Returns:
            RegimeAnalysis with regime classification and recommendations.
        """
        if len(df) < self.atr_lookback:
            return RegimeAnalysis(
                regime=MarketRegime.RANGING,
                reasons=["Insufficient data for regime detection"],
                should_trade=False,
            )

        # ── 1. ADX Trend Strength ────────────────────────────────────────
        adx_value = float(df["adx"].iloc[-1]) if "adx" in df.columns else 0.0
        di_plus = float(df["di_plus"].iloc[-1]) if "di_plus" in df.columns else 0.0
        di_minus = float(df["di_minus"].iloc[-1]) if "di_minus" in df.columns else 0.0

        # Determine trend direction from +DI / -DI
        if di_plus > di_minus:
            trend_dir = "UP"
        elif di_minus > di_plus:
            trend_dir = "DOWN"
        else:
            trend_dir = "NEUTRAL"

        # ── 2. Volatility Assessment ────────────────────────────────────
        atr_col = df["atr"].dropna() if "atr" in df.columns else pd.Series()

        if len(atr_col) >= self.atr_lookback:
            current_atr = float(atr_col.iloc[-1])
            atr_history = atr_col.iloc[-self.atr_lookback:]
            vol_percentile = float(
                (atr_history < current_atr).sum() / len(atr_history) * 100
            )
        else:
            vol_percentile = 50.0

        if vol_percentile >= self.high_vol_pct:
            vol_label = "HIGH"
        elif vol_percentile <= self.low_vol_pct:
            vol_label = "LOW"
        else:
            vol_label = "NORMAL"

        # ── 3. Classify Regime ───────────────────────────────────────────
        reasons = []
        recommended = []
        position_modifier = 1.0
        should_trade = True

        # Check for news event pause
        if self._news_pause_active:
            regime = MarketRegime.NEWS_EVENT
            should_trade = False
            position_modifier = 0.0
            reasons.append("Trading paused due to upcoming high-impact news event")
            return RegimeAnalysis(
                regime=regime,
                adx_value=adx_value,
                trend_direction=trend_dir,
                volatility_percentile=vol_percentile,
                volatility_label=vol_label,
                recommended_strategies=recommended,
                position_size_modifier=position_modifier,
                should_trade=should_trade,
                reasons=reasons,
            )

        # Strong trend
        if adx_value >= self.adx_strong:
            if trend_dir == "UP":
                regime = MarketRegime.STRONG_TREND_UP
                reasons.append(f"Strong uptrend (ADX={adx_value:.1f}, +DI > -DI)")
            else:
                regime = MarketRegime.STRONG_TREND_DOWN
                reasons.append(f"Strong downtrend (ADX={adx_value:.1f}, -DI > +DI)")
            recommended = ["swing_trading", "day_trading"]
            position_modifier = 1.2  # Increase size in strong trends

        # Moderate trend
        elif adx_value >= self.adx_trending:
            if trend_dir == "UP":
                regime = MarketRegime.MODERATE_TREND_UP
                reasons.append(f"Moderate uptrend (ADX={adx_value:.1f})")
            else:
                regime = MarketRegime.MODERATE_TREND_DOWN
                reasons.append(f"Moderate downtrend (ADX={adx_value:.1f})")
            recommended = ["day_trading", "scalping"]
            position_modifier = 1.0

        # Ranging
        else:
            regime = MarketRegime.RANGING
            reasons.append(f"Ranging/choppy market (ADX={adx_value:.1f})")
            recommended = ["scalping"]
            position_modifier = 0.7  # Reduce size in ranging markets

        # Adjust for volatility
        if vol_label == "HIGH":
            reasons.append(f"High volatility (ATR percentile: {vol_percentile:.0f}%)")
            position_modifier *= 0.7  # Reduce size in high volatility
            if regime == MarketRegime.RANGING:
                should_trade = False
                reasons.append("Pausing: high volatility + ranging = dangerous")
        elif vol_label == "LOW":
            reasons.append(f"Low volatility (ATR percentile: {vol_percentile:.0f}%)")
            # Low vol ranging is OK for scalping
            if regime != MarketRegime.RANGING:
                position_modifier *= 0.8

        logger.info(
            f"Regime: {regime.value} | ADX: {adx_value:.1f} | "
            f"Vol: {vol_label} ({vol_percentile:.0f}%) | "
            f"Recommended: {recommended}"
        )

        return RegimeAnalysis(
            regime=regime,
            adx_value=adx_value,
            trend_direction=trend_dir,
            volatility_percentile=vol_percentile,
            volatility_label=vol_label,
            recommended_strategies=recommended,
            position_size_modifier=position_modifier,
            should_trade=should_trade,
            reasons=reasons,
        )

    def set_news_pause(self, active: bool):
        """Enable/disable trading pause for news events."""
        self._news_pause_active = active
        if active:
            logger.warning("⚠️ News event pause ACTIVATED — all trading paused")
        else:
            logger.info("✅ News event pause DEACTIVATED — trading resumed")

    def is_strategy_recommended(self, strategy_name: str, regime: RegimeAnalysis) -> bool:
        """Check if a strategy is recommended for the current regime."""
        return strategy_name in regime.recommended_strategies
