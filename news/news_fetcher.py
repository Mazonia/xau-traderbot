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
import re

def _sanitize_log(msg: str) -> str:
    """Mask API tokens from URLs and error tracebacks."""
    return re.sub(r'([?&](?:token|apikey|api_key)=)[^&\s]+', r'\1***REDACTED***', str(msg))

from loguru import logger

from config.settings import get_settings
from news.news_utils import compute_news_hash, is_headline_relevant, normalize_headline


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

        # Cache to avoid duplicate processing (persisted from DB across restarts)
        self._seen_hashes: set[str] = set()
        self._seen_headlines = self._seen_hashes  # Alias for backward compatibility
        self._last_fetch: Optional[datetime] = None
        self._alpha_vantage_cooldown_until: Optional[datetime] = None

        self._load_seen_from_db()

    def _load_seen_from_db(self):
        """Preload recent news hashes from database so restarts never re-process news."""
        try:
            from database.models import get_session, NewsEvent
            session = get_session()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                events = session.query(NewsEvent.headline, NewsEvent.url).filter(
                    NewsEvent.fetched_at >= cutoff
                ).all()
                for h_text, u_text in events:
                    if h_text:
                        self._seen_hashes.add(compute_news_hash(h_text, u_text or ""))
                    if u_text:
                        self._seen_hashes.add(hashlib.sha256(u_text.strip().lower().encode("utf-8")).hexdigest())
                logger.info(f"📰 Preloaded {len(self._seen_hashes)} seen news hashes from database.")
            finally:
                session.close()
        except Exception as e:
            logger.debug(f"Could not preload seen news from DB: {e}")

    def _headline_hash(self, headline: str, url: str = "") -> str:
        """Create a hash of a headline for deduplication."""
        return compute_news_hash(headline, url)

    def _is_relevant(self, headline: str, summary: str = "") -> bool:
        """Check if an article is relevant to XAUUSD trading using regex word boundaries."""
        return is_headline_relevant(headline, summary, self.keywords)

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
        params = {"category": category}
        headers = {"X-Finnhub-Token": self.finnhub_key}

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                articles = response.json()

            relevant = []
            for article in articles:
                headline = article.get("headline", "")
                summary = article.get("summary", "")
                art_url = article.get("url", "")

                # Skip if already seen
                h = compute_news_hash(headline, art_url)
                if h in self._seen_hashes:
                    continue

                # Filter for relevance
                if not self._is_relevant(headline, summary):
                    continue

                self._seen_hashes.add(h)
                relevant.append({
                    "source": "finnhub",
                    "headline": headline,
                    "summary": summary,
                    "url": art_url,
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
            logger.error(_sanitize_log(f"Finnhub API error: {e}"))
            return []
        except Exception as e:
            logger.error(_sanitize_log(f"Finnhub fetch error: {e}"))
            return []

    async def fetch_alpha_vantage_news(
        self,
        topics: str = "economy_macro,monetary_policy",
        tickers: str = "FOREX:XAU",
    ) -> list[dict]:
        """
        Fetch news sentiment from Alpha Vantage.

        Args:
            topics: Comma-separated topics
            tickers: Comma-separated tickers

        Returns:
            List of news articles with pre-computed sentiment.
        """
        if not self.alpha_vantage_key:
            logger.warning("Alpha Vantage API key not configured")
            return []

        if self._alpha_vantage_cooldown_until and datetime.now(timezone.utc) < self._alpha_vantage_cooldown_until:
            wait_m = max(1, int((self._alpha_vantage_cooldown_until - datetime.now(timezone.utc)).total_seconds() / 60))
            logger.debug(f"Alpha Vantage in cooldown, skipping fetch (resumes in {wait_m}m)")
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
            if "Note" in data:
                logger.warning(f"Alpha Vantage rate limit reached: {data['Note'][:100]}... Backing off 15m.")
                self._alpha_vantage_cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                return []
            if "Information" in data:
                logger.warning(f"Alpha Vantage notice: {data['Information'][:100]}... Backing off 15m.")
                self._alpha_vantage_cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=15)
                return []
            relevant = []

            for article in feed:
                headline = article.get("title", "")
                summary = article.get("summary", "")
                art_url = article.get("url", "")

                h = compute_news_hash(headline, art_url)
                if h in self._seen_hashes:
                    continue

                if not self._is_relevant(headline, summary):
                    continue

                self._seen_hashes.add(h)

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
                    "url": art_url,
                    "category": ",".join([t.get("topic", "") if isinstance(t, dict) else str(t) for t in article.get("topics", [])[:3]]),
                    "published_at": pub_time,
                    "av_sentiment_score": float(overall_sentiment),
                    "av_sentiment_label": sentiment_label,
                    "source_name": article.get("source", ""),
                })

            logger.info(f"Alpha Vantage: {len(relevant)} relevant articles from {len(feed)} total")
            return relevant

        except httpx.HTTPError as e:
            logger.error(_sanitize_log(f"Alpha Vantage API error: {e}"))
            return []
        except Exception as e:
            logger.error(_sanitize_log(f"Alpha Vantage fetch error: {e}"))
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
        self._seen_hashes.clear()
        logger.debug("News cache cleared")
