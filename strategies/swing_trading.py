"""
Swing Trading Strategy (H4-D1)

Longer-term trades capturing major moves over days.

Entry Logic:
- D1 trend established (EMA alignment)
- H4 pullback to 50 EMA
- Confluence with support/resistance levels
- RSI divergence or extreme readings
- News sentiment alignment

Exit Logic:
- SL: Below/above recent swing high/low (3x ATR minimum)
- TP: Key S/R levels or 3:1+ risk-reward
- Partial close at intermediate levels
"""

import pandas as pd
from loguru import logger

from analysis.technical import TechnicalAnalyzer
from config.settings import get_settings
from strategies.base_strategy import BaseStrategy, SignalDirection, TradingSignal


class SwingTradingStrategy(BaseStrategy):
    """
    Swing trading strategy for XAUUSD on H4-D1 timeframes.

    Captures large moves by entering on pullbacks within established trends,
    with confluence from support/resistance and higher conviction threshold.
    """

    def __init__(self):
        settings = get_settings()
        params = settings.swing_trading_params
        super().__init__(name="swing_trading", params=params)

        self.ema_fast = params.get("ema_fast", 20)
        self.ema_slow = params.get("ema_slow", 50)
        self.ema_trend = params.get("ema_trend", 200)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_overbought = params.get("rsi_overbought", 70)
        self.rsi_oversold = params.get("rsi_oversold", 30)
        self.atr_sl_multiplier = params.get("atr_sl_multiplier", 3.0)
        self.rr_ratio = params.get("risk_reward_ratio", 3.0)
        self.timeframes = params.get("timeframes", ["D1", "H4"])

    def analyze(self, df: pd.DataFrame) -> dict:
        """Analyze H4/D1 data for swing trading opportunities."""
        ta = TechnicalAnalyzer()

        ema_periods = [self.ema_fast, self.ema_slow, self.ema_trend]
        df = ta.add_ema(df, ema_periods)
        df = ta.add_rsi(df, self.rsi_period)
        df = ta.add_macd(df)
        df = ta.add_atr(df)
        df = ta.add_adx(df)
        df = ta.add_bollinger_bands(df)

        current_price = float(df["close"].iloc[-1])

        # EMA values
        ema_fast_val = float(df[f"ema_{self.ema_fast}"].iloc[-1]) if f"ema_{self.ema_fast}" in df.columns else current_price
        ema_slow_val = float(df[f"ema_{self.ema_slow}"].iloc[-1]) if f"ema_{self.ema_slow}" in df.columns else current_price
        ema_trend_val = float(df[f"ema_{self.ema_trend}"].iloc[-1]) if f"ema_{self.ema_trend}" in df.columns else current_price

        # Trend assessment
        bullish_trend = current_price > ema_trend_val and ema_fast_val > ema_slow_val
        bearish_trend = current_price < ema_trend_val and ema_fast_val < ema_slow_val

        # Pullback to slow EMA (key zone for swing entries)
        pullback_to_ema = abs(current_price - ema_slow_val) / current_price * 100
        is_pullback = pullback_to_ema < 0.3  # Within 0.3% of 50 EMA

        # Support / Resistance
        sr_levels = ta.find_support_resistance(df, lookback=200, num_levels=5)

        # Check if price is near a key S/R level
        near_support = False
        near_resistance = False
        nearest_support = 0.0
        nearest_resistance = 0.0

        if sr_levels["support"]:
            nearest_support = sr_levels["support"][0]
            near_support = abs(current_price - nearest_support) / current_price * 100 < 0.5

        if sr_levels["resistance"]:
            nearest_resistance = sr_levels["resistance"][0]
            near_resistance = abs(current_price - nearest_resistance) / current_price * 100 < 0.5

        # RSI
        rsi_signal = ta.get_rsi_signal(df, self.rsi_overbought, self.rsi_oversold)

        # MACD
        macd_cross = ta.detect_macd_crossover(df)

        # Higher timeframe trend confirmation (using EMA slope)
        ema_slope = (ema_slow_val - float(df[f"ema_{self.ema_slow}"].iloc[-5])) if f"ema_{self.ema_slow}" in df.columns else 0
        trend_strengthening = ema_slope > 0 if bullish_trend else ema_slope < 0

        # Candlestick patterns
        patterns = ta.detect_candlestick_patterns(df)

        # ATR
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else 5.0

        # ADX
        adx = float(df["adx"].iloc[-1]) if "adx" in df.columns and not pd.isna(df["adx"].iloc[-1]) else 0

        return {
            "current_price": current_price,
            "bullish_trend": bullish_trend,
            "bearish_trend": bearish_trend,
            "is_pullback": is_pullback,
            "pullback_distance_pct": pullback_to_ema,
            "near_support": near_support,
            "near_resistance": near_resistance,
            "nearest_support": nearest_support,
            "nearest_resistance": nearest_resistance,
            "support_resistance": sr_levels,
            "rsi": rsi_signal,
            "macd_crossover": macd_cross,
            "trend_strengthening": trend_strengthening,
            "candlestick_patterns": patterns,
            "atr": atr,
            "adx": adx,
        }

    def generate_signal(self, df: pd.DataFrame, analysis: dict) -> TradingSignal:
        """Generate swing trading signal from analysis."""
        score = 0
        reasons = []
        direction = SignalDirection.HOLD

        rsi = analysis["rsi"]
        macd = analysis["macd_crossover"]
        patterns = analysis["candlestick_patterns"]

        # ── BULLISH SWING ────────────────────────────────────────────────
        bullish_score = 0

        # 1. Established uptrend (+20)
        if analysis["bullish_trend"]:
            bullish_score += 20
            reasons.append("✅ Established bullish trend (price > 200 EMA, 20 > 50)")

        # 2. Pullback to 50 EMA (+20) — KEY entry criteria
        if analysis["is_pullback"] and analysis["bullish_trend"]:
            bullish_score += 20
            reasons.append(f"✅ Pullback to 50 EMA zone ({analysis['pullback_distance_pct']:.2f}%)")

        # 3. Price near support level (+15)
        if analysis["near_support"]:
            bullish_score += 15
            reasons.append(f"✅ Near support level @ {analysis['nearest_support']:.2f}")

        # 4. RSI divergence or recovering from oversold (+10-15)
        if rsi["divergence"] == "BULLISH":
            bullish_score += 15
            reasons.append("✅ Bullish RSI divergence — strong reversal signal")
        elif rsi["zone"] == "OVERSOLD":
            bullish_score += 10
            reasons.append(f"✅ RSI oversold ({rsi['value']:.1f}) — bounce expected")

        # 5. MACD turning bullish (+10)
        if macd["crossover"] == "BULLISH":
            bullish_score += 10
            reasons.append("✅ MACD bullish crossover")

        # 6. Trend strengthening (+5)
        if analysis["trend_strengthening"] and analysis["bullish_trend"]:
            bullish_score += 5
            reasons.append("✅ Trend momentum is strengthening")

        # 7. Candlestick confirmation (+5)
        bullish_candles = [p for p in patterns if p["direction"] == "BULLISH"]
        if bullish_candles:
            bullish_score += 5
            reasons.append(f"✅ {bullish_candles[0]['name']}")

        # ── BEARISH SWING ────────────────────────────────────────────────
        bearish_score = 0

        if analysis["bearish_trend"]:
            bearish_score += 20
            reasons.append("✅ Established bearish trend (price < 200 EMA, 20 < 50)")

        if analysis["is_pullback"] and analysis["bearish_trend"]:
            bearish_score += 20
            reasons.append(f"✅ Pullback to 50 EMA zone ({analysis['pullback_distance_pct']:.2f}%)")

        if analysis["near_resistance"]:
            bearish_score += 15
            reasons.append(f"✅ Near resistance level @ {analysis['nearest_resistance']:.2f}")

        if rsi["divergence"] == "BEARISH":
            bearish_score += 15
            reasons.append("✅ Bearish RSI divergence — strong reversal signal")
        elif rsi["zone"] == "OVERBOUGHT":
            bearish_score += 10
            reasons.append(f"✅ RSI overbought ({rsi['value']:.1f}) — pullback expected")

        if macd["crossover"] == "BEARISH":
            bearish_score += 10
            reasons.append("✅ MACD bearish crossover")

        if analysis["trend_strengthening"] and analysis["bearish_trend"]:
            bearish_score += 5
            reasons.append("✅ Bearish trend momentum strengthening")

        bearish_candles = [p for p in patterns if p["direction"] == "BEARISH"]
        if bearish_candles:
            bearish_score += 5
            reasons.append(f"✅ {bearish_candles[0]['name']}")

        # ── Determine Direction ──────────────────────────────────────────
        # Swing trading has higher threshold (75 default)
        if bullish_score > bearish_score and bullish_score >= self.min_confluence_score:
            direction = SignalDirection.BUY
            score = bullish_score
        elif bearish_score > bullish_score and bearish_score >= self.min_confluence_score:
            direction = SignalDirection.SELL
            score = bearish_score
        else:
            score = max(bullish_score, bearish_score)
            reasons.append(f"⏸ Score {score} below threshold {self.min_confluence_score}")

        entry_price = analysis["current_price"]
        sl, tp = self.get_sl_tp(df, direction, entry_price)
        rr = abs(tp - entry_price) / abs(sl - entry_price) if abs(sl - entry_price) > 0 else 0

        return TradingSignal(
            direction=direction,
            strategy=self.name,
            timeframe=self.timeframes[0],
            confidence=min(score, 100),
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            risk_reward_ratio=rr,
            technical_score=score,
            reasons=reasons,
            metadata=analysis,
        )

    def get_sl_tp(
        self,
        df: pd.DataFrame,
        direction: SignalDirection,
        entry_price: float,
    ) -> tuple[float, float]:
        """Calculate wider ATR-based SL/TP for swing trading."""
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else 5.0

        sl_distance = atr * self.atr_sl_multiplier
        tp_distance = sl_distance * self.rr_ratio

        if direction == SignalDirection.BUY:
            sl = round(entry_price - sl_distance, 2)
            tp = round(entry_price + tp_distance, 2)
        elif direction == SignalDirection.SELL:
            sl = round(entry_price + sl_distance, 2)
            tp = round(entry_price - tp_distance, 2)
        else:
            sl = 0.0
            tp = 0.0

        return sl, tp
