"""
Alert Manager — Priority Routing, Throttling, and Notification Delivery

Features:
- Priority levels (INFO, WARNING, CRITICAL)
- Throttles low-priority messages to prevent notification fatigue
- Delivers immediately for CRITICAL events (SL hits, margin warnings, errors)
- Integrates directly with TelegramNotifier
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, Optional
from loguru import logger

from notifications.telegram_bot import TelegramNotifier


class AlertPriority(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertManager:
    """
    Manages notifications with rate limiting and priority rules.
    """

    def __init__(self, notifier: Optional[TelegramNotifier] = None):
        self.notifier = notifier or TelegramNotifier()
        self._last_alert_times: Dict[str, datetime] = {}
        # Min seconds between alerts of same category
        self.throttles = {
            AlertPriority.INFO: 60,       # 1 minute throttle
            AlertPriority.WARNING: 30,    # 30 seconds throttle
            AlertPriority.CRITICAL: 0,    # Instant, never throttled
        }

    def _should_send(self, key: str, priority: AlertPriority) -> bool:
        """Check whether an alert key should be sent based on throttling."""
        if priority == AlertPriority.CRITICAL:
            return True

        now = datetime.now(timezone.utc)
        last_time = self._last_alert_times.get(key)
        throttle_sec = self.throttles.get(priority, 60)

        if last_time and (now - last_time).total_seconds() < throttle_sec:
            logger.debug(f"Alert '{key}' throttled ({priority.value})")
            return False

        self._last_alert_times[key] = now
        return True

    async def notify_trade_opened(self, trade_data: dict):
        """Notify trade entry."""
        if self._should_send("trade_opened", AlertPriority.INFO):
            await self.notifier.send_trade_opened(trade_data)

    async def notify_trade_closed(self, trade_data: dict):
        """Notify trade exit."""
        if self._should_send("trade_closed", AlertPriority.INFO):
            await self.notifier.send_trade_closed(trade_data)

    async def notify_news_alert(self, headline: str, sentiment: str, impact: str, score: float):
        """Notify high/medium impact news."""
        prio = AlertPriority.WARNING if impact == "HIGH" else AlertPriority.INFO
        if self._should_send(f"news_{headline[:30]}", prio):
            await self.notifier.send_news_alert(headline, sentiment, impact, score)

    async def notify_critical_error(self, error_message: str):
        """Notify critical system error or failure."""
        logger.critical(f"AlertManager CRITICAL: {error_message}")
        msg = f"<b>CRITICAL BOT ERROR</b>\n\n{error_message}\n\nPlease check server logs."
        await self.notifier.send_message(msg)

    async def notify_margin_warning(self, margin_level: float):
        """Notify low margin warning."""
        msg = (
            f"<b>MARGIN LEVEL WARNING</b>\n\n"
            f"Account Margin Level: <code>{margin_level:.1f}%</code>\n"
            f"Bot is halting new trade entries to prevent stop-out."
        )
        await self.notifier.send_message(msg)
