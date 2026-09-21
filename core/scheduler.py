"""
Task Scheduler — Periodic Background Tasks

Uses APScheduler to run:
- Periodic news and sentiment updates
- Economic calendar checks
- Daily performance report generation
- Model retraining triggers
"""

from typing import Callable, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from loguru import logger


class BotScheduler:
    """
    Manages asynchronous periodic jobs for the trading bot.
    """

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self._is_running = False

    def start(self):
        """Start the scheduler."""
        if not self._is_running:
            self.scheduler.start()
            self._is_running = True
            logger.info("Bot background scheduler started")

    def shutdown(self):
        """Shutdown the scheduler."""
        if self._is_running:
            self.scheduler.shutdown()
            self._is_running = False
            logger.info("Bot background scheduler stopped")

    def add_news_job(self, func: Callable, interval_minutes: int = 15):
        """Schedule periodic news checking."""
        self.scheduler.add_job(
            func,
            trigger=IntervalTrigger(minutes=interval_minutes),
            id="news_check",
            name="Periodic News Refresh",
            replace_existing=True,
        )
        logger.info(f"Scheduled news job every {interval_minutes} minutes")

    def add_daily_summary_job(self, func: Callable, hour: int = 22, minute: int = 0):
        """Schedule daily summary notification at UTC hour:minute."""
        self.scheduler.add_job(
            func,
            trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
            id="daily_summary",
            name="Daily Performance Report",
            replace_existing=True,
        )
        logger.info(f"Scheduled daily summary job at {hour:02d}:{minute:02d} UTC")

    def add_economic_events_job(self, func: Callable, interval_hours: int = 1):
        """Schedule economic events refresh."""
        self.scheduler.add_job(
            func,
            trigger=IntervalTrigger(hours=interval_hours),
            id="economic_events",
            name="Economic Calendar Refresh",
            replace_existing=True,
        )
        logger.info(f"Scheduled economic calendar refresh every {interval_hours} hour(s)")
