"""Unit tests for V3 Institutional Fixes:
1. Ranging regime trend direction neutrality (NEUTRAL trend in RANGING)
2. Signal aggregator threshold scaling when AI is in HOLD / Neutral
3. Strategy attribution in sync_positions and close_trade (preventing misattribution)
4. Time-decay rehabilitation of penalized strategy multipliers
5. Responsive Higher-TF trend alignment (ADX + EMA directional detection)
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

from ai.trade_learner import TradeLearner
from database import crud
from database.models import Trade
from execution.trade_executor import TradeExecutor
from strategies.base_strategy import SignalDirection, TradingSignal
from strategies.regime_detector import MarketRegime, RegimeDetector
from strategies.scalping import ScalpingStrategy
from strategies.signal_aggregator import SignalAggregator


def test_ranging_regime_is_neutral():
    """Verify that a ranging market assigns NEUTRAL trend direction and allows oscillations."""
    detector = RegimeDetector()
    df = pd.DataFrame({
        "close": [2000.0] * 60,
        "adx": [18.0] * 60,       # Low ADX < 25 -> RANGING
        "di_plus": [22.0] * 60,   # Even with di_plus > di_minus
        "di_minus": [15.0] * 60,
        "atr": [1.5] * 60,
    })
    analysis = detector.analyze(df)
    assert analysis.regime == MarketRegime.RANGING
    assert analysis.trend_direction == "NEUTRAL", "Ranging regime must be trend-neutral"


def test_signal_aggregator_ranging_not_counter_trend():
    """Verify that in RANGING regime, SELL signals are not vetoed as counter-trend."""
    agg = SignalAggregator()
    signal = TradingSignal(
        direction=SignalDirection.SELL,
        strategy="scalping",
        timeframe="M5",
        confidence=80.0,
        entry_price=2000.0,
        stop_loss=2005.0,
        take_profit=1990.0,
        risk_reward_ratio=2.0,
        technical_score=80.0,
    )
    regime_info = {
        "regime": "RANGING",
        "trend_direction": "NEUTRAL",
        "adx": 18.0,
        "is_recommended": True,
        "position_modifier": 0.7,
        "allow_counter_trend": False,
    }
    result = agg.calculate_confluence(
        strategy_signal=signal,
        ai_prediction={"direction": "HOLD", "confidence": 0.4},
        sentiment={"direction": "NEUTRAL", "score": 0.0},
        regime_analysis=regime_info,
        min_score=50.0,
    )
    # Ensure it was not vetoed as counter-trend
    assert not any("Counter-trend entries prohibited" in r for r in result.reasons)
    assert result.regime_score > 0, "Regime score should be positive in recommended ranging"


def test_signal_aggregator_ai_hold_threshold_scaling():
    """Verify that when AI is in HOLD, threshold scales so strong technical setups can execute."""
    agg = SignalAggregator()
    signal = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="scalping",
        timeframe="M5",
        confidence=85.0,
        entry_price=2000.0,
        stop_loss=1995.0,
        take_profit=2010.0,
        risk_reward_ratio=2.0,
        technical_score=85.0,
    )
    regime_info = {
        "regime": "MODERATE_TREND_UP",
        "trend_direction": "UP",
        "adx": 28.0,
        "is_recommended": True,
        "position_modifier": 1.0,
        "allow_counter_trend": False,
    }
    result = agg.calculate_confluence(
        strategy_signal=signal,
        ai_prediction={"direction": "HOLD", "confidence": 0.4},
        sentiment={"direction": "NEUTRAL", "score": 0.0},
        regime_analysis=regime_info,
        min_score=50.0,
    )
    # Total score should meet the scaled target
    assert result.should_execute is True, "High-conviction technical setup must execute when AI is neutral HOLD"


def test_trade_learner_rehabilitation():
    """Verify that a penalized strategy recovers its multiplier after period of dormancy."""
    learner = TradeLearner()
    learner.strategy_multipliers["scalping"] = 0.45  # severely penalized

    # Screen with simulated dormant memory (> 12h ago)
    old_time = (datetime.now(timezone.utc) - timedelta(hours=18)).isoformat()
    learner.mistake_memory = [{
        "strategy": "scalping",
        "direction": "BUY",
        "timestamp": old_time,
        "trap_type": "marginal_confluence",
        "regime_family": "RANGING",
    }]

    approved, reason, penalty = learner.screen_prospective_signal(
        strategy_name="scalping",
        direction="BUY",
        confluence_score=60.0,
        regime_val="RANGING",
    )
    # The multiplier should have rehabilitated from 0.45 towards 1.0 (exceeding 0.55)
    assert learner.strategy_multipliers["scalping"] > 0.55
    assert approved is True


def test_trade_executor_sync_positions_preserves_strategy():
    """Verify that sync_positions preserves exact trade strategy to prevent misattribution."""
    mock_mt5 = MagicMock()
    mock_mt5.get_open_positions.return_value = []  # No positions in MT5 (all closed)
    mock_mt5.get_closed_deal_info.return_value = {
        "exit_price": 2005.0,
        "profit": -50.0,
        "swap": 0.0,
        "commission": 0.0,
        "comment": "SL hit",
        "time": datetime.now(timezone.utc),
    }
    mock_risk = MagicMock()

    executor = TradeExecutor(mt5=mock_mt5, risk_manager=mock_risk)

    mock_trade = MagicMock()
    mock_trade.ticket = 99999
    mock_trade.strategy = "day_trading"
    mock_trade.symbol = "XAUUSD"
    mock_trade.order_type = "BUY"
    mock_trade.entry_price = 2010.0
    mock_trade.regime = "MODERATE_TREND_DOWN"
    mock_trade.confluence_score = 58.0
    mock_trade.sentiment_score = 0.2

    with patch("database.crud.get_open_trades", return_value=[mock_trade]), \
         patch("database.crud.close_trade"), \
         patch.object(mock_mt5, "get_historical_trades", return_value=[]):
        closed = executor.sync_positions()
        assert len(closed) == 1
        assert closed[0]["strategy"] == "day_trading", "Must preserve original strategy to prevent misattribution"
        assert closed[0]["regime"] == "MODERATE_TREND_DOWN"
