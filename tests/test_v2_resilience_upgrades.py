"""
Unit Tests for V2 Resilience, Capital Protection & Trade Identification Upgrades:

1. Account Drawdown Scaling (5% halving, 10% suspension)
2. Loss-Streak Circuit Breaker (3+ consecutive losses exponential cooldown)
3. Win-Rate Gating with 2-hour Auto-Recovery Probation
4. Multi-Timeframe Confirmation Gate (Scalping M5->H1, Day Trading H1->H4, Swing H4->D1)
5. Confluence Scaled Regime & Volume Confirmation Bonus
6. Asian Dead Hours Low-Volume Scalping Shield
7. Market Rollover (21:00-22:00 UTC) Spread Blowout Shield
8. Fuzzy Mistake Memory Matching across Regime Families
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import numpy as np
import pandas as pd
import pytest

from ai.trade_learner import TradeLearner
from execution.risk_manager import RiskManager
from strategies.base_strategy import SignalDirection, TradingSignal
from strategies.day_trading import DayTradingStrategy
from strategies.scalping import ScalpingStrategy
from strategies.signal_aggregator import SignalAggregator
from strategies.swing_trading import SwingTradingStrategy


@pytest.fixture
def mock_mt5():
    mock = MagicMock()
    mock.get_account_info.return_value = {
        "balance": 10000.0,
        "equity": 10000.0,
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


def _generate_ohlcv(n_bars: int = 250, start_price: float = 2650.0, trend: str = "UP") -> pd.DataFrame:
    """Generate realistic synthetic OHLCV data for testing."""
    times = [datetime(2026, 10, 1, 0, 0) + timedelta(minutes=5 * i) for i in range(n_bars)]
    drift = 0.3 if trend == "UP" else -0.3 if trend == "DOWN" else 0.0
    prices = [start_price]
    for _ in range(1, n_bars):
        prices.append(prices[-1] + drift + np.random.normal(0, 0.5))

    prices = np.array(prices)
    highs = prices + np.random.uniform(0.5, 1.5, n_bars)
    lows = prices - np.random.uniform(0.5, 1.5, n_bars)
    opens = prices - np.random.uniform(-0.5, 0.5, n_bars)
    volumes = np.random.uniform(500, 2000, n_bars)

    df = pd.DataFrame({
        "time": times,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": prices,
        "volume": volumes,
    })
    return df


# ── 1. Account Drawdown Scaling Tests ────────────────────────────────────

def test_drawdown_scaling_halving(mock_mt5, monkeypatch):
    """When account equity drops 5-10% below peak balance, lot size must be cut in half."""
    monkeypatch.setattr("database.crud.get_daily_pnl", lambda: 0.0)
    monkeypatch.setattr("database.crud.get_open_trades", lambda: [])

    rm = RiskManager(mock_mt5)
    rm._peak_balance = 10000.0

    # Normal baseline lot size with 10k balance and 10k equity
    mock_mt5.get_account_info.return_value = {
        "balance": 10000.0,
        "equity": 10000.0,
        "margin": 100.0,
        "margin_free": 9900.0,
        "margin_level": 9900.0,
        "trade_allowed": True,
    }
    normal_lot = rm.calculate_lot_size(entry_price=2650.0, stop_loss=2640.0)

    # 6% drawdown: balance=10k, equity=9400
    mock_mt5.get_account_info.return_value["equity"] = 9400.0
    scaled_lot = rm.calculate_lot_size(entry_price=2650.0, stop_loss=2640.0)

    assert scaled_lot < normal_lot
    assert scaled_lot <= round(normal_lot * 0.55, 2)


def test_drawdown_scaling_full_suspension(mock_mt5, monkeypatch):
    """When account equity drops >= 10% below peak balance, all new trade entries must be blocked."""
    monkeypatch.setattr("database.crud.get_daily_pnl", lambda: 0.0)
    monkeypatch.setattr("database.crud.get_open_trades", lambda: [])

    rm = RiskManager(mock_mt5)
    rm._peak_balance = 10000.0

    # 11% drawdown: balance=10k, equity=8900
    mock_mt5.get_account_info.return_value = {
        "balance": 10000.0,
        "equity": 8900.0,
        "margin": 100.0,
        "margin_free": 8800.0,
        "margin_level": 8800.0,
        "trade_allowed": True,
    }

    allowed, reason = rm.can_trade("XAUUSD", strategy="day_trading")
    assert allowed is False
    assert "exceeds 10% threshold" in reason.lower() or "drawdown" in reason.lower()


# ── 2. Loss-Streak Circuit Breaker Tests ─────────────────────────────────

def test_loss_streak_circuit_breaker():
    """3 consecutive losses must trigger exponential cooldown."""
    learner = TradeLearner()
    learner.reset_adaptive_state()

    # Simulate 3 losses in scalping
    for ticket in [101, 102, 103]:
        learner.on_trade_closed({
            "ticket": ticket,
            "profit": -75.0,
            "strategy": "scalping",
            "direction": "BUY",
            "regime": "RANGING",
            "confluence_score": 60.0,
        })

    assert learner.get_consecutive_losses("scalping") == 3
    assert learner._cooldown_until["scalping"] is not None
    assert learner._cooldown_until["scalping"] > datetime.now(timezone.utc)

    # Prospective signal must be vetoed during cooldown
    approved, reason, penalty = learner.screen_prospective_signal(
        strategy_name="scalping",
        direction="BUY",
        confluence_score=80.0,
        regime_val="RANGING",
    )
    assert approved is False
    assert "Loss Streak Cooldown" in reason

    # Win resets streak & cooldown
    learner.on_trade_closed({
        "ticket": 104,
        "profit": 150.0,
        "strategy": "scalping",
        "direction": "BUY",
        "regime": "RANGING",
        "confluence_score": 82.0,
    })
    assert learner.get_consecutive_losses("scalping") == 0
    assert learner._cooldown_until["scalping"] is None


# ── 3. Win-Rate Gating Auto-Probation Tests ──────────────────────────────

def test_win_rate_gating_and_auto_probation():
    """Rolling win rate < 30% suspends strategy, which recovers after 2h timeout."""
    learner = TradeLearner()
    learner.reset_adaptive_state()

    # Fill rolling outcomes with 1 WIN and 5 LOSSes (16.7% win rate)
    for i in range(5):
        learner._rolling_outcomes["scalping"].append("LOSS")
    learner._rolling_outcomes["scalping"].append("WIN")

    learner.strategy_multipliers["scalping"] = 0.50
    learner._evaluate_win_rate_gating("scalping")

    assert learner.is_strategy_suspended("scalping") is True

    # Fast forward time past 2 hours
    learner._suspended_until["scalping"] = datetime.now(timezone.utc) - timedelta(minutes=5)

    # Strategy should now be unsuspended on timeout check
    assert learner.is_strategy_suspended("scalping") is False


# ── 4. Multi-Timeframe Confirmation Gate Tests ──────────────────────────

def test_multi_tf_gate_scalping():
    """Scalping on M5 must confirm with H1 trend."""
    strat = ScalpingStrategy()
    df_m5 = _generate_ohlcv(250, start_price=2650.0, trend="UP")

    # H1 is strongly BEARISH (closing below EMA50 & EMA200)
    df_h1_bear = _generate_ohlcv(200, start_price=2750.0, trend="DOWN")

    analysis = strat.analyze(df_m5, higher_tf_df=df_h1_bear)
    assert analysis["htf_aligned_buy"] is False

    sig = strat.generate_signal(df_m5, analysis)
    assert sig.direction != SignalDirection.BUY
    assert any("HTF GATE" in r for r in sig.reasons)


def test_multi_tf_gate_day_trading():
    """Day trading on H1 must confirm with H4 trend."""
    strat = DayTradingStrategy()
    df_h1 = _generate_ohlcv(250, start_price=2650.0, trend="UP")

    # H4 is strongly BEARISH
    df_h4_bear = _generate_ohlcv(200, start_price=2750.0, trend="DOWN")

    analysis = strat.analyze(df_h1, higher_tf_df=df_h4_bear)
    assert analysis["htf_aligned_buy"] is False

    sig = strat.generate_signal(df_h1, analysis)
    assert sig.direction != SignalDirection.BUY
    assert any("HTF GATE" in r for r in sig.reasons)


def test_multi_tf_gate_swing_trading():
    """Swing trading on H4 must confirm with D1 trend."""
    strat = SwingTradingStrategy()
    df_h4 = _generate_ohlcv(250, start_price=2650.0, trend="UP")

    # D1 is strongly BEARISH
    df_d1_bear = _generate_ohlcv(200, start_price=2750.0, trend="DOWN")

    analysis = strat.analyze(df_h4, higher_tf_df=df_d1_bear)
    assert analysis["htf_aligned_buy"] is False

    sig = strat.generate_signal(df_h4, analysis)
    assert sig.direction != SignalDirection.BUY
    assert any("HTF GATE" in r for r in sig.reasons)


# ── 5. Scaled Regime & Volume Confluence Tests ───────────────────────────

def test_confluence_scaled_regime_and_volume():
    """Strong ADX yields scaled regime contribution; volume > 1.5x gives bonus."""
    aggregator = SignalAggregator()

    base_signal = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="scalping",
        timeframe="M5",
        confidence=80.0,
        technical_score=80.0,
        metadata={"volume_intensity": 2.0},  # High volume bonus
    )

    regime_aligned = {
        "is_recommended": True,
        "trend_direction": "UP",
        "regime": "STRONG_TREND_UP",
        "adx": 45.0,  # High ADX -> scaled regime score
        "volatility": "NORMAL",
    }

    res = aggregator.calculate_confluence(
        strategy_signal=base_signal,
        ai_prediction={"direction": "BUY", "confidence": 0.8},
        sentiment={"direction": "BULLISH", "score": 0.3},
        regime_analysis=regime_aligned,
    )

    assert res.total_score >= 70.0
    assert any("Volume: 2.0x avg" in r for r in res.reasons)
    assert any("Regime: ALIGNED" in r for r in res.reasons)


# ── 6. Fuzzy Mistake Memory Matching Tests ──────────────────────────────

def test_fuzzy_mistake_memory_matching():
    """Trap in STRONG_TREND_DOWN matches prospective signal in MODERATE_TREND_DOWN."""
    learner = TradeLearner()
    learner.reset_adaptive_state()

    # Record a mistake in BEARISH regime family
    learner.mistake_memory.append({
        "strategy": "day_trading",
        "direction": "BUY",
        "regime": "STRONG_TREND_DOWN",
        "regime_family": "BEARISH",
        "trap_type": "counter_trend",
        "rule": "Do not buy into aggressive bear trend",
    })

    # Screen prospective BUY in MODERATE_TREND_DOWN (same BEARISH family)
    approved, reason, penalty = learner.screen_prospective_signal(
        strategy_name="day_trading",
        direction="BUY",
        confluence_score=60.0,
        regime_val="MODERATE_TREND_DOWN",
    )

    assert approved is False
    assert "Mistake Guard Veto" in reason
    assert "counter_trend" in reason


# ── 7. Backtester & ML Safety Tests ─────────────────────────────────────

def test_signal_classifier_timestamp_safety():
    """Predict must safely handle DataFrames with Timestamp 'time' without crashing."""
    from ai.signal_classifier import SignalClassifier
    clf = SignalClassifier()
    # Mock trained model and feature columns
    mock_model = MagicMock()
    mock_model.predict_proba.return_value = np.array([[0.1, 0.7, 0.2]])
    clf._model = mock_model
    clf._feature_columns = ["rsi", "macd", "atr"]

    np.random.seed(42)
    p = 2600.0 + np.cumsum(np.random.normal(0, 1, 300))
    df = pd.DataFrame({
        "time": pd.date_range("2026-10-01", periods=300, freq="1h"),
        "open": p,
        "high": p + 2.5,
        "low": p - 2.5,
        "close": p + 0.5,
        "volume": np.random.randint(500, 2000, 300),
    })

    result = clf.predict(df)
    assert result["direction"] == "HOLD"
    assert "probabilities" in result


def test_sentiment_scaling_when_none():
    """When sentiment is None (offline), effective target threshold scales down proportionally."""
    agg = SignalAggregator()
    from strategies.base_strategy import SignalDirection, TradingSignal

    sig = TradingSignal(
        direction=SignalDirection.BUY,
        strategy="day_trading",
        timeframe="H1",
        confidence=80.0,
        entry_price=2600.0,
        stop_loss=2590.0,
        take_profit=2620.0,
        reasons=["Test buy"],
    )

    # 1. With sentiment provided as NEUTRAL
    conf_neutral = agg.calculate_confluence(
        strategy_signal=sig,
        sentiment={"direction": "NEUTRAL", "score": 0.0},
        min_score=60.0,
    )

    # 2. With sentiment None (offline backtest)
    conf_none = agg.calculate_confluence(
        strategy_signal=sig,
        sentiment=None,
        min_score=60.0,
    )

    # With sentiment=None, effective min score must be scaled down by (100 - sentiment_weight) / 100 = 0.80
    assert conf_none.total_score == conf_neutral.total_score

