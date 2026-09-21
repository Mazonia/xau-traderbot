"""
Unit tests for Strategies, Regime Detection, and Confluence Scoring.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.technical import TechnicalAnalyzer
from strategies.base_strategy import SignalDirection, TradingSignal
from strategies.day_trading import DayTradingStrategy
from strategies.regime_detector import RegimeDetector
from strategies.scalping import ScalpingStrategy
from strategies.signal_aggregator import SignalAggregator
from strategies.swing_trading import SwingTradingStrategy


@pytest.fixture
def sample_indicators_df():
    """Create a sample dataframe with full technical indicators."""
    np.random.seed(123)
    n = 250
    base_price = 2650.0
    drift = np.linspace(0, 30, n)
    noise = np.random.normal(0, 2, n)
    closes = base_price + drift + noise

    df = pd.DataFrame({
        "open": closes - 0.5,
        "high": closes + 2.0,
        "low": closes - 2.0,
        "close": closes,
        "volume": [1000] * n,
    })
    ta = TechnicalAnalyzer()
    return ta.add_all_indicators(df)


def test_regime_detector(sample_indicators_df):
    detector = RegimeDetector()
    analysis = detector.analyze(sample_indicators_df)
    assert analysis.regime is not None
    assert isinstance(analysis.recommended_strategies, list)
    assert analysis.position_size_modifier > 0


def test_scalping_strategy_run(sample_indicators_df):
    strategy = ScalpingStrategy()
    sig = strategy.run(sample_indicators_df)
    assert isinstance(sig, TradingSignal)
    assert sig.direction in (SignalDirection.BUY, SignalDirection.SELL, SignalDirection.HOLD)


def test_day_trading_strategy_run(sample_indicators_df):
    strategy = DayTradingStrategy()
    sig = strategy.run(sample_indicators_df)
    assert isinstance(sig, TradingSignal)
    assert sig.strategy_name == "day_trading"


def test_swing_trading_strategy_run(sample_indicators_df):
    strategy = SwingTradingStrategy()
    sig = strategy.run(sample_indicators_df)
    assert isinstance(sig, TradingSignal)
    assert sig.strategy_name == "swing_trading"


def test_confluence_aggregator_high_score():
    agg = SignalAggregator()
    buy_sig = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="day_trading",
        timeframe="H1",
        confidence=90.0,
        stop_loss=2640.0,
        take_profit=2670.0,
    )

    confluence = agg.calculate_confluence(
        strategy_signal=buy_sig,
        ai_prediction={"direction": "BUY", "confidence": 0.85},
        sentiment={"direction": "BULLISH", "score": 0.8},
        regime_analysis={"is_recommended": True, "position_modifier": 1.0},
        min_score=65.0,
    )
    assert confluence.direction == SignalDirection.BUY
    assert confluence.total_score >= 65.0
    assert confluence.should_execute is True


def test_confluence_aggregator_opposing_sentiment():
    agg = SignalAggregator()
    buy_sig = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="day_trading",
        timeframe="H1",
        confidence=50.0,
        stop_loss=2640.0,
        take_profit=2670.0,
    )

    # Opposing sentiment: BUY strategy but heavily BEARISH news
    confluence = agg.calculate_confluence(
        strategy_signal=buy_sig,
        ai_prediction={"direction": "SELL", "confidence": 0.7},
        sentiment={"direction": "BEARISH", "score": -0.9},
        regime_analysis={"is_recommended": False, "position_modifier": 0.5},
        min_score=65.0,
    )
    assert confluence.should_execute is False
