"""
Day Trading Strategy (M15-H1)

Medium-term intraday trades using multi-timeframe EMA alignment,
MACD momentum, RSI divergence, and Bollinger Band positioning.

Entry Logic:
- Multi-TF EMA alignment (H1 trend + M15 entry)
- MACD histogram growing in trend direction
- RSI between 40-60 (not overextended) or divergence present
- Price near Bollinger Band edge for mean-reversion entries

Exit Logic:
- SL: 2x ATR on H1
- TP: 2:1 risk-reward ratio
- Active during: London + New York sessions
"""

import pandas as pd
from loguru import logger

from analysis.technical import TechnicalAnalyzer
from config.settings import get_settings
from strategies.base_strategy import BaseStrategy, SignalDirection, TradingSignal


class DayTradingStrategy(BaseStrategy):
    """
    Day trading strategy for XAUUSD on M15-H1 timeframes.

    Combines trend-following with momentum and mean-reversion elements.
    """

    def __init__(self):
        settings = get_settings()
        params = settings.day_trading_params
        super().__init__(name="day_trading", params=params)

        self.ema_fast = params.get("ema_fast", 20)
        self.ema_slow = params.get("ema_slow", 50)
        self.ema_trend = params.get("ema_trend", 200)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_overbought = params.get("rsi_overbought", 70)
        self.rsi_oversold = params.get("rsi_oversold", 30)
        self.bb_period = params.get("bollinger_period", 20)
        self.bb_std = params.get("bollinger_std", 2)
        self.atr_sl_multiplier = params.get("atr_sl_multiplier", 2.0)
        self.rr_ratio = params.get("risk_reward_ratio", 2.0)
        self.timeframes = params.get("timeframes", ["H1", "M15"])

    def analyze(self, df: pd.DataFrame) -> dict:
        """Analyze H1 data for day trading signals."""
        ta = TechnicalAnalyzer()

        # Calculate indicators
        ema_periods = [self.ema_fast, self.ema_slow, self.ema_trend]
        df = ta.add_ema(df, ema_periods)
        df = ta.add_rsi(df, self.rsi_period)
        df = ta.add_macd(df)
        df = ta.add_atr(df)
        df = ta.add_bollinger_bands(df, self.bb_period, self.bb_std)
        df = ta.add_adx(df)

        current_price = float(df["close"].iloc[-1])

        # EMA alignment check
        ema_fast_val = float(df[f"ema_{self.ema_fast}"].iloc[-1]) if f"ema_{self.ema_fast}" in df.columns else current_price
        ema_slow_val = float(df[f"ema_{self.ema_slow}"].iloc[-1]) if f"ema_{self.ema_slow}" in df.columns else current_price
        ema_trend_val = float(df[f"ema_{self.ema_trend}"].iloc[-1]) if f"ema_{self.ema_trend}" in df.columns else current_price

        # Full EMA alignment: fast > slow > trend (bullish) or fast < slow < trend (bearish)
        bullish_alignment = ema_fast_val > ema_slow_val > ema_trend_val
        bearish_alignment = ema_fast_val < ema_slow_val < ema_trend_val

        # MACD histogram momentum
        macd_hist = float(df["macd_histogram"].iloc[-1]) if "macd_histogram" in df.columns else 0
        prev_macd_hist = float(df["macd_histogram"].iloc[-2]) if "macd_histogram" in df.columns else 0
        macd_growing = abs(macd_hist) > abs(prev_macd_hist) and (
            (macd_hist > 0 and prev_macd_hist > 0) or (macd_hist < 0 and prev_macd_hist < 0)
        )

        # Bollinger Band position
        bb_pctb = float(df["bb_pctb"].iloc[-1]) if "bb_pctb" in df.columns and not pd.isna(df["bb_pctb"].iloc[-1]) else 0.5

        # RSI analysis
        rsi_signal = ta.get_rsi_signal(df, self.rsi_overbought, self.rsi_oversold)

        # MACD crossover
        macd_cross = ta.detect_macd_crossover(df)

        # Candlestick patterns
        patterns = ta.detect_candlestick_patterns(df)

        # ATR
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else 2.0

        # ADX
        adx = float(df["adx"].iloc[-1]) if "adx" in df.columns and not pd.isna(df["adx"].iloc[-1]) else 0

        # Support/Resistance
        sr_levels = ta.find_support_resistance(df)

        return {
            "current_price": current_price,
            "bullish_ema_alignment": bullish_alignment,
            "bearish_ema_alignment": bearish_alignment,
            "macd_histogram": macd_hist,
            "macd_growing": macd_growing,
            "macd_crossover": macd_cross,
            "rsi": rsi_signal,
            "bb_pctb": bb_pctb,
            "candlestick_patterns": patterns,
            "atr": atr,
            "adx": adx,
            "support_resistance": sr_levels,
        }

    def generate_signal(self, df: pd.DataFrame, analysis: dict) -> TradingSignal:
        """Generate day trading signal from analysis."""
        score = 0
        reasons = []
        direction = SignalDirection.HOLD

        rsi = analysis["rsi"]
        macd = analysis["macd_crossover"]
        patterns = analysis["candlestick_patterns"]
        bb_pctb = analysis["bb_pctb"]

        # ── BULLISH SETUP ────────────────────────────────────────────────
        bullish_score = 0

        # 1. Full EMA alignment (+20)
        if analysis["bullish_ema_alignment"]:
            bullish_score += 20
            reasons.append("✅ Full bullish EMA alignment (20 > 50 > 200)")

        # 2. MACD bullish + growing histogram (+20)
        if macd["crossover"] == "BULLISH":
            bullish_score += 15
            reasons.append("✅ MACD bullish")
        if analysis["macd_growing"] and analysis["macd_histogram"] > 0:
            bullish_score += 5
            reasons.append("✅ MACD histogram growing (strengthening momentum)")

        # 3. RSI in favorable zone (+15)
        if 40 <= rsi["value"] <= 65:
            bullish_score += 15
            reasons.append(f"✅ RSI at {rsi['value']:.1f} (favorable zone)")
        elif rsi["divergence"] == "BULLISH":
            bullish_score += 20
            reasons.append("✅ Bullish RSI divergence — high conviction")

        # 4. Bollinger Band position: price near lower band = buy opportunity (+10)
        if bb_pctb < 0.3:
            bullish_score += 10
            reasons.append(f"✅ Price near lower Bollinger Band (%B={bb_pctb:.2f})")

        # 5. ADX confirms trend strength (+10)
        if analysis["adx"] > 25:
            bullish_score += 10
            reasons.append(f"✅ ADX {analysis['adx']:.1f} confirms trend strength")

        # 6. Candlestick confirmation (+5)
        bullish_patterns = [p for p in patterns if p["direction"] == "BULLISH"]
        if bullish_patterns:
            bullish_score += 5
            reasons.append(f"✅ {bullish_patterns[0]['name']}")

        # ── BEARISH SETUP ────────────────────────────────────────────────
        bearish_score = 0

        if analysis["bearish_ema_alignment"]:
            bearish_score += 20
            reasons.append("✅ Full bearish EMA alignment (20 < 50 < 200)")

        if macd["crossover"] == "BEARISH":
            bearish_score += 15
            reasons.append("✅ MACD bearish")
        if analysis["macd_growing"] and analysis["macd_histogram"] < 0:
            bearish_score += 5
            reasons.append("✅ MACD histogram growing bearish")

        if 35 <= rsi["value"] <= 60:
            bearish_score += 15
            reasons.append(f"✅ RSI at {rsi['value']:.1f} (favorable for short)")
        elif rsi["divergence"] == "BEARISH":
            bearish_score += 20
            reasons.append("✅ Bearish RSI divergence — high conviction")

        if bb_pctb > 0.7:
            bearish_score += 10
            reasons.append(f"✅ Price near upper Bollinger Band (%B={bb_pctb:.2f})")

        if analysis["adx"] > 25:
            bearish_score += 10
            reasons.append(f"✅ ADX {analysis['adx']:.1f} confirms trend")

        bearish_patterns = [p for p in patterns if p["direction"] == "BEARISH"]
        if bearish_patterns:
            bearish_score += 5
            reasons.append(f"✅ {bearish_patterns[0]['name']}")

        # ── Determine Direction ──────────────────────────────────────────
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
        """Calculate ATR-based SL and TP for day trading."""
        atr = float(df["atr"].iloc[-1]) if "atr" in df.columns and not pd.isna(df["atr"].iloc[-1]) else 2.0

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
