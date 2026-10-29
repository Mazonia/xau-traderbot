"""
Signal Aggregator — Confluence Scoring Engine (v2 — Oct 2026)

Combines signals from:
- Technical analysis strategies (40% weight, adaptive)
- AI price prediction (25% weight, adaptive)
- News sentiment analysis (20% weight, adaptive)
- Market regime alignment (15% weight, SCALED not binary)
- Temporal self-attention structural alignment (bonus modifier)
- Volume confirmation bonus

Only signals above the minimum confluence threshold are executed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from config.settings import get_settings
from strategies.base_strategy import SignalDirection, TradingSignal


@dataclass
class ConfluenceResult:
    """Result of the confluence scoring process."""

    direction: SignalDirection
    total_score: float
    technical_score: float = 0.0
    ai_score: float = 0.0
    sentiment_score: float = 0.0
    regime_score: float = 0.0
    strategy_name: str = ""
    should_execute: bool = False
    reasons: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SignalAggregator:
    """
    Aggregates multiple signal sources into a single confluence score.

    The confluence score determines whether a trade should be executed.
    """

    def __init__(self):
        settings = get_settings()
        weights = settings.confluence_weights

        self.technical_weight = weights.get("technical_weight", 40)
        self.ai_weight = weights.get("ai_prediction_weight", 25)
        self.sentiment_weight = weights.get("sentiment_weight", 20)
        self.regime_weight = weights.get("regime_weight", 15)

        # Normalize weights to 100
        total = self.technical_weight + self.ai_weight + self.sentiment_weight + self.regime_weight
        if total != 100:
            factor = 100 / total
            self.technical_weight *= factor
            self.ai_weight *= factor
            self.sentiment_weight *= factor
            self.regime_weight *= factor

    def calculate_confluence(
        self,
        strategy_signal: TradingSignal,
        ai_prediction: Optional[dict] = None,
        sentiment: Optional[dict] = None,
        regime_analysis: Optional[dict] = None,
        attention_analysis: Optional[dict] = None,
        min_score: float = 65.0,
    ) -> ConfluenceResult:
        """
        Calculate the confluence score from all signal sources.

        Args:
            strategy_signal: Signal from the active strategy.
            ai_prediction: Dict with 'direction' (BUY/SELL/HOLD) and 'confidence' (0-1).
            sentiment: Dict with 'direction' (BULLISH/BEARISH/NEUTRAL) and 'score' (-1 to 1).
            regime_analysis: Dict with 'is_recommended' (bool) and 'position_modifier' (float).
            min_score: Minimum confluence score to execute.

        Returns:
            ConfluenceResult with final score and execution decision.
        """
        # Dynamically synchronize with self-learning adaptive weights
        try:
            from ai.trade_learner import trade_learner
            cw = trade_learner.get_confluence_weights()
            self.technical_weight = cw.get("technical", self.technical_weight)
            self.ai_weight = cw.get("ai_prediction", self.ai_weight)
            self.sentiment_weight = cw.get("sentiment", self.sentiment_weight)
            self.regime_weight = cw.get("regime", self.regime_weight)
        except Exception:
            pass
        reasons = list(strategy_signal.reasons)

        # ── 1. Technical Score (from strategy) ───────────────────────────
        # Strategy confidence is already 0-100, normalize to weight
        raw_technical = strategy_signal.confidence
        technical_contrib = (raw_technical / 100) * self.technical_weight
        reasons.append(f"📊 Technical: {raw_technical:.0f}/100 → {technical_contrib:.1f} pts")

        # ── 2. AI Prediction Score ───────────────────────────────────────
        ai_contrib = 0.0
        if ai_prediction:
            ai_direction = ai_prediction.get("direction", "HOLD")
            ai_confidence = ai_prediction.get("confidence", 0.0)

            # Score based on alignment with strategy signal
            if strategy_signal.direction == SignalDirection.BUY and ai_direction == "BUY":
                ai_contrib = ai_confidence * self.ai_weight
                reasons.append(f"🤖 AI: BULLISH (conf={ai_confidence:.0%}) → +{ai_contrib:.1f} pts")
            elif strategy_signal.direction == SignalDirection.SELL and ai_direction == "SELL":
                ai_contrib = ai_confidence * self.ai_weight
                reasons.append(f"🤖 AI: BEARISH (conf={ai_confidence:.0%}) → +{ai_contrib:.1f} pts")
            elif ai_direction == "HOLD":
                ai_contrib = 0.0  # Indecision/Neutral gives 0 bonus points (no free points)
                reasons.append("🤖 AI: NEUTRAL (HOLD) → +0.0 pts (no directional edge)")
            else:
                # AI disagrees with strategy — penalize proportionally to AI confidence
                penalty_factor = max(0.4, ai_confidence)
                ai_contrib = -self.ai_weight * penalty_factor
                reasons.append(f"🤖 AI: OPPOSING signal ({ai_direction} {ai_confidence:.0%}) → {ai_contrib:.1f} pts (penalized)")
        else:
            ai_contrib = 0.0
            reasons.append("🤖 AI: unavailable → +0.0 pts")

        # ── 3. News Sentiment Score ──────────────────────────────────────
        sentiment_contrib = 0.0
        if sentiment:
            sent_direction = sentiment.get("direction", "NEUTRAL")
            sent_score = sentiment.get("score", 0.0)  # -1 to 1

            if strategy_signal.direction == SignalDirection.BUY and sent_direction == "BULLISH":
                sentiment_contrib = abs(sent_score) * self.sentiment_weight
                reasons.append(f"📰 Sentiment: BULLISH ({sent_score:+.2f}) → +{sentiment_contrib:.1f} pts")
            elif strategy_signal.direction == SignalDirection.SELL and sent_direction == "BEARISH":
                sentiment_contrib = abs(sent_score) * self.sentiment_weight
                reasons.append(f"📰 Sentiment: BEARISH ({sent_score:+.2f}) → +{sentiment_contrib:.1f} pts")
            elif sent_direction == "NEUTRAL":
                sentiment_contrib = 0.0  # Neutral news gives 0 bonus
                reasons.append("📰 Sentiment: NEUTRAL → +0.0 pts")
            else:
                # Sentiment opposes strategy
                sentiment_contrib = -self.sentiment_weight * max(0.3, abs(sent_score))
                reasons.append(f"📰 Sentiment: OPPOSING ({sent_score:+.2f}) → {sentiment_contrib:.1f} pts")
        else:
            sentiment_contrib = 0.0
            reasons.append("📰 Sentiment: unavailable → +0.0 pts")

        # ── 4. Regime Alignment Score (SCALED, not binary) ───────────────
        regime_contrib = 0.0
        is_counter_trend = False
        if regime_analysis:
            is_recommended = regime_analysis.get("is_recommended", True)
            trend_dir = regime_analysis.get("trend_direction", "NEUTRAL")
            regime_name = regime_analysis.get("regime", "")
            adx_val = float(regime_analysis.get("adx", 15.0))

            if regime_name == "RANGING":
                is_counter_trend = False
                trend_dir = "NEUTRAL"
            elif (trend_dir == "UP" and strategy_signal.direction == SignalDirection.SELL) or \
               (trend_dir == "DOWN" and strategy_signal.direction == SignalDirection.BUY):
                is_counter_trend = True

            if is_recommended and not is_counter_trend:
                # SCALED regime contribution: stronger ADX = more conviction points
                # ADX 25-40: moderate trend → 60-80% of regime weight
                # ADX 40+: strong trend → 80-100% of regime weight
                # ADX < 25: ranging → 40-60% of regime weight (less confident)
                if adx_val >= 40:
                    regime_scale = min(1.0, 0.8 + (adx_val - 40) / 100)
                elif adx_val >= 25:
                    regime_scale = 0.6 + (adx_val - 25) / 37.5  # 0.6 to ~1.0
                else:
                    regime_scale = max(0.3, 0.4 + adx_val / 62.5)  # 0.4 to ~0.8

                regime_contrib = self.regime_weight * regime_scale
                reasons.append(
                    f"🌊 Regime: ALIGNED ({regime_name}, ADX={adx_val:.0f}) → "
                    f"+{regime_contrib:.1f} pts ({regime_scale:.0%} scale)"
                )
            elif is_counter_trend:
                # Counter-trend gets full negative penalty
                regime_contrib = -self.regime_weight
                reasons.append(
                    f"🌊 Regime: COUNTER-TREND ({regime_name} {trend_dir} vs "
                    f"{strategy_signal.direction.value}) → {regime_contrib:.1f} pts"
                )
            else:
                # Not recommended but not counter-trend — partial penalty
                regime_contrib = -self.regime_weight * 0.5
                reasons.append(
                    f"🌊 Regime: NOT RECOMMENDED ({regime_name}) → {regime_contrib:.1f} pts"
                )
        else:
            regime_contrib = 0.0
            reasons.append("🌊 Regime: unavailable → +0.0 pts")

        # ── 5. Temporal Self-Attention Alignment (Book Ch. 5) ─────────────
        attention_contrib = 0.0
        if attention_analysis:
            att_conc = attention_analysis.get("concentration", 0.0)
            att_bonus = attention_analysis.get("bonus_pts", 0.0)
            anchor_type = attention_analysis.get("anchor_type", "")
            if abs(att_bonus) > 0.05:
                attention_contrib = att_bonus
                emoji = "🟢" if att_bonus > 0 else "🔴"
                reasons.append(f"🧠 Attention: {att_conc:.0f}% focus on {anchor_type} → {emoji} {attention_contrib:+.1f} pts")

        # ── 6. Volume Confirmation Bonus ─────────────────────────────────
        volume_bonus = 0.0
        if hasattr(strategy_signal, 'metadata') and strategy_signal.metadata:
            vol_intensity = strategy_signal.metadata.get("volume_intensity", 1.0)
            if vol_intensity is not None and vol_intensity > 1.5:
                # Above-average volume confirms the move — small bonus
                volume_bonus = min(3.0, (vol_intensity - 1.0) * 2.0)
                reasons.append(f"📊 Volume: {vol_intensity:.1f}x avg → +{volume_bonus:.1f} pts")
            elif vol_intensity is not None and vol_intensity < 0.5:
                # Very low volume — signal is suspect
                volume_bonus = -2.0
                reasons.append(f"📊 Volume: LOW ({vol_intensity:.1f}x avg) → {volume_bonus:.1f} pts")

        # ── Dynamic Regime & Volatility Threshold (Book Ch. 6 & 7) ───────
        effective_min_score = min_score
        # Proportional threshold scaling if feeds are neutral or unavailable
        if sentiment is None or sentiment.get("direction") == "NEUTRAL":
            effective_min_score = effective_min_score * ((100.0 - (self.sentiment_weight * 0.5)) / 100.0)

        # Scale threshold when AI model is in HOLD (neutral conviction)
        # Prevents locking out valid high-conviction technical setups
        if ai_prediction is None or ai_prediction.get("direction") == "HOLD":
            effective_min_score = effective_min_score * ((100.0 - (self.ai_weight * 0.5)) / 100.0)

        if regime_analysis:
            regime_name = regime_analysis.get("regime", "")
            vol_level = regime_analysis.get("volatility", "")
            if "TREND" in regime_name:
                effective_min_score -= 2.0
                reasons.append(f"🎯 Dynamic Threshold: -2.0 pts for TRENDING momentum (Target: {effective_min_score:.1f})")
            elif regime_name == "RANGING":
                effective_min_score += 3.0
                reasons.append(f"🎯 Dynamic Threshold: +3.0 pts for RANGING chop filter (Target: {effective_min_score:.1f})")

            if vol_level == "HIGH":
                effective_min_score += 5.0
                reasons.append(f"🎯 Dynamic Threshold: +5.0 pts for HIGH VOLATILITY shield (Target: {effective_min_score:.1f})")

        # ── Final Score ──────────────────────────────────────────────────
        total_score = max(0.0, min(100.0,
            technical_contrib + ai_contrib + sentiment_contrib + regime_contrib + attention_contrib + volume_bonus
        ))
        allow_counter = regime_analysis.get("allow_counter_trend", False) if regime_analysis else False

        should_execute = (
            total_score >= effective_min_score
            and strategy_signal.direction != SignalDirection.HOLD
            and (allow_counter or not is_counter_trend)
        )

        if not should_execute and is_counter_trend and not allow_counter:
            reasons.append(f"🚫 VETOED: Counter-trend entries prohibited in {trend_dir} market")
        elif should_execute:
            reasons.append(
                f"✅ CONFLUENCE MET: {total_score:.1f}/{effective_min_score:.1f} — EXECUTE"
            )
        else:
            reasons.append(
                f"❌ CONFLUENCE NOT MET: {total_score:.1f}/{effective_min_score:.1f} — HOLD"
            )

        logger.info(
            f"Confluence: {total_score:.1f}/100 | "
            f"Tech={technical_contrib:.1f} AI={ai_contrib:.1f} "
            f"Sent={sentiment_contrib:.1f} Regime={regime_contrib:.1f} "
            f"Att={attention_contrib:+.1f} Vol={volume_bonus:+.1f} | Target={effective_min_score:.1f} | "
            f"Execute={should_execute}"
        )

        return ConfluenceResult(
            direction=strategy_signal.direction,
            total_score=total_score,
            technical_score=technical_contrib,
            ai_score=ai_contrib,
            sentiment_score=sentiment_contrib,
            regime_score=regime_contrib,
            strategy_name=strategy_signal.strategy,
            should_execute=should_execute,
            reasons=reasons,
        )
