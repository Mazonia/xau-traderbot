"""
Signal Aggregator — Confluence Scoring Engine

Combines signals from:
- Technical analysis strategies (40% weight)
- AI price prediction (25% weight)
- News sentiment analysis (20% weight)
- Market regime alignment (15% weight)

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
                ai_contrib = self.ai_weight * 0.3  # Neutral contribution
                reasons.append(f"🤖 AI: NEUTRAL → +{ai_contrib:.1f} pts (neutral)")
            else:
                # AI disagrees with strategy — penalize
                ai_contrib = -self.ai_weight * 0.3
                reasons.append(f"🤖 AI: OPPOSING signal → {ai_contrib:.1f} pts (penalized)")
        else:
            # No AI available — use partial weight as neutral
            ai_contrib = self.ai_weight * 0.4
            reasons.append(f"🤖 AI: unavailable → +{ai_contrib:.1f} pts (default)")

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
                sentiment_contrib = self.sentiment_weight * 0.3
                reasons.append(f"📰 Sentiment: NEUTRAL → +{sentiment_contrib:.1f} pts")
            else:
                # Sentiment opposes strategy
                sentiment_contrib = -self.sentiment_weight * 0.2
                reasons.append(f"📰 Sentiment: OPPOSING ({sent_score:+.2f}) → {sentiment_contrib:.1f} pts")
        else:
            sentiment_contrib = self.sentiment_weight * 0.3
            reasons.append(f"📰 Sentiment: unavailable → +{sentiment_contrib:.1f} pts (default)")

        # ── 4. Regime Alignment Score ────────────────────────────────────
        regime_contrib = 0.0
        if regime_analysis:
            is_recommended = regime_analysis.get("is_recommended", True)
            if is_recommended:
                regime_contrib = self.regime_weight
                reasons.append(f"🌊 Regime: ALIGNED → +{regime_contrib:.1f} pts")
            else:
                regime_contrib = -self.regime_weight * 0.5
                reasons.append(f"🌊 Regime: MISALIGNED → {regime_contrib:.1f} pts")
        else:
            regime_contrib = self.regime_weight * 0.5
            reasons.append(f"🌊 Regime: unavailable → +{regime_contrib:.1f} pts (default)")

        # ── Final Score ──────────────────────────────────────────────────
        total_score = max(0, technical_contrib + ai_contrib + sentiment_contrib + regime_contrib)
        should_execute = (
            total_score >= min_score
            and strategy_signal.direction != SignalDirection.HOLD
        )

        if should_execute:
            reasons.append(
                f"✅ CONFLUENCE MET: {total_score:.1f}/{min_score:.0f} — EXECUTE"
            )
        else:
            reasons.append(
                f"❌ CONFLUENCE NOT MET: {total_score:.1f}/{min_score:.0f} — HOLD"
            )

        logger.info(
            f"Confluence: {total_score:.1f}/100 | "
            f"Tech={technical_contrib:.1f} AI={ai_contrib:.1f} "
            f"Sent={sentiment_contrib:.1f} Regime={regime_contrib:.1f} | "
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
