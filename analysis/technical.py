"""
Technical Analysis Module

Calculates all technical indicators used by the trading strategies:
- RSI, EMA, MACD, ATR, Bollinger Bands, ADX
- Multi-timeframe analysis
- Support/resistance detection
- Candlestick pattern recognition

All indicators are computed using pure numpy/pandas — no external TA library needed.
"""

import numpy as np
import pandas as pd
from loguru import logger


class TechnicalAnalyzer:
    """
    Computes technical indicators on OHLCV DataFrames.

    All methods accept a pandas DataFrame with columns:
    open, high, low, close, volume
    and return the DataFrame with new indicator columns appended.
    """

    # ── Core Indicators ──────────────────────────────────────────────────

    @staticmethod
    def add_ema(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        """Add Exponential Moving Averages."""
        periods = periods or [20, 30, 50, 60, 200]
        for period in periods:
            col_name = f"ema_{period}"
            df[col_name] = df["close"].ewm(span=period, adjust=False).mean()
        return df

    @staticmethod
    def add_sma(df: pd.DataFrame, periods: list[int] | None = None) -> pd.DataFrame:
        """Add Simple Moving Averages."""
        periods = periods or [20, 50, 200]
        for period in periods:
            col_name = f"sma_{period}"
            df[col_name] = df["close"].rolling(window=period).mean()
        return df

    @staticmethod
    def add_rsi(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add Relative Strength Index (Wilder's smoothing)."""
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)

        # Wilder's smoothing (exponential moving average)
        avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

        rs = avg_gain / avg_loss.replace(0, np.nan)
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    @staticmethod
    def add_macd(
        df: pd.DataFrame,
        fast: int = 12,
        slow: int = 26,
        signal: int = 9,
    ) -> pd.DataFrame:
        """Add MACD (Moving Average Convergence Divergence)."""
        ema_fast = df["close"].ewm(span=fast, adjust=False).mean()
        ema_slow = df["close"].ewm(span=slow, adjust=False).mean()

        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=signal, adjust=False).mean()
        df["macd_histogram"] = df["macd"] - df["macd_signal"]
        return df

    @staticmethod
    def add_atr(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add Average True Range (volatility measure)."""
        high = df["high"]
        low = df["low"]
        close_prev = df["close"].shift(1)

        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()

        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df["atr"] = true_range.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
        return df

    @staticmethod
    def add_bollinger_bands(
        df: pd.DataFrame,
        period: int = 20,
        std: float = 2.0,
    ) -> pd.DataFrame:
        """Add Bollinger Bands."""
        df["bb_mid"] = df["close"].rolling(window=period).mean()
        rolling_std = df["close"].rolling(window=period).std()

        df["bb_upper"] = df["bb_mid"] + (rolling_std * std)
        df["bb_lower"] = df["bb_mid"] - (rolling_std * std)
        df["bb_bandwidth"] = (df["bb_upper"] - df["bb_lower"]) / df["bb_mid"]

        # %B — position within the bands (0 = lower, 1 = upper)
        bb_range = df["bb_upper"] - df["bb_lower"]
        df["bb_pctb"] = (df["close"] - df["bb_lower"]) / bb_range.replace(0, np.nan)
        return df

    @staticmethod
    def add_adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
        """Add Average Directional Index (trend strength)."""
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # +DM and -DM
        plus_dm = high.diff()
        minus_dm = -low.diff()

        plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
        minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

        # True Range
        close_prev = close.shift(1)
        tr1 = high - low
        tr2 = (high - close_prev).abs()
        tr3 = (low - close_prev).abs()
        true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

        # Smoothed TR, +DM, -DM (Wilder's smoothing)
        alpha = 1 / period
        atr_smooth = true_range.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        plus_dm_smooth = plus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        minus_dm_smooth = minus_dm.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

        # +DI and -DI
        df["di_plus"] = 100 * (plus_dm_smooth / atr_smooth.replace(0, np.nan))
        df["di_minus"] = 100 * (minus_dm_smooth / atr_smooth.replace(0, np.nan))

        # DX and ADX
        di_sum = df["di_plus"] + df["di_minus"]
        dx = 100 * ((df["di_plus"] - df["di_minus"]).abs() / di_sum.replace(0, np.nan))
        df["adx"] = dx.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
        return df

    @staticmethod
    def add_stochastic(
        df: pd.DataFrame,
        k_period: int = 14,
        d_period: int = 3,
    ) -> pd.DataFrame:
        """Add Stochastic Oscillator."""
        lowest_low = df["low"].rolling(window=k_period).min()
        highest_high = df["high"].rolling(window=k_period).max()

        denom = (highest_high - lowest_low).replace(0, np.nan)
        df["stoch_k"] = 100 * (df["close"] - lowest_low) / denom
        df["stoch_d"] = df["stoch_k"].rolling(window=d_period).mean()
        return df

    @staticmethod
    def add_vwap(df: pd.DataFrame) -> pd.DataFrame:
        """Add Volume Weighted Average Price."""
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        cum_tp_vol = (typical_price * df["volume"]).cumsum()
        cum_vol = df["volume"].cumsum()
        df["vwap"] = cum_tp_vol / cum_vol.replace(0, np.nan)
        return df

    # ── Composite Analysis ───────────────────────────────────────────────

    @classmethod
    def add_all_indicators(
        cls,
        df: pd.DataFrame,
        ema_periods: list[int] | None = None,
        rsi_period: int = 14,
        macd_fast: int = 12,
        macd_slow: int = 26,
        macd_signal: int = 9,
        atr_period: int = 14,
        bb_period: int = 20,
        bb_std: float = 2.0,
        adx_period: int = 14,
    ) -> pd.DataFrame:
        """Add all technical indicators to a DataFrame."""
        df = cls.add_ema(df, ema_periods)
        df = cls.add_rsi(df, rsi_period)
        df = cls.add_macd(df, macd_fast, macd_slow, macd_signal)
        df = cls.add_atr(df, atr_period)
        df = cls.add_bollinger_bands(df, bb_period, bb_std)
        df = cls.add_adx(df, adx_period)
        df = cls.add_stochastic(df)
        return df

    # ── Signal Detection ─────────────────────────────────────────────────

    @staticmethod
    def detect_ema_crossover(df: pd.DataFrame, fast: int = 30, slow: int = 60) -> dict:
        """
        Detect EMA crossover events.

        Returns:
            dict with 'crossover' (BULLISH/BEARISH/NONE), 'just_crossed' (bool)
        """
        fast_col = f"ema_{fast}"
        slow_col = f"ema_{slow}"

        if fast_col not in df.columns or slow_col not in df.columns:
            return {"crossover": "NONE", "just_crossed": False}

        current_fast = df[fast_col].iloc[-1]
        current_slow = df[slow_col].iloc[-1]
        prev_fast = df[fast_col].iloc[-2]
        prev_slow = df[slow_col].iloc[-2]

        # Check if any are NaN
        if any(pd.isna([current_fast, current_slow, prev_fast, prev_slow])):
            return {"crossover": "NONE", "just_crossed": False}

        # Current state
        if current_fast > current_slow:
            crossover = "BULLISH"
        elif current_fast < current_slow:
            crossover = "BEARISH"
        else:
            crossover = "NONE"

        # Did it just cross?
        just_crossed = (prev_fast <= prev_slow and current_fast > current_slow) or (
            prev_fast >= prev_slow and current_fast < current_slow
        )

        return {"crossover": crossover, "just_crossed": just_crossed}

    @staticmethod
    def detect_macd_crossover(df: pd.DataFrame) -> dict:
        """Detect MACD line crossing the signal line."""
        if "macd" not in df.columns or "macd_signal" not in df.columns:
            return {"crossover": "NONE", "just_crossed": False}

        current_macd = df["macd"].iloc[-1]
        current_signal = df["macd_signal"].iloc[-1]
        prev_macd = df["macd"].iloc[-2]
        prev_signal = df["macd_signal"].iloc[-2]

        if any(pd.isna([current_macd, current_signal, prev_macd, prev_signal])):
            return {"crossover": "NONE", "just_crossed": False}

        if current_macd > current_signal:
            crossover = "BULLISH"
        elif current_macd < current_signal:
            crossover = "BEARISH"
        else:
            crossover = "NONE"

        just_crossed = (prev_macd <= prev_signal and current_macd > current_signal) or (
            prev_macd >= prev_signal and current_macd < current_signal
        )

        return {"crossover": crossover, "just_crossed": just_crossed}

    @staticmethod
    def get_rsi_signal(df: pd.DataFrame, overbought: int = 70, oversold: int = 30) -> dict:
        """
        Analyze RSI for trading signals.

        Returns:
            dict with 'value', 'zone' (OVERBOUGHT/OVERSOLD/NEUTRAL),
            'above_50' (bool), 'divergence' (BULLISH/BEARISH/NONE)
        """
        if "rsi" not in df.columns:
            return {"value": 50, "zone": "NEUTRAL", "above_50": True, "divergence": "NONE"}

        rsi = df["rsi"].iloc[-1]

        if pd.isna(rsi):
            return {"value": 50, "zone": "NEUTRAL", "above_50": True, "divergence": "NONE"}

        if rsi >= overbought:
            zone = "OVERBOUGHT"
        elif rsi <= oversold:
            zone = "OVERSOLD"
        else:
            zone = "NEUTRAL"

        # Simple RSI divergence detection (last 20 candles)
        divergence = "NONE"
        lookback = min(20, len(df) - 1)
        if lookback > 5:
            price_slice = df["close"].iloc[-lookback:]
            rsi_slice = df["rsi"].iloc[-lookback:]

            if not rsi_slice.isna().all():
                # Bullish divergence: price making lower lows, RSI making higher lows
                if (
                    price_slice.iloc[-1] < price_slice.iloc[0]
                    and rsi_slice.iloc[-1] > rsi_slice.iloc[0]
                ):
                    divergence = "BULLISH"
                elif (
                    price_slice.iloc[-1] > price_slice.iloc[0]
                    and rsi_slice.iloc[-1] < rsi_slice.iloc[0]
                ):
                    divergence = "BEARISH"

        return {
            "value": float(rsi),
            "zone": zone,
            "above_50": rsi > 50,
            "divergence": divergence,
        }

    @staticmethod
    def get_trend_direction(df: pd.DataFrame, ema_period: int = 200) -> dict:
        """
        Determine overall trend direction using EMA.

        Returns:
            dict with 'direction' (BULLISH/BEARISH/NEUTRAL), 'strength' (float 0-1)
        """
        ema_col = f"ema_{ema_period}"
        if ema_col not in df.columns:
            return {"direction": "NEUTRAL", "strength": 0.0}

        current_price = df["close"].iloc[-1]
        ema_value = df[ema_col].iloc[-1]

        if pd.isna(ema_value):
            return {"direction": "NEUTRAL", "strength": 0.0}

        # Distance from EMA as percentage
        distance_pct = (current_price - ema_value) / ema_value * 100

        if distance_pct > 0.1:
            direction = "BULLISH"
        elif distance_pct < -0.1:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Strength based on distance
        strength = min(abs(distance_pct) / 2.0, 1.0)

        return {"direction": direction, "strength": strength}

    # ── Support / Resistance ─────────────────────────────────────────────

    @staticmethod
    def find_support_resistance(
        df: pd.DataFrame,
        lookback: int = 100,
        num_levels: int = 5,
    ) -> dict:
        """
        Find key support and resistance levels using swing highs/lows.

        Returns:
            dict with 'support' (list of prices), 'resistance' (list of prices)
        """
        if len(df) < lookback:
            lookback = len(df)

        highs = df["high"].iloc[-lookback:]
        lows = df["low"].iloc[-lookback:]
        current_price = df["close"].iloc[-1]

        # Find swing highs and lows (local extremes)
        swing_highs = []
        swing_lows = []

        for i in range(2, len(highs) - 2):
            # Swing high: higher than 2 candles on each side
            if (
                highs.iloc[i] > highs.iloc[i - 1]
                and highs.iloc[i] > highs.iloc[i - 2]
                and highs.iloc[i] > highs.iloc[i + 1]
                and highs.iloc[i] > highs.iloc[i + 2]
            ):
                swing_highs.append(float(highs.iloc[i]))

            # Swing low: lower than 2 candles on each side
            if (
                lows.iloc[i] < lows.iloc[i - 1]
                and lows.iloc[i] < lows.iloc[i - 2]
                and lows.iloc[i] < lows.iloc[i + 1]
                and lows.iloc[i] < lows.iloc[i + 2]
            ):
                swing_lows.append(float(lows.iloc[i]))

        # Cluster nearby levels (within 0.2% of each other)
        def cluster_levels(levels: list[float], threshold_pct: float = 0.2) -> list[float]:
            if not levels:
                return []
            sorted_levels = sorted(levels)
            clusters = [[sorted_levels[0]]]
            for level in sorted_levels[1:]:
                if abs(level - clusters[-1][-1]) / clusters[-1][-1] * 100 < threshold_pct:
                    clusters[-1].append(level)
                else:
                    clusters.append([level])
            # Return the average of each cluster
            return [round(sum(c) / len(c), 2) for c in clusters]

        # Split into support (below price) and resistance (above price)
        all_levels = cluster_levels(swing_highs + swing_lows)
        support = sorted([l for l in all_levels if l < current_price], reverse=True)[:num_levels]
        resistance = sorted([l for l in all_levels if l > current_price])[:num_levels]

        return {"support": support, "resistance": resistance}

    # ── Candlestick Patterns ─────────────────────────────────────────────

    @staticmethod
    def detect_candlestick_patterns(df: pd.DataFrame) -> list[dict]:
        """
        Detect common candlestick patterns on the latest candles.

        Returns:
            List of detected patterns with name and signal direction.
        """
        patterns = []

        if len(df) < 3:
            return patterns

        # Latest 3 candles
        c0 = {
            "open": df["open"].iloc[-1],
            "high": df["high"].iloc[-1],
            "low": df["low"].iloc[-1],
            "close": df["close"].iloc[-1],
        }
        c1 = {
            "open": df["open"].iloc[-2],
            "high": df["high"].iloc[-2],
            "low": df["low"].iloc[-2],
            "close": df["close"].iloc[-2],
        }

        body0 = abs(c0["close"] - c0["open"])
        body1 = abs(c1["close"] - c1["open"])
        range0 = c0["high"] - c0["low"]
        range1 = c1["high"] - c1["low"]

        if range0 == 0:
            range0 = 0.001  # Avoid division by zero

        # ── Bullish Engulfing ──
        if (
            c1["close"] < c1["open"]  # Previous bearish
            and c0["close"] > c0["open"]  # Current bullish
            and c0["open"] <= c1["close"]
            and c0["close"] >= c1["open"]
        ):
            patterns.append({"name": "BULLISH_ENGULFING", "direction": "BULLISH", "strength": 0.8})

        # ── Bearish Engulfing ──
        if (
            c1["close"] > c1["open"]  # Previous bullish
            and c0["close"] < c0["open"]  # Current bearish
            and c0["open"] >= c1["close"]
            and c0["close"] <= c1["open"]
        ):
            patterns.append({"name": "BEARISH_ENGULFING", "direction": "BEARISH", "strength": 0.8})

        # ── Hammer (bullish reversal) ──
        upper_wick = c0["high"] - max(c0["open"], c0["close"])
        lower_wick = min(c0["open"], c0["close"]) - c0["low"]

        if (
            lower_wick > body0 * 2
            and upper_wick < body0 * 0.5
            and body0 > 0
        ):
            patterns.append({"name": "HAMMER", "direction": "BULLISH", "strength": 0.7})

        # ── Shooting Star (bearish reversal) ──
        if (
            upper_wick > body0 * 2
            and lower_wick < body0 * 0.5
            and body0 > 0
        ):
            patterns.append({"name": "SHOOTING_STAR", "direction": "BEARISH", "strength": 0.7})

        # ── Doji (indecision) ──
        if body0 < range0 * 0.1 and range0 > 0:
            patterns.append({"name": "DOJI", "direction": "NEUTRAL", "strength": 0.5})

        return patterns

    # ── Feature Engineering for ML ───────────────────────────────────────

    @classmethod
    def create_ml_features(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create a comprehensive feature set for ML models.
        Adds all indicators + derived features.
        """
        # Add all base indicators
        df = cls.add_all_indicators(df)

        # Price-based features
        df["returns"] = df["close"].pct_change()
        df["log_returns"] = np.log(df["close"] / df["close"].shift(1))
        df["high_low_range"] = (df["high"] - df["low"]) / df["close"]
        df["close_open_range"] = (df["close"] - df["open"]) / df["open"]

        # Lagged features
        for lag in [1, 2, 3, 5, 10]:
            df[f"returns_lag_{lag}"] = df["returns"].shift(lag)
            df[f"close_lag_{lag}"] = df["close"].shift(lag)

        # Rolling statistics
        for window in [5, 10, 20]:
            df[f"volatility_{window}"] = df["returns"].rolling(window).std()
            df[f"avg_volume_{window}"] = df["volume"].rolling(window).mean()
            df[f"momentum_{window}"] = df["close"] / df["close"].shift(window) - 1

        # EMA relationship features
        if "ema_50" in df.columns and "ema_200" in df.columns:
            df["ema_50_200_diff"] = (df["ema_50"] - df["ema_200"]) / df["ema_200"]

        if "ema_20" in df.columns:
            df["price_to_ema20"] = (df["close"] - df["ema_20"]) / df["ema_20"]

        # Bollinger Band position
        if "bb_upper" in df.columns and "bb_lower" in df.columns:
            bb_range = df["bb_upper"] - df["bb_lower"]
            df["bb_position"] = (df["close"] - df["bb_lower"]) / bb_range.replace(0, np.nan)

        return df
