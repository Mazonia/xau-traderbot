"""
News Analyzer — FinBERT + Gemini Sentiment Analysis

Two-tier analysis:
1. FinBERT: Fast, local sentiment scoring (bullish/bearish/neutral)
2. Gemini API: Deep analysis — impact prediction, risk assessment
"""

import json
from typing import Optional

from loguru import logger

from config.settings import get_settings


class NewsAnalyzer:
    """
    Analyzes financial news using FinBERT for fast sentiment
    and Gemini API for deeper market impact analysis.
    """

    def __init__(self):
        self.settings = get_settings()
        self._finbert_pipeline = None
        self._gemini_client = None

    def _get_finbert(self):
        """Lazy-load the FinBERT sentiment pipeline."""
        if self._finbert_pipeline is None:
            try:
                from transformers import pipeline

                self._finbert_pipeline = pipeline(
                    "sentiment-analysis",
                    model="ProsusAI/finbert",
                    return_all_scores=True,
                )
                logger.info("FinBERT model loaded successfully")
            except Exception as e:
                logger.error(f"Failed to load FinBERT: {e}")
                return None
        return self._finbert_pipeline

    def _get_gemini(self):
        """Lazy-load the Gemini client."""
        if self._gemini_client is None:
            try:
                from google import genai

                self._gemini_client = genai.Client(
                    api_key=self.settings.gemini.api_key
                )
                logger.info("Gemini client initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Gemini: {e}")
                return None
        return self._gemini_client

    def analyze_with_finbert(self, text: str) -> dict:
        """
        Quick sentiment scoring using FinBERT.

        Args:
            text: News headline or summary.

        Returns:
            Dict with 'sentiment' (BULLISH/BEARISH/NEUTRAL),
            'score' (-1 to 1), and 'confidence' (0 to 1).
        """
        pipeline = self._get_finbert()
        if pipeline is None:
            return {"sentiment": "NEUTRAL", "score": 0.0, "confidence": 0.0}

        try:
            # Truncate to FinBERT max length
            text = text[:512]
            results = pipeline(text)

            if not results or not results[0]:
                return {"sentiment": "NEUTRAL", "score": 0.0, "confidence": 0.0}

            scores = {r["label"]: r["score"] for r in results[0]}
            positive = scores.get("positive", 0)
            negative = scores.get("negative", 0)
            neutral = scores.get("neutral", 0)

            # Determine sentiment
            if positive > negative and positive > neutral:
                sentiment = "BULLISH"
                score = positive
                confidence = positive
            elif negative > positive and negative > neutral:
                sentiment = "BEARISH"
                score = -negative
                confidence = negative
            else:
                sentiment = "NEUTRAL"
                score = 0.0
                confidence = neutral

            return {
                "sentiment": sentiment,
                "score": score,
                "confidence": confidence,
                "raw_scores": scores,
            }

        except Exception as e:
            logger.error(f"FinBERT analysis error: {e}")
            return {"sentiment": "NEUTRAL", "score": 0.0, "confidence": 0.0}

    async def analyze_with_gemini(self, headline: str, summary: str = "") -> dict:
        """
        Deep analysis using Gemini API.

        Asks Gemini to analyze the news impact on XAUUSD.

        Returns:
            Dict with 'sentiment', 'score', 'impact_level',
            'expected_direction', 'time_horizon', 'analysis'.
        """
        client = self._get_gemini()
        if client is None:
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "impact_level": "LOW",
                "expected_direction": "NEUTRAL",
                "analysis": "Gemini unavailable",
            }

        prompt = f"""You are an expert Gold (XAUUSD) market analyst. Analyze this news article and determine its potential impact on the XAUUSD price.

HEADLINE: {headline}
SUMMARY: {summary}

Respond in JSON format ONLY (no markdown, no code blocks):
{{
    "sentiment": "BULLISH" or "BEARISH" or "NEUTRAL",
    "score": float from -1.0 (very bearish for gold) to 1.0 (very bullish for gold),
    "impact_level": "HIGH" or "MEDIUM" or "LOW",
    "expected_direction": "UP" or "DOWN" or "FLAT",
    "time_horizon": "SHORT" (hours) or "MEDIUM" (days) or "LONG" (weeks),
    "is_risk_off": true or false (risk-off events typically boost gold),
    "key_factors": ["factor1", "factor2"],
    "analysis": "Brief 1-2 sentence explanation of impact on XAUUSD"
}}

Important context:
- Gold rises on: inflation fears, rate cut expectations, geopolitical risk, weak USD, risk-off sentiment
- Gold falls on: rate hike expectations, strong USD, risk-on sentiment, low inflation
"""

        try:
            response = client.models.generate_content(
                model=self.settings.gemini.model,
                contents=prompt,
                config={
                    "temperature": self.settings.gemini.temperature,
                    "max_output_tokens": self.settings.gemini.max_tokens,
                },
            )

            text = response.text.strip()

            # Robust JSON extraction from potential markdown or introductory text
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                result = json.loads(json_match.group(0))
            else:
                result = json.loads(text)

            # Strict validation and boundary clamping for AI-derived fields
            try:
                score = float(result.get("score", 0.0))
            except (ValueError, TypeError):
                score = 0.0
            score = max(-1.0, min(1.0, score))

            sentiment = str(result.get("sentiment", "NEUTRAL")).strip().upper()
            if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
                sentiment = "NEUTRAL"

            impact = str(result.get("impact_level", "LOW")).strip().upper()
            if impact not in ("HIGH", "MEDIUM", "LOW"):
                impact = "LOW"

            direction = str(result.get("expected_direction", "FLAT")).strip().upper()
            if direction not in ("UP", "DOWN", "FLAT"):
                direction = "FLAT"

            result["score"] = score
            result["sentiment"] = sentiment
            result["impact_level"] = impact
            result["expected_direction"] = direction

            logger.info(
                f"Gemini analysis: {sentiment} "
                f"(score={score:.2f}, impact={impact})"
            )
            return result

        except json.JSONDecodeError as e:
            logger.error(f"Gemini returned invalid JSON: {e}")
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "impact_level": "LOW",
                "analysis": "Failed to parse Gemini response",
            }
        except Exception as e:
            err_msg = str(e)
            if self.settings.gemini.api_key:
                err_msg = err_msg.replace(self.settings.gemini.api_key, "***GEMINI_KEY***")
            logger.error(f"Gemini analysis error: {err_msg}")
            return {
                "sentiment": "NEUTRAL",
                "score": 0.0,
                "impact_level": "LOW",
                "analysis": f"Error: {str(e)}",
            }

    async def analyze_article(self, article: dict) -> dict:
        """
        Full two-tier analysis of a news article.

        1. Quick FinBERT sentiment
        2. Deep Gemini analysis (if article seems important)
        """
        headline = article.get("headline", "")
        summary = article.get("summary", "")

        # Tier 1: FinBERT (fast baseline)
        finbert_result = self.analyze_with_finbert(headline + ". " + summary)

        # Tier 2: Gemini (deep financial macro reasoning)
        gemini_result = None
        if self.settings.gemini.api_key:
            gemini_result = await self.analyze_with_gemini(headline, summary)
        elif finbert_result["confidence"] > 0.5 and finbert_result["sentiment"] != "NEUTRAL":
            gemini_result = await self.analyze_with_gemini(headline, summary)
        else:
            gemini_result = {
                "sentiment": finbert_result["sentiment"],
                "score": finbert_result["score"],
                "impact_level": "LOW",
                "analysis": "Gemini API key not configured",
            }

        # Combine scores (weighted average: 40% FinBERT, 60% Gemini)
        finbert_score = finbert_result["score"]
        gemini_score = gemini_result.get("score", 0)

        if gemini_result.get("impact_level") != "LOW":
            combined_score = finbert_score * 0.4 + gemini_score * 0.6
        else:
            combined_score = finbert_score

        # Determine final sentiment
        if combined_score > 0.15:
            final_sentiment = "BULLISH"
        elif combined_score < -0.15:
            final_sentiment = "BEARISH"
        else:
            final_sentiment = "NEUTRAL"

        return {
            "headline": headline,
            "sentiment": final_sentiment,
            "combined_score": combined_score,
            "finbert": finbert_result,
            "gemini": gemini_result,
            "impact_level": gemini_result.get("impact_level", "LOW"),
        }
