"""
Telegram Bot — Notifications & Remote Control

Sends alerts for:
- Trade entries/exits
- Daily P&L summaries
- High-impact news
- Bot status updates

Commands:
- /status — Bot status + open positions
- /trades — Recent trade history
- /pnl — Current P&L
- /pause / /resume — Control bot
- /risk — Current risk exposure
"""

import asyncio
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from config.settings import get_settings


class TelegramNotifier:
    """
    Sends formatted trading alerts and summaries via Telegram.
    """

    def __init__(self):
        settings = get_settings()
        self.bot_token = settings.telegram.bot_token
        self.chat_id = settings.telegram.chat_id
        self._bot = None
        self._enabled = bool(self.bot_token and self.chat_id)

        if not self._enabled:
            logger.warning("Telegram not configured — notifications disabled")

    def _get_bot(self):
        """Lazy-load the Telegram bot."""
        if self._bot is None and self._enabled:
            try:
                from telegram import Bot
                self._bot = Bot(token=self.bot_token)
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")
        return self._bot

    async def send_message(self, text: str, parse_mode: str = "HTML"):
        """Send a message to the configured chat."""
        if not self._enabled:
            return

        bot = self._get_bot()
        if not bot:
            return

        try:
            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
            )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def send_trade_opened(self, trade: dict):
        """Send trade entry notification."""
        direction_emoji = "📈" if trade["direction"] == "BUY" else "📉"

        msg = (
            f"{direction_emoji} <b>NEW TRADE OPENED</b>\n\n"
            f"<b>Direction:</b> {trade['direction']}\n"
            f"<b>Volume:</b> {trade['volume']} lots\n"
            f"<b>Entry:</b> ${trade['entry_price']:,.2f}\n"
            f"<b>Stop Loss:</b> ${trade['stop_loss']:,.2f}\n"
            f"<b>Take Profit:</b> ${trade['take_profit']:,.2f}\n"
            f"<b>Strategy:</b> {trade['strategy']}\n"
            f"<b>Confluence:</b> {trade['confluence_score']:.0f}/100\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )

        await self.send_message(msg)

    async def send_trade_closed(
        self,
        ticket: int,
        direction: str,
        profit: float,
        entry: float,
        exit_price: float,
        duration_min: int = 0,
    ):
        """Send trade close notification."""
        emoji = "✅" if profit > 0 else "❌"
        profit_color = "🟢" if profit > 0 else "🔴"

        msg = (
            f"{emoji} <b>TRADE CLOSED</b>\n\n"
            f"<b>Ticket:</b> #{ticket}\n"
            f"<b>Direction:</b> {direction}\n"
            f"<b>Entry:</b> ${entry:,.2f}\n"
            f"<b>Exit:</b> ${exit_price:,.2f}\n"
            f"{profit_color} <b>P&L:</b> ${profit:+,.2f}\n"
            f"<b>Duration:</b> {duration_min} min\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )

        await self.send_message(msg)

    async def send_daily_summary(
        self,
        balance: float,
        daily_pnl: float,
        total_trades: int,
        winning: int,
        losing: int,
        win_rate: float,
    ):
        """Send end-of-day performance summary."""
        pnl_emoji = "📊" if daily_pnl >= 0 else "📉"

        msg = (
            f"{pnl_emoji} <b>DAILY SUMMARY</b>\n"
            f"{'━' * 25}\n\n"
            f"<b>Balance:</b> ${balance:,.2f}\n"
            f"<b>Daily P&L:</b> ${daily_pnl:+,.2f}\n"
            f"<b>Trades:</b> {total_trades}\n"
            f"<b>Won:</b> {winning} | <b>Lost:</b> {losing}\n"
            f"<b>Win Rate:</b> {win_rate:.1f}%\n\n"
            f"📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        )

        await self.send_message(msg)

    async def send_news_alert(self, headline: str, sentiment: str, impact: str, score: float):
        """Send high-impact news alert."""
        impact_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(impact, "⚪")
        sentiment_emoji = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "➡️"}.get(sentiment, "➡️")

        msg = (
            f"{impact_emoji} <b>NEWS ALERT — {impact} IMPACT</b>\n\n"
            f"<b>Headline:</b> {headline}\n"
            f"{sentiment_emoji} <b>Sentiment:</b> {sentiment} ({score:+.2f})\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )

        await self.send_message(msg)

    async def send_risk_alert(self, message: str):
        """Send risk management alert."""
        msg = f"⚠️ <b>RISK ALERT</b>\n\n{message}"
        await self.send_message(msg)

    async def send_bot_status(self, status: str, details: str = ""):
        """Send bot status update."""
        emoji = "🟢" if status == "RUNNING" else "🔴" if status == "STOPPED" else "🟡"
        msg = f"{emoji} <b>Bot Status:</b> {status}"
        if details:
            msg += f"\n{details}"
        await self.send_message(msg)
