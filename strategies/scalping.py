"""
Scalping Strategy (M1-M5)

Fast-paced, short-term trades during high-volatility sessions.

Entry Logic:
- Price above/below 200 EMA (trend filter)
- Pullback to 30/60 EMA zone
- MACD crossover confirms momentum
- RSI crosses above/below 50 (momentum confirmation)
- Candlestick confirmation pattern

Exit Logic:
- SL: 1.5x ATR
- TP: 1.5:1 risk-reward ratio
- Active during: London + NY overlap (highest XAUUSD volatility)
"""

import pandas as pd
from loguru import logger

from analysis.technical import TechnicalAnalyzer
from config.settings import get_settings
from strategies.base_strategy import BaseStrategy, SignalDirection, TradingSignal


class ScalpingStrategy(BaseStrategy):
    """
    Scalping strategy for XAUUSD on M1-M5 timeframes.

    Uses triple confirmation: EMA trend + MACD momentum + RSI filter.
    """

    def __init__(self):
        settings = get_settings()
        params = settings.scalping_params
        super().__init__(name="scalping", params=params)

        self.ema_fast = params.get("ema_fast", 30)
        self.ema_slow = params.get("ema_slow", 60)
        self.ema_trend = params.get("ema_trend", 200)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_overbought = params.get("rsi_overbought", 70)
        self.rsi_oversold = params.get("rsi_oversold", 30)
        self.rsi_neutral = params.get("rsi_neutral", 50)
        self.atr_sl_multiplier = params.get("atr_sl_multiplier", 1.5)
        self.rr_ratio = params.get("risk_reward_ratio", 1.5)
        self.timeframes = params.get("timeframes", ["M5", "M1"])

    def analyze(self, df: pd.DataFrame) -> dict:
        """Analyze M5 data for scalping signals."""
        ta = TechnicalAnalyzer()

        # Ensure indicators are calculated
        ema_periods = [self.ema_fast, self.ema_slow, self.ema_trend]
        df = ta.add_ema(df, ema_periods)
        df = ta.add_rsi(df, self.rsi_period)
        df = ta.add_macd(df)
        df = ta.add_atr(df)

        # Get the latest values
        current_price = float(df["close"].iloc[-1])
        ema_trend_val = float(df[f"ema_{self.ema_trend}"].iloc[-1]) if f"ema_{self.ema_trend}" in df.columns else current_price
        ema_fast_val = float(df[f"ema_{self.ema_fast}"].iloc[-1]) if f"ema_{self.ema_fast}" in df.columns else current_price
        ema_slow_val = float(df[f"ema_{self.ema_slow}"].iloc[-1]) if f"ema_{self.ema_slow}" in df.columns else current_price

        # Trend direction from 200 EMA
        trend = "BULLISH" if current_price > ema_trend_val else "BEARISH"

        # Pullback detection: price near fast/slow EMA zone
        dist_fast = abs(current_price - ema_fast_val) / current_price * 100
        dist_slow = abs(current_price - ema_slow_val) / current_price * 100
        pullback_zone = min(dist_fast, dist_slow)
        pullback_limit = float(get_settings().scalping_params.get("pullback_tolerance_pct", 0.25))
        is_in_pullback = pullback_zone <= pullback_limit

        # EMA crossover
        ema_cross = ta.detect_ema_crossover(df, self.ema_fast, self.ema_slow)

        # MACD crossover
        macd_cross = ta.detect_macd_crossover(df)

        # RSI
        rsi_signal = ta.get_rsi_signal(df, self.rsi_overbought, self.rsi_oversold)

        # Candlestick patterns
        patterns = ta.detect_candlestick_patterns(df)

        # ATR for SL/TP
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else 1.0

        return {
            "current_price": current_price,
            "trend": trend,
            "is_in_pullback": is_in_pullback,
            "pullback_distance_pct": pullback_zone,
            "ema_crossover": ema_cross,
            "macd_crossover": macd_cross,
            "rsi": rsi_signal,
            "candlestick_patterns": patterns,
            "atr": atr,
            "ema_trend_value": ema_trend_val,
            "ema_fast_value": ema_fast_val,
            "ema_slow_value": ema_slow_val,
        }

    def generate_signal(self, df: pd.DataFrame, analysis: dict) -> TradingSignal:
        """Generate scalping signal from analysis."""
        score = 0
        reasons = []
        direction = SignalDirection.HOLD

        trend = analysis["trend"]
        rsi = analysis["rsi"]
        macd = analysis["macd_crossover"]
        ema = analysis["ema_crossover"]
        patterns = analysis["candlestick_patterns"]
        in_pullback = analysis["is_in_pullback"]

        # ── BULLISH SETUP ────────────────────────────────────────────────
        bullish_score = 0

        # 1. Trend filter: Price above 200 EMA (+15)
        if trend == "BULLISH":
            bullish_score += 15
            reasons.append("✅ Price above 200 EMA (bullish trend)")

        # 2. Pullback to EMA zone (+15)
        if in_pullback and trend == "BULLISH":
            bullish_score += 15
            reasons.append(f"✅ Pullback to EMA zone ({analysis['pullback_distance_pct']:.2f}%)")

        # 3. MACD bullish crossover (+20)
        if macd["crossover"] == "BULLISH":
            bullish_score += 20
            if macd["just_crossed"]:
                bullish_score += 5  # Bonus for fresh cross
                reasons.append("✅ MACD bullish crossover (FRESH)")
            else:
                reasons.append("✅ MACD bullish momentum")

        # 4. RSI above 50 (+15)
        if rsi["above_50"] and rsi["zone"] != "OVERBOUGHT":
            bullish_score += 15
            reasons.append(f"✅ RSI at {rsi['value']:.1f} (above 50, not overbought)")

        # 5. RSI divergence bonus (+10)
        if rsi["divergence"] == "BULLISH":
            bullish_score += 10
            reasons.append("✅ Bullish RSI divergence detected")

        # 6. Candlestick confirmation (+10)
        bullish_patterns = [p for p in patterns if p["direction"] == "BULLISH"]
        if bullish_patterns:
            bullish_score += 10
            reasons.append(f"✅ Bullish candle: {bullish_patterns[0]['name']}")

        # ── BEARISH SETUP ────────────────────────────────────────────────
        bearish_score = 0

        if trend == "BEARISH":
            bearish_score += 15
            reasons.append("✅ Price below 200 EMA (bearish trend)")

        if in_pullback and trend == "BEARISH":
            bearish_score += 15
            reasons.append(f"✅ Pullback to EMA zone ({analysis['pullback_distance_pct']:.2f}%)")

        if macd["crossover"] == "BEARISH":
            bearish_score += 20
            if macd["just_crossed"]:
                bearish_score += 5
                reasons.append("✅ MACD bearish crossover (FRESH)")
            else:
                reasons.append("✅ MACD bearish momentum")

        if not rsi["above_50"] and rsi["zone"] != "OVERSOLD":
            bearish_score += 15
            reasons.append(f"✅ RSI at {rsi['value']:.1f} (below 50, not oversold)")

        if rsi["divergence"] == "BEARISH":
            bearish_score += 10
            reasons.append("✅ Bearish RSI divergence detected")

        bearish_patterns = [p for p in patterns if p["direction"] == "BEARISH"]
        if bearish_patterns:
            bearish_score += 10
            reasons.append(f"✅ Bearish candle: {bearish_patterns[0]['name']}")

        # ── Determine Direction ──────────────────────────────────────────
        min_tech = self.min_technical_score
        if bullish_score > bearish_score and bullish_score >= min_tech:
            direction = SignalDirection.BUY
            score = bullish_score
        elif bearish_score > bullish_score and bearish_score >= min_tech:
            direction = SignalDirection.SELL
            score = bearish_score
        else:
            score = max(bullish_score, bearish_score)
            reasons.append(
                f"⏸ Technical score {score} below strategy setup threshold {min_tech}"
            )

        # Calculate SL/TP
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
        """Calculate ATR-based SL and TP for scalping."""
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else 1.0

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
