"""
Sentiment Module — Unified Sentiment Signal

Combines FinBERT + Gemini scores into a single sentiment signal
with time-decay weighting (recent news matters more).
"""

import math
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from config.settings import get_settings
from database import crud


class SentimentAggregator:
    """
    Aggregates multiple news sentiment scores into a single
    unified signal for the trading strategy engine.
    """

    def __init__(self):
        settings = get_settings()
        news_params = settings.news_params
        self.decay_hours = news_params.get("sentiment_decay_hours", 6)
        self._recent_sentiments: list[dict] = []

    def add_sentiment(
        self,
        score: float,
        impact_level: str = "LOW",
        published_at: Optional[datetime] = None,
    ):
        """
        Add a sentiment data point.

        Args:
            score: -1.0 (bearish) to 1.0 (bullish)
            impact_level: LOW, MEDIUM, HIGH
            published_at: When the news was published
        """
        if published_at is None:
            published_at = datetime.now(timezone.utc)

        # Impact weight multiplier
        impact_weights = {"LOW": 0.5, "MEDIUM": 1.0, "HIGH": 2.0}
        weight = impact_weights.get(impact_level, 0.5)

        self._recent_sentiments.append({
            "score": score,
            "weight": weight,
            "impact_level": impact_level,
            "published_at": published_at,
        })

        # Keep only last 100 data points
        if len(self._recent_sentiments) > 100:
            self._recent_sentiments = self._recent_sentiments[-100:]

    def get_signal(self) -> dict:
        """
        Calculate the unified sentiment signal with time decay.

        Returns:
            Dict with:
                direction: BULLISH, BEARISH, or NEUTRAL
                score: -1.0 to 1.0
                confidence: 0.0 to 1.0
                data_points: number of articles considered
                has_high_impact: whether any HIGH impact news is active
        """
        if not self._recent_sentiments:
            return {
                "direction": "NEUTRAL",
                "score": 0.0,
                "confidence": 0.0,
                "data_points": 0,
                "has_high_impact": False,
            }

        now = datetime.now(timezone.utc)
        weighted_sum = 0.0
        total_weight = 0.0
        has_high_impact = False

        for item in self._recent_sentiments:
            # Time decay: exponential decay based on hours since publication
            hours_old = (now - item["published_at"]).total_seconds() / 3600
            decay = math.exp(-hours_old / self.decay_hours)

            # Combined weight = impact_weight * time_decay
            effective_weight = item["weight"] * decay
            weighted_sum += item["score"] * effective_weight
            total_weight += effective_weight

            # Check for recent high-impact news
            if item["impact_level"] == "HIGH" and hours_old < self.decay_hours:
                has_high_impact = True

        # Calculate weighted average
        if total_weight > 0:
            avg_score = weighted_sum / total_weight
        else:
            avg_score = 0.0

        # Confidence based on number of data points and agreement
        data_points = len(self._recent_sentiments)
        confidence = min(data_points / 10, 1.0)  # Max confidence with 10+ articles

        # Direction
        if avg_score > 0.15:
            direction = "BULLISH"
        elif avg_score < -0.15:
            direction = "BEARISH"
        else:
            direction = "NEUTRAL"

        # Also check from database
        db_sentiment = crud.get_recent_sentiment(hours=self.decay_hours)
        if db_sentiment != 0.0:
            # Blend with DB sentiment
            avg_score = avg_score * 0.7 + db_sentiment * 0.3

        return {
            "direction": direction,
            "score": round(avg_score, 4),
            "confidence": round(confidence, 2),
            "data_points": data_points,
            "has_high_impact": has_high_impact,
        }

    def clear(self):
        """Clear all stored sentiments."""
        self._recent_sentiments.clear()
