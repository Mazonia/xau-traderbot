"""
Unit tests for Backtesting Engine and Performance Metrics.
"""

import pandas as pd
import pytest

from backtesting.backtester import Backtester
from backtesting.performance import BacktestTrade, calculate_metrics


def test_calculate_metrics_empty():
    metrics = calculate_metrics([], initial_balance=10_000.0)
    assert metrics.total_trades == 0
    assert metrics.total_pnl == 0.0
    assert metrics.win_rate == 0.0


def test_calculate_metrics_with_trades():
    trades = [
        BacktestTrade(
            trade_id=1,
            symbol="XAUUSD",
            strategy="day_trading",
            direction="BUY",
            entry_time=None,
            exit_time=None,
            entry_price=2650.0,
            exit_price=2660.0,
            lot_size=0.02,
            pnl=20.0,
            pnl_pips=100.0,
            pnl_pct=0.2,
            exit_reason="TAKE_PROFIT",
            confluence_score=75.0,
            bars_held=5,
        ),
        BacktestTrade(
            trade_id=2,
            symbol="XAUUSD",
            strategy="day_trading",
            direction="SELL",
            entry_time=None,
            exit_time=None,
            entry_price=2660.0,
            exit_price=2665.0,
            lot_size=0.02,
            pnl=-10.0,
            pnl_pips=-50.0,
            pnl_pct=-0.1,
            exit_reason="STOP_LOSS",
            confluence_score=70.0,
            bars_held=3,
        ),
    ]

    m = calculate_metrics(trades, initial_balance=10_000.0)
    assert m.total_trades == 2
    assert m.winning_trades == 1
    assert m.losing_trades == 1
    assert m.win_rate == 50.0
    assert m.total_pnl == 10.0
    assert m.profit_factor == 2.0
    assert m.gross_profit == 20.0
    assert m.gross_loss == 10.0


def test_backtester_benchmark_generation():
    bt = Backtester()
    df = bt.generate_benchmark_data(bars=300)
    assert len(df) == 300
    for col in ["open", "high", "low", "close", "volume"]:
        assert col in df.columns
    assert (df["high"] >= df["low"]).all()
