"""
Tests for Performance & Self-Improvement Fixes:
1. Strategy duplicate position prevention (no cluster spamming)
2. Global and strategy cooldown enforcement
3. MT5 comment sanitization & safe truncation (< 28 chars, safe ASCII)
4. Counter-trend veto when allow_counter_trend is false
5. Phantom confluence point eradication (AI HOLD & Sentiment NEUTRAL give 0)
6. Trailing stop partial profit booking
"""

from unittest.mock import MagicMock
import pytest
from datetime import datetime, timezone, timedelta

from execution.risk_manager import RiskManager
from core.mt5_connector import MT5Connector
from strategies.base_strategy import TradingSignal, SignalDirection
from strategies.signal_aggregator import SignalAggregator
from execution.trailing_stop import TrailingStopManager


@pytest.fixture
def mock_mt5():
    mock = MagicMock()
    mock.get_account_info.return_value = {
        "balance": 10000.0,
        "margin": 100.0,
        "margin_free": 9900.0,
        "margin_level": 9900.0,
        "trade_allowed": True,
    }
    mock.get_symbol_info.return_value = {
        "trade_contract_size": 100,
        "point": 0.01,
        "volume_step": 0.01,
        "volume_min": 0.01,
        "volume_max": 100.0,
    }
    mock.get_current_tick.return_value = {
        "bid": 2650.0,
        "ask": 2650.25,
        "spread": 25,
    }
    mock.get_open_positions.return_value = []
    return mock


def test_duplicate_strategy_prevention(mock_mt5, monkeypatch):
    """Test that a strategy cannot open duplicate positions."""
    monkeypatch.setattr("database.crud.get_daily_pnl", lambda: 0.0)
    monkeypatch.setattr("database.crud.get_open_trades", lambda: [])

    rm = RiskManager(mock_mt5)

    # 1. No open positions -> allowed
    allowed, reason = rm.can_trade("XAUUSD", strategy="day_trading")
    assert allowed is True

    # 2. Existing open position with comment containing "day_trading"
    mock_mt5.get_open_positions.return_value = [
        {"ticket": 12345, "symbol": "XAUUSD", "comment": "day_trading|conf=62", "type": "BUY"}
    ]
    allowed, reason = rm.can_trade("XAUUSD", strategy="day_trading")
    assert allowed is False
    assert "already has an active open position" in reason

    # 3. Scalping strategy is NOT blocked by day_trading's position
    allowed_scalp, reason_scalp = rm.can_trade("XAUUSD", strategy="scalping")
    assert allowed_scalp is True


def test_strategy_cooldown_enforcement(mock_mt5, monkeypatch):
    """Test that cooldown timer prevents rapid-fire consecutive entries."""
    monkeypatch.setattr("database.crud.get_daily_pnl", lambda: 0.0)
    monkeypatch.setattr("database.crud.get_open_trades", lambda: [])

    rm = RiskManager(mock_mt5)
    # Simulate a trade just executed for scalping
    rm.record_trade_execution(strategy="scalping")

    # Immediate next trade attempt should be blocked by cooldown
    allowed, reason = rm.can_trade("XAUUSD", strategy="scalping")
    assert allowed is False
    assert "cooldown active" in reason.lower()

    # Fast forward time beyond cooldown
    rm._global_last_trade_time = datetime.now(timezone.utc) - timedelta(seconds=200)
    rm._last_trade_times["scalping"] = datetime.now(timezone.utc) - timedelta(seconds=400)

    allowed_after, reason_after = rm.can_trade("XAUUSD", strategy="scalping")
    assert allowed_after is True


def test_mt5_comment_sanitization():
    """Test that MT5 connector truncates and sanitizes comment to avoid (-2, 'Invalid comment argument')."""
    long_dirty_comment = "close_smart_midway:Structural Breakdown: Lost prior swing low by 1.2 ATR"
    clean = MT5Connector._sanitize_comment(long_dirty_comment, max_len=27)

    assert len(clean) <= 27
    assert ":" not in clean
    assert " " not in clean
    # Should only contain safe chars
    for ch in clean:
        assert ch.isalnum() or ch in "_-"


def test_counter_trend_veto():
    """Test that counter-trend signals are vetoed when allow_counter_trend is False."""
    aggregator = SignalAggregator()
    buy_signal = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="day_trading",
        timeframe="H1",
        confidence=75.0,
        entry_price=4000.0,
        stop_loss=3980.0,
        take_profit=4040.0,
        risk_reward_ratio=2.0,
        technical_score=75.0,
    )

    # In a downtrend (MODERATE_TREND_DOWN) with allow_counter_trend = False
    confluence = aggregator.calculate_confluence(
        strategy_signal=buy_signal,
        ai_prediction={"direction": "HOLD", "confidence": 0.45},
        sentiment={"direction": "NEUTRAL", "score": 0.0},
        regime_analysis={
            "is_recommended": False,
            "regime": "MODERATE_TREND_DOWN",
            "trend_direction": "DOWN",
            "allow_counter_trend": False,
        },
        min_score=55.0,
    )

    # Should be vetoed because buying into a downtrend is counter-trend
    assert confluence.should_execute is False
    assert any("counter-trend" in r.lower() or "vetoed" in r.lower() for r in confluence.reasons)


def test_phantom_points_eradicated():
    """Test that AI HOLD and Sentiment NEUTRAL give 0 bonus points instead of phantom points."""
    aggregator = SignalAggregator()
    signal = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="scalping",
        timeframe="M5",
        confidence=40.0,  # Weak technical setup
        entry_price=4000.0,
        stop_loss=3990.0,
        take_profit=4015.0,
        risk_reward_ratio=1.5,
        technical_score=40.0,
    )

    confluence = aggregator.calculate_confluence(
        strategy_signal=signal,
        ai_prediction={"direction": "HOLD", "confidence": 0.40},
        sentiment={"direction": "NEUTRAL", "score": 0.0},
        regime_analysis={"is_recommended": True, "regime": "RANGING", "trend_direction": "NEUTRAL"},
        min_score=60.0,
    )

    # AI and Sentiment should contribute exactly 0.0 pts
    assert confluence.ai_score == 0.0
    assert confluence.sentiment_score == 0.0
    # Confluence should NOT reach min_score
    assert confluence.should_execute is False


def test_trailing_stop_partial_close(mock_mt5):
    """Test that trailing stop manager executes partial close when 1R target is reached."""
    mock_mt5.get_open_positions.return_value = [
        {
            "ticket": 9999,
            "symbol": "XAUUSD",
            "type": "BUY",
            "volume": 0.04,
            "price_open": 4000.0,
            "price_current": 4015.0,  # +15 points profit
            "sl": 3990.0,             # SL distance = 10 points -> 1R = 4010.0
            "tp": 4030.0,
        }
    ]
    mock_mt5.close_position.return_value = True
    mock_mt5.modify_position.return_value = True

    ts = TrailingStopManager(mock_mt5)
    ts.breakeven_rr = 1.0
    ts.partial_close_pct = 50

    ts.update_all_positions(current_atr=2.0)

    # partial close should have been called for 50% of 0.04 = 0.02 lots
    mock_mt5.close_position.assert_called_once_with(9999, volume=0.02, comment="tp1_partial")
    assert 9999 in ts._partial_closed
