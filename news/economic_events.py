"""
Economic Events Calendar & High-Impact News Detection

Detects upcoming high-impact macroeconomic events:
- FOMC Rate Decision & Press Conferences
- Non-Farm Payrolls (NFP) & US Unemployment
- CPI / PPI Inflation Prints
- ISM Manufacturing & Services PMI
- US GDP Releases

Signals the trading engine to pause new positions and tighten existing stops
before and after high-impact volatility spikes.
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from loguru import logger
import httpx

from config.settings import get_settings


class EconomicEventsManager:
    """
    Monitors economic releases and informs the bot when high-impact
    events are scheduled within a pre-defined volatility window.
    """

    # Major high-impact USD events that create extreme gold volatility
    HIGH_IMPACT_KEYWORDS = [
        "interest rate",
        "fed",
        "fomc",
        "non-farm",
        "nonfarm",
        "nfp",
        "cpi",
        "consumer price",
        "inflation",
        "ppi",
        "gdp",
        "ism",
        "powell",
        "rate decision",
    ]

    def __init__(self):
        self.settings = get_settings()
        self.finnhub_key = self.settings.news.finnhub_api_key
        self.pre_event_pause_minutes = self.settings.news_params.get("pre_event_pause_minutes", 30)
        self.post_event_pause_minutes = self.settings.news_params.get("post_event_pause_minutes", 30)
        self._cached_events: List[Dict] = []
        self._last_fetch_time: Optional[datetime] = None

    async def fetch_upcoming_events(self) -> List[Dict]:
        """
        Fetch economic calendar from Finnhub API.
        Cached for 1 hour to respect rate limits.
        """
        now = datetime.now(timezone.utc)

        # Use cache if fresh (< 60 minutes old)
        if self._last_fetch_time and (now - self._last_fetch_time).total_seconds() < 3600:
            return self._cached_events

        if not self.finnhub_key:
            return []

        try:
            today_str = now.strftime("%Y-%m-%d")
            end_date = (now + timedelta(days=7)).strftime("%Y-%m-%d")
            url = "https://finnhub.io/api/v1/calendar/economic"
            params = {
                "from": today_str,
                "to": end_date,
            }
            headers = {"X-Finnhub-Token": self.finnhub_key}

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url, params=params, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    events = data.get("economicCalendar", [])
                    filtered = []
                    for ev in events:
                        # Focus on US / USD events
                        country = ev.get("country", "").upper()
                        if country in ("US", "USA", "UNITED STATES"):
                            filtered.append({
                                "event": ev.get("event", ""),
                                "time": ev.get("time", ""),
                                "impact": ev.get("impact", "medium").upper(),
                                "actual": ev.get("actual"),
                                "estimate": ev.get("estimate"),
                                "prev": ev.get("prev"),
                            })
                    self._cached_events = filtered
                    self._last_fetch_time = now
                    logger.info(f"Economic Calendar: Loaded {len(filtered)} US events for the week")
                    return filtered

        except Exception as e:
            logger.debug(f"Could not fetch economic calendar from Finnhub: {e}")

        return self._cached_events

    def is_high_impact_imminent(self) -> Tuple[bool, Optional[str]]:
        """
        Check if a high-impact event is scheduled within pre-event pause window.

        Returns:
            (is_imminent, event_name)
        """
        now = datetime.now(timezone.utc)

        for ev in self._cached_events:
            ev_name = ev.get("event", "").lower()
            # Check impact level or keyword match
            is_high = ev.get("impact") in ("HIGH", "3") or any(k in ev_name for k in self.HIGH_IMPACT_KEYWORDS)
            if not is_high:
                continue

            # Parse event time
            ev_time_str = ev.get("time", "")
            if not ev_time_str:
                continue

            try:
                # Format: "YYYY-MM-DD HH:MM:SS" or ISO
                if "T" in ev_time_str:
                    ev_dt = datetime.fromisoformat(ev_time_str.replace("Z", "+00:00"))
                else:
                    ev_dt = datetime.strptime(ev_time_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)

                diff_seconds = (ev_dt - now).total_seconds()
                diff_minutes = diff_seconds / 60.0

                # Pre-event pause window (e.g. 0 to +30 min)
                if 0 <= diff_minutes <= self.pre_event_pause_minutes:
                    return True, f"{ev.get('event')} in {int(diff_minutes)}m"

                # Post-event pause window (e.g. 0 to -30 min)
                if -self.post_event_pause_minutes <= diff_minutes < 0:
                    return True, f"{ev.get('event')} released {abs(int(diff_minutes))}m ago (cooling down)"

            except Exception:
                continue

        # 2. Check recent HIGH impact news from database (within post_event_pause_minutes)
        try:
            from database import crud
            from database.models import NewsEvent
            session = crud.get_session()
            cutoff = now - timedelta(minutes=self.post_event_pause_minutes)
            recent_high = session.query(NewsEvent).filter(
                NewsEvent.impact_level == "HIGH",
                NewsEvent.published_at >= cutoff,
            ).first()
            session.close()

            if recent_high:
                return True, f"High Impact News: {recent_high.headline[:50]}... (cooling down)"
        except Exception:
            pass

        return False, None
