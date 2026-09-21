"""
Unit tests for Technical Indicators and Feature Engineering.
"""

import numpy as np
import pandas as pd
import pytest

from analysis.technical import TechnicalAnalyzer


@pytest.fixture
def sample_ohlcv_data():
    """Generate 300 bars of synthetic OHLCV data."""
    np.random.seed(42)
    n = 300
    prices = [2600.0]
    for _ in range(n - 1):
        ret = np.random.normal(0.0002, 0.003)
        prices.append(prices[-1] * (1 + ret))

    opens, highs, lows, closes, volumes = [], [], [], [], []
    for p in prices:
        spread = np.random.uniform(1.0, 5.0)
        open_p = p + np.random.uniform(-1.0, 1.0)
        high = max(open_p, p) + spread
        low = min(open_p, p) - spread
        opens.append(open_p)
        highs.append(high)
        lows.append(low)
        closes.append(p)
        volumes.append(int(np.random.uniform(500, 2000)))

    return pd.DataFrame({
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def test_rsi_calculation(sample_ohlcv_data):
    ta = TechnicalAnalyzer()
    df = ta.add_rsi(sample_ohlcv_data.copy(), period=14)
    assert "rsi" in df.columns
    valid_rsi = df["rsi"].dropna()
    assert len(valid_rsi) > 0
    assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()


def test_macd_calculation(sample_ohlcv_data):
    ta = TechnicalAnalyzer()
    df = ta.add_macd(sample_ohlcv_data.copy(), fast=12, slow=26, signal=9)
    assert "macd" in df.columns
    assert "macd_signal" in df.columns
    assert "macd_histogram" in df.columns
    assert not df["macd"].iloc[-1] != df["macd"].iloc[-1]  # not NaN


def test_bollinger_bands(sample_ohlcv_data):
    ta = TechnicalAnalyzer()
    df = ta.add_bollinger_bands(sample_ohlcv_data.copy(), period=20, std=2.0)
    assert "bb_upper" in df.columns
    assert "bb_mid" in df.columns
    assert "bb_lower" in df.columns
    # Upper band must be greater than lower band
    last_row = df.iloc[-1]
    assert last_row["bb_upper"] >= last_row["bb_lower"]


def test_atr_calculation(sample_ohlcv_data):
    ta = TechnicalAnalyzer()
    df = ta.add_atr(sample_ohlcv_data.copy(), period=14)
    assert "atr" in df.columns
    valid_atr = df["atr"].dropna()
    assert (valid_atr > 0).all()


def test_add_all_indicators(sample_ohlcv_data):
    ta = TechnicalAnalyzer()
    df = ta.add_all_indicators(sample_ohlcv_data.copy())
    expected_cols = ["rsi", "macd", "atr", "ema_200", "bb_upper"]
    for col in expected_cols:
        assert col in df.columns
