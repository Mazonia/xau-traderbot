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
        self._finbert_checked = False
        self._gemini_client = None
        self._gemini_cooldown_until = 0.0

    def _get_finbert(self):
        """Lazy-load the FinBERT sentiment pipeline."""
        if self._finbert_pipeline is not None:
            return self._finbert_pipeline
        if self._finbert_checked:
            return None

        self._finbert_checked = True
        try:
            from transformers import pipeline

            self._finbert_pipeline = pipeline(
                "sentiment-analysis",
                model="ProsusAI/finbert",
                return_all_scores=True,
            )
            logger.info("FinBERT model loaded successfully")
            return self._finbert_pipeline
        except ImportError:
            logger.info("FinBERT (transformers) not installed — using built-in financial lexicon analyzer")
            return None
        except Exception as e:
            logger.warning(f"Could not load FinBERT: {e} — using financial lexicon fallback")
            return None

    def _get_gemini(self):
        """Lazy-load the Gemini client."""
        if self._gemini_client is None:
            try:
                from google import genai
                try:
                    from google.genai import models
                    models.Models._logged_afc_warning = True
                except Exception:
                    pass

                self._gemini_client = genai.Client(
                    api_key=self.settings.gemini.api_key
                )
                logger.info("Gemini client initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Gemini: {e}")
                return None
        return self._gemini_client

    def _analyze_with_lexicon(self, text: str) -> dict:
        """
        Fast, robust domain-specific financial sentiment analysis for Gold (XAUUSD).
        Used when FinBERT is not installed or as a fallback.
        """
        t = text.lower()
        
        # Bullish factors for Gold (Rate cuts, inflation, safe haven, dollar weakness, turmoil)
        bullish_keywords = [
            "rate cut", "cut rate", "cuts rate", "cutting rate", "fed cut", "dovish", "easing",
            "inflation", "cpi", "safe haven", "safe-haven", "gold surge", "gold rally", "gold climb", "gold jump",
            "gold advance", "gold gain", "weak dollar", "dollar slide", "dollar fall", "dollar drop", "dollar sink",
            "dollar weak", "dollar soft", "war", "conflict", "geopolitical", "crisis", "tension", "escalat", "strike", "attack",
            "recession", "slowdown", "debt", "deficit", "bank failure", "tariff", "trade war",
            "stimulus", "liquidity", "central bank", "reserve"
        ]
        
        # Bearish factors for Gold (Rate hikes, hawkish, strong dollar, peace, high yields)
        bearish_keywords = [
            "rate hike", "hike rate", "hikes rate", "hiking rate", "fed hike", "hawkish", "tighten", "higher for longer",
            "disinflation", "strong dollar", "dollar surge", "dollar rally", "dollar jump", "dollar gain", "dollar strong",
            "gold drop", "gold fall", "gold tumble", "gold slide", "gold retreat", "gold sink",
            "ceasefire", "peace", "de-escalat", "diplomacy", "strong job", "nfp beat", "robust job",
            "yield surge", "yields rise", "yields jump"
        ]
        
        bull_matches = [kw for kw in bullish_keywords if kw in t]
        bear_matches = [kw for kw in bearish_keywords if kw in t]
        
        bull_score = len(bull_matches)
        bear_score = len(bear_matches)
        
        total = bull_score + bear_score
        if total == 0:
            return {"sentiment": "NEUTRAL", "score": 0.0, "confidence": 0.4, "factors": []}
            
        raw_score = (bull_score - bear_score) / max(1, total)
        clamped_score = max(-1.0, min(1.0, raw_score * 0.75))
        
        if clamped_score > 0.15:
            sentiment = "BULLISH"
        elif clamped_score < -0.15:
            sentiment = "BEARISH"
        else:
            sentiment = "NEUTRAL"
            
        return {
            "sentiment": sentiment,
            "score": round(clamped_score, 2),
            "confidence": min(0.9, 0.45 + (0.1 * total)),
            "factors": bull_matches + bear_matches
        }

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
            return self._analyze_with_lexicon(text)

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

    def _fallback_lexicon_analysis(self, headline: str, summary: str = "", reason: str = "") -> dict:
        """Domain financial lexicon sentiment fallback for Gold."""
        lex = self._analyze_with_lexicon(f"{headline}. {summary}")
        factors = lex.get("factors", [])
        abs_score = abs(lex["score"])
        # High impact requires strong conviction and multiple macro factors
        is_high = abs_score >= 0.7 and len(factors) >= 2
        is_med = abs_score >= 0.3 or len(factors) >= 1
        impact = "HIGH" if is_high else ("MEDIUM" if is_med else "LOW")
        direction = "UP" if lex["score"] > 0.15 else ("DOWN" if lex["score"] < -0.15 else "FLAT")
        analysis_desc = f"Macro Sentiment: {lex['sentiment']} (Score: {lex['score']:+.2f})"
        if reason:
            analysis_desc += f" [{reason}]"
        return {
            "sentiment": lex["sentiment"],
            "score": lex["score"],
            "impact_level": impact,
            "expected_direction": direction,
            "time_horizon": "SHORT",
            "is_risk_off": lex["score"] > 0,
            "key_factors": factors,
            "analysis": analysis_desc,
        }

    async def analyze_with_gemini(self, headline: str, summary: str = "") -> dict:
        """
        Deep analysis using Gemini API.

        Asks Gemini to analyze the news impact on XAUUSD.

        Returns:
            Dict with 'sentiment', 'score', 'impact_level',
            'expected_direction', 'time_horizon', 'analysis'.
        """
        import time

        now = time.time()
        if now < self._gemini_cooldown_until:
            return self._fallback_lexicon_analysis(headline, summary, reason="Gemini Cooldown")

        client = self._get_gemini()
        if client is None:
            return self._fallback_lexicon_analysis(headline, summary, reason="Gemini Unavailable")

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
            import asyncio

            def _call_gemini_sync():
                return client.models.generate_content(
                    model=self.settings.gemini.model,
                    contents=prompt,
                    config={
                        "temperature": self.settings.gemini.temperature,
                        "max_output_tokens": self.settings.gemini.max_tokens,
                    },
                )

            # Non-blocking async execution with 12s timeout
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(_call_gemini_sync),
                    timeout=12.0
                )
                text = response.text.strip()
            except asyncio.TimeoutError:
                raise TimeoutError("Gemini API call timed out after 12s")

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
            logger.warning(f"Gemini returned invalid JSON, using lexicon fallback: {e}")
            return self._fallback_lexicon_analysis(headline, summary, reason="Parse Fallback")
        except Exception as e:
            err_msg = str(e)
            if self.settings.gemini.api_key:
                err_msg = err_msg.replace(self.settings.gemini.api_key, "***GEMINI_KEY***")

            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg or "quota" in err_msg.lower():
                import time
                self._gemini_cooldown_until = time.time() + 60.0
                logger.info("Gemini API rate limit reached — temporarily switching to financial lexicon analyzer (60s cooldown)")
            else:
                logger.warning(f"Gemini analysis fallback (temporary issue: {err_msg[:90]}...)")

            return self._fallback_lexicon_analysis(headline, summary, reason="Lexicon Fallback")

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
