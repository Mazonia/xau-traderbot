"""
News Fetcher — Financial News Aggregation

Fetches real-time financial news from:
- Finnhub API (market news + company news)
- Alpha Vantage (news sentiment API)

Filters for Gold/XAUUSD-relevant keywords and caches results.
"""

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from loguru import logger

from config.settings import get_settings


class NewsFetcher:
    """
    Aggregates financial news from multiple APIs.

    Filters articles by gold/forex/macro keywords and de-duplicates.
    """

    def __init__(self):
        settings = get_settings()
        self.finnhub_key = settings.news.finnhub_api_key
        self.alpha_vantage_key = settings.news.alpha_vantage_api_key

        news_params = settings.news_params
        self.keywords = [kw.lower() for kw in news_params.get("keywords", ["gold", "XAUUSD"])]
        self.check_interval = news_params.get("check_interval_minutes", 5)

        # Cache to avoid duplicate processing
        self._seen_headlines: set[str] = set()
        self._last_fetch: Optional[datetime] = None

    def _headline_hash(self, headline: str) -> str:
        """Create a hash of a headline for deduplication."""
        return hashlib.md5(headline.lower().strip().encode()).hexdigest()

    def _is_relevant(self, headline: str, summary: str = "") -> bool:
        """Check if an article is relevant to XAUUSD trading."""
        text = (headline + " " + summary).lower()
        return any(kw in text for kw in self.keywords)

    async def fetch_finnhub_news(self, category: str = "general") -> list[dict]:
        """
        Fetch market news from Finnhub API.

        Args:
            category: "general", "forex", or "crypto"

        Returns:
            List of news article dicts.
        """
        if not self.finnhub_key:
            logger.warning("Finnhub API key not configured")
            return []

        url = "https://finnhub.io/api/v1/news"
        params = {
            "category": category,
            "token": self.finnhub_key,
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                articles = response.json()

            relevant = []
            for article in articles:
                headline = article.get("headline", "")
                summary = article.get("summary", "")

                # Skip if already seen
                h = self._headline_hash(headline)
                if h in self._seen_headlines:
                    continue

                # Filter for relevance
                if not self._is_relevant(headline, summary):
                    continue

                self._seen_headlines.add(h)
                relevant.append({
                    "source": "finnhub",
                    "headline": headline,
                    "summary": summary,
                    "url": article.get("url", ""),
                    "category": article.get("category", category),
                    "published_at": datetime.fromtimestamp(
                        article.get("datetime", 0), tz=timezone.utc
                    ),
                    "image": article.get("image", ""),
                    "source_name": article.get("source", ""),
                })

            logger.info(f"Finnhub: {len(relevant)} relevant articles from {len(articles)} total")
            return relevant

        except httpx.HTTPError as e:
            logger.error(f"Finnhub API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Finnhub fetch error: {e}")
            return []

    async def fetch_alpha_vantage_news(
        self,
        tickers: Optional[str] = None,
        topics: str = "economy_monetary,economy_fiscal,financial_markets",
    ) -> list[dict]:
        """
        Fetch news with sentiment from Alpha Vantage.

        Args:
            tickers: Comma-separated tickers (e.g., "FOREX:XAU")
            topics: Comma-separated topics

        Returns:
            List of news article dicts with pre-computed sentiment.
        """
        if not self.alpha_vantage_key:
            logger.warning("Alpha Vantage API key not configured")
            return []

        url = "https://www.alphavantage.co/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "topics": topics,
            "sort": "LATEST",
            "limit": "50",
            "apikey": self.alpha_vantage_key,
        }
        if tickers:
            params["tickers"] = tickers

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                data = response.json()

            feed = data.get("feed", [])
            relevant = []

            for article in feed:
                headline = article.get("title", "")
                summary = article.get("summary", "")

                h = self._headline_hash(headline)
                if h in self._seen_headlines:
                    continue

                if not self._is_relevant(headline, summary):
                    continue

                self._seen_headlines.add(h)

                # Alpha Vantage provides pre-computed sentiment
                overall_sentiment = article.get("overall_sentiment_score", 0)
                sentiment_label = article.get("overall_sentiment_label", "Neutral")

                # Parse published time
                time_str = article.get("time_published", "")
                try:
                    pub_time = datetime.strptime(time_str, "%Y%m%dT%H%M%S")
                    pub_time = pub_time.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    pub_time = datetime.now(timezone.utc)

                relevant.append({
                    "source": "alpha_vantage",
                    "headline": headline,
                    "summary": summary,
                    "url": article.get("url", ""),
                    "category": ",".join([t.get("topic", "") if isinstance(t, dict) else str(t) for t in article.get("topics", [])[:3]]),
                    "published_at": pub_time,
                    "av_sentiment_score": float(overall_sentiment),
                    "av_sentiment_label": sentiment_label,
                    "source_name": article.get("source", ""),
                })

            logger.info(f"Alpha Vantage: {len(relevant)} relevant articles from {len(feed)} total")
            return relevant

        except httpx.HTTPError as e:
            logger.error(f"Alpha Vantage API error: {e}")
            return []
        except Exception as e:
            logger.error(f"Alpha Vantage fetch error: {e}")
            return []

    async def fetch_all_news(self) -> list[dict]:
        """
        Fetch news from all configured sources.

        Returns:
            Combined list of relevant news articles, sorted by publish time.
        """
        all_articles = []

        # Fetch from both sources
        finnhub_articles = await self.fetch_finnhub_news("general")
        all_articles.extend(finnhub_articles)

        # Also fetch forex-specific news from Finnhub
        forex_articles = await self.fetch_finnhub_news("forex")
        all_articles.extend(forex_articles)

        av_articles = await self.fetch_alpha_vantage_news()
        all_articles.extend(av_articles)

        # Sort by publish time (newest first)
        all_articles.sort(
            key=lambda x: x.get("published_at", datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True,
        )

        self._last_fetch = datetime.now(timezone.utc)
        logger.info(f"📰 Total relevant news articles fetched: {len(all_articles)}")
        return all_articles

    def should_fetch(self) -> bool:
        """Check if enough time has passed since last fetch."""
        if self._last_fetch is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self._last_fetch).total_seconds() / 60
        return elapsed >= self.check_interval

    def clear_cache(self):
        """Clear the seen headlines cache."""
        self._seen_headlines.clear()
        logger.debug("News cache cleared")
