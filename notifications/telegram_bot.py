"""
Interactive Telegram Bot — 2-Way Command & Control Center

Features:
1. Real-time Outbound Alerts:
   - Trade entry alerts with inline action buttons (Close Position, Move SL to Breakeven)
   - Trade exit alerts with P&L and duration
   - High-impact news alerts with Gemini sentiment score
   - Daily performance summaries and risk alerts
2. Interactive 2-Way Remote Control:
   - Inline Keyboard Menu (one-tap dashboard control)
   - /start & /menu — Interactive Command Center Dashboard
   - /status — Live balance, equity, margin, running state, current gold spread
   - /positions — Real-time open trades with floating P&L and per-trade close buttons
   - /trades — Recent closed trade history and win rate
   - /pnl — Today's net P&L and performance statistics
   - /news — Live financial news with AI sentiment breakdown
   - /regime — Current market regime (trend vs ranging) and active strategies
   - /price — Real-time XAUUSD Bid, Ask, and Spread ticker
   - /pause & /resume — Remotely toggle automated trading
   - /closeall — Emergency remote kill-switch to flatten all positions
   - /setlot <size> — Adjust default lot size on the fly
   - /setrisk <pct> — Adjust risk % per trade on the fly
   - /help — Command cheatsheet
3. Security:
   - Whitelist authorization guard (rejects unauthorized users)
"""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from loguru import logger

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from config.settings import get_settings
from database import crud


class TelegramNotifier:
    """
    Unified 2-way Telegram bot for automated trading alerts and interactive remote control.
    """

    def __init__(self, bot_instance: Optional[Any] = None):
        self.settings = get_settings()
        self.bot_token = self.settings.telegram.bot_token
        self.chat_id = str(self.settings.telegram.chat_id)
        self.bot_instance = bot_instance

        self._app: Optional[Application] = None
        self._is_polling = False
        self._enabled = bool(self.bot_token and self.chat_id and self.chat_id != "0")

        if not self._enabled:
            logger.warning("Telegram bot not configured or chat ID missing — remote control disabled")

    def set_bot_instance(self, bot_instance: Any):
        """Link the parent TradingBot instance for live data and control."""
        self.bot_instance = bot_instance

    def _is_authorized(self, update: Update) -> bool:
        """Verify message sender matches the authorized Telegram chat ID."""
        if not update.effective_chat:
            return False
        sender_id = str(update.effective_chat.id)
        if sender_id != self.chat_id:
            logger.warning(f"Unauthorized Telegram access attempt from Chat ID: {sender_id}")
            return False
        return True

    # ── Interactive Keyboards ─────────────────────────────────────────────

    def _get_main_keyboard(self) -> InlineKeyboardMarkup:
        """Create the primary interactive Command Center keyboard."""
        paused = getattr(self.bot_instance, "_trading_paused", False)
        pause_btn = (
            InlineKeyboardButton("▶️ Resume Trading", callback_data="cb_resume")
            if paused
            else InlineKeyboardButton("⏸️ Pause Trading", callback_data="cb_pause")
        )

        keyboard = [
            [
                InlineKeyboardButton("📊 Status & Balance", callback_data="cb_status"),
                InlineKeyboardButton("📈 Open Positions", callback_data="cb_positions"),
            ],
            [
                InlineKeyboardButton("💰 P&L Summary", callback_data="cb_pnl"),
                InlineKeyboardButton("📜 Recent Trades", callback_data="cb_trades"),
            ],
            [
                InlineKeyboardButton("📰 News & AI Sentiment", callback_data="cb_news"),
                InlineKeyboardButton("🧠 Market Regime", callback_data="cb_regime"),
            ],
            [
                InlineKeyboardButton("🏷️ Gold Price & Spread", callback_data="cb_price"),
                pause_btn,
            ],
            [
                InlineKeyboardButton("🛑 EMERGENCY CLOSE ALL", callback_data="cb_confirm_closeall"),
                InlineKeyboardButton("🔄 Refresh Menu", callback_data="cb_menu"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    # ── Command & Callback Handlers ──────────────────────────────────────

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start or /menu command."""
        if not self._is_authorized(update):
            await update.effective_message.reply_text("⛔ Unauthorized access.")
            return

        mode = "DEMO" if self.settings.demo_mode else "LIVE"
        text = (
            f"⚡ <b>XAUUSD AI TRADING BOT — COMMAND CENTER</b> ⚡\n\n"
            f"<b>Status:</b> 🟢 ONLINE ({mode})\n"
            f"<b>Symbol:</b> <code>{self.settings.symbol}</code>\n"
            f"<b>Lot Size:</b> <code>{self.settings.trading_params.get('risk', {}).get('default_lot_size', 0.02)}</code>\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
            f"Tap an action button below to monitor or control your bot:"
        )
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=text,
                    reply_markup=self._get_main_keyboard(),
                    parse_mode="HTML",
                )
            except Exception:
                pass
        else:
            await update.effective_message.reply_text(
                text=text,
                reply_markup=self._get_main_keyboard(),
                parse_mode="HTML",
            )

    async def _handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /status command or button."""
        if not self._is_authorized(update):
            return

        account = None
        if self.bot_instance and hasattr(self.bot_instance, "mt5"):
            mt5_obj = self.bot_instance.mt5
            is_conn = mt5_obj.is_connected() if callable(getattr(mt5_obj, "is_connected", None)) else getattr(mt5_obj, "is_connected", False)
            if is_conn:
                account = mt5_obj.get_account_info(auto_reconnect=False)

        paused = getattr(self.bot_instance, "_trading_paused", False)
        state_str = "⏸️ PAUSED" if paused else "🟢 RUNNING"
        mode_str = "DEMO" if self.settings.demo_mode else "LIVE"

        if account:
            balance_str = f"${account.get('balance', 0.0):,.2f}"
            equity_str = f"${account.get('equity', 0.0):,.2f}"
            profit_str = f"${account.get('profit', 0.0):+,.2f}"
            margin_level = account.get("margin_level", 0.0)
            margin_level_str = f"{margin_level:.1f}%" if margin_level else "N/A"
            free_margin_str = f"${account.get('free_margin', 0.0):,.2f}"
        else:
            balance_str = equity_str = profit_str = margin_level_str = free_margin_str = "Unavailable (MT5 Offline)"

        daily_pnl = crud.get_daily_pnl()
        open_trades = crud.get_open_trades()

        msg = (
            f"📊 <b>BOT & ACCOUNT STATUS</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>State:</b> {state_str} ({mode_str})\n"
            f"<b>Account:</b> <code>{self.settings.mt5.login}</code> ({self.settings.mt5.server})\n\n"
            f"💰 <b>Balance:</b> <code>{balance_str}</code>\n"
            f"📈 <b>Equity:</b> <code>{equity_str}</code>\n"
            f"💵 <b>Floating P&L:</b> <code>{profit_str}</code>\n"
            f"📅 <b>Today's Realized P&L:</b> <code>${daily_pnl:+,.2f}</code>\n"
            f"🛡️ <b>Margin Level:</b> <code>{margin_level_str}</code>\n"
            f"🔓 <b>Free Margin:</b> <code>{free_margin_str}</code>\n\n"
            f"<b>Open Positions:</b> {len(open_trades)}\n"
            f"<b>Symbol:</b> <code>{self.settings.symbol}</code>"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 View Open Positions", callback_data="cb_positions")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /positions command or button."""
        if not self._is_authorized(update):
            return

        positions = []
        if self.bot_instance and hasattr(self.bot_instance, "mt5"):
            mt5_obj = self.bot_instance.mt5
            is_conn = mt5_obj.is_connected() if callable(getattr(mt5_obj, "is_connected", None)) else getattr(mt5_obj, "is_connected", False)
            if is_conn:
                positions = mt5_obj.get_open_positions(self.settings.symbol, auto_reconnect=False)

        keyboard_rows = []

        if not positions:
            msg = (
                f"📈 <b>OPEN POSITIONS</b>\n"
                f"{'━' * 25}\n\n"
                f"<i>No open positions currently active on {self.settings.symbol}.</i>\n"
                f"The bot is scanning market regimes and waiting for high-confluence entry signals."
            )
        else:
            msg = f"📈 <b>OPEN POSITIONS ({len(positions)})</b>\n{'━' * 25}\n\n"
            for pos in positions:
                ticket = pos.get("ticket")
                direction = pos.get("type", "BUY")
                volume = pos.get("volume", 0.0)
                entry = pos.get("open_price", 0.0)
                current = pos.get("current_price", 0.0)
                profit = pos.get("profit", 0.0)
                p_emoji = "🟢" if profit >= 0 else "🔴"
                dir_emoji = "📈" if direction == "BUY" else "📉"

                msg += (
                    f"{dir_emoji} <b>Ticket #{ticket}</b> | {direction} {volume} lots\n"
                    f"   • Entry: <code>${entry:,.2f}</code> → Now: <code>${current:,.2f}</code>\n"
                    f"   • P&L: {p_emoji} <code>${profit:+,.2f}</code>\n"
                    f"   • SL: <code>${pos.get('sl', 0.0):,.2f}</code> | TP: <code>${pos.get('tp', 0.0):,.2f}</code>\n\n"
                )
                # Add action button for each position
                keyboard_rows.append([
                    InlineKeyboardButton(f"❌ Close #{ticket} (${profit:+,.1f})", callback_data=f"cb_close_{ticket}")
                ])

        keyboard_rows.append([
            InlineKeyboardButton("🔄 Refresh Positions", callback_data="cb_positions"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu"),
        ])

        reply_markup = InlineKeyboardMarkup(keyboard_rows)
        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=reply_markup, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=reply_markup, parse_mode="HTML")

    async def _handle_trades(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /trades command or button."""
        if not self._is_authorized(update):
            return

        recent_trades = crud.get_recent_trades(limit=5)
        stats = crud.get_trade_stats(days=7)

        if not recent_trades:
            msg = (
                f"📜 <b>TRADE HISTORY</b>\n"
                f"{'━' * 25}\n\n"
                f"<i>No completed trades recorded in the database yet.</i>"
            )
        else:
            msg = (
                f"📜 <b>RECENT TRADES (Last 7 Days)</b>\n"
                f"{'━' * 28}\n"
                f"Win Rate: <b>{stats.get('win_rate', 0.0):.1f}%</b> | Profit Factor: <b>{stats.get('profit_factor', 0.0):.2f}</b>\n\n"
            )
            for t in recent_trades:
                p_emoji = "🟢" if t.profit >= 0 else "🔴"
                msg += (
                    f"{p_emoji} <b>#{t.ticket}</b> {t.order_type} {t.volume} lots\n"
                    f"   Strategy: <i>{t.strategy}</i>\n"
                    f"   In: ${t.entry_price:,.2f} → Out: ${t.exit_price:,.2f}\n"
                    f"   Net P&L: <b>${t.profit:+,.2f}</b> ({t.status})\n\n"
                )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 View P&L Stats", callback_data="cb_pnl")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_pnl(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /pnl command or button."""
        if not self._is_authorized(update):
            return

        daily_pnl = crud.get_daily_pnl()
        stats_7d = crud.get_trade_stats(days=7)
        stats_30d = crud.get_trade_stats(days=30)

        daily_emoji = "🟢" if daily_pnl >= 0 else "🔴"

        msg = (
            f"💰 <b>P&L & PERFORMANCE OVERVIEW</b>\n"
            f"{'━' * 28}\n\n"
            f"{daily_emoji} <b>Today's P&L:</b> <code>${daily_pnl:+,.2f}</code>\n\n"
            f"📅 <b>7-Day Performance:</b>\n"
            f"   • Total Trades: {stats_7d.get('total_trades', 0)}\n"
            f"   • Win Rate: <b>{stats_7d.get('win_rate', 0.0):.1f}%</b>\n"
            f"   • Net Profit: <code>${stats_7d.get('total_profit', 0.0):+,.2f}</code>\n"
            f"   • Profit Factor: {stats_7d.get('profit_factor', 0.0):.2f}\n\n"
            f"📆 <b>30-Day Performance:</b>\n"
            f"   • Total Trades: {stats_30d.get('total_trades', 0)}\n"
            f"   • Win Rate: <b>{stats_30d.get('win_rate', 0.0):.1f}%</b>\n"
            f"   • Net Profit: <code>${stats_30d.get('total_profit', 0.0):+,.2f}</code>\n"
            f"   • Profit Factor: {stats_30d.get('profit_factor', 0.0):.2f}"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 View Trade History", callback_data="cb_trades")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_news(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /news command or button."""
        if not self._is_authorized(update):
            return

        sentiment_score = crud.get_recent_sentiment(hours=6)
        sent_emoji = "📈 BULLISH" if sentiment_score > 0.1 else ("📉 BEARISH" if sentiment_score < -0.1 else "➡️ NEUTRAL")

        msg = (
            f"📰 <b>MARKET NEWS & AI SENTIMENT</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>Composite 6H Sentiment:</b> {sent_emoji} (<code>{sentiment_score:+.2f}</code>)\n"
            f"<b>AI Engine:</b> Gemini 3.6 Flash + FinBERT\n\n"
        )

        # Pull top news events from DB
        session = crud.get_session()
        try:
            from database.models import NewsEvent
            events = session.query(NewsEvent).order_by(NewsEvent.published_at.desc()).limit(3).all()
            if events:
                msg += "<b>Latest Macro Analysis:</b>\n"
                for ev in events:
                    impact_emoji = "🔴" if ev.impact_level == "HIGH" else "🟡"
                    msg += (
                        f"{impact_emoji} <b>{ev.headline[:75]}...</b>\n"
                        f"   Sentiment: {ev.sentiment} ({ev.sentiment_score:+.2f})\n"
                    )
                    if ev.gemini_analysis:
                        msg += f"   <i>AI Note:</i> {ev.gemini_analysis[:100]}...\n\n"
            else:
                msg += "<i>No recent news cached. The bot queries Finnhub and Alpha Vantage every 15 minutes.</i>\n"
        finally:
            session.close()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh News", callback_data="cb_news")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_regime(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /regime command or button."""
        if not self._is_authorized(update):
            return

        msg = (
            f"🧠 <b>MARKET REGIME & ACTIVE STRATEGIES</b>\n"
            f"{'━' * 28}\n\n"
        )

        if self.bot_instance and hasattr(self.bot_instance, "regime_detector"):
            regime = getattr(self.bot_instance, "_last_regime", None)
            if regime:
                msg += (
                    f"<b>Current Regime:</b> <code>{regime.regime.value}</code>\n"
                    f"<b>Trend Strength (ADX):</b> <code>{regime.adx_value:.1f}</code>\n"
                    f"<b>Volatility Percentile:</b> <code>{regime.volatility_percentile:.1f}% ({regime.volatility_label})</code>\n"
                    f"<b>Position Sizing Modifier:</b> <code>{regime.position_size_modifier:.2f}x</code>\n"
                    f"<b>Trading Allowed:</b> {'✅ YES' if regime.should_trade else '⏸️ PAUSED'}\n\n"
                    f"<b>Recommended Strategies:</b>\n"
                )
                for s in regime.recommended_strategies:
                    msg += f"   • <code>{s}</code>\n"
            else:
                msg += "<i>Regime analysis will be updated after the next H4 candle cycle.</i>\n"
        else:
            msg += "<i>Bot instance offline or warming up.</i>\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_price(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /price command or button."""
        if not self._is_authorized(update):
            return

        tick = None
        if self.bot_instance and hasattr(self.bot_instance, "mt5"):
            mt5_obj = self.bot_instance.mt5
            is_conn = mt5_obj.is_connected() if callable(getattr(mt5_obj, "is_connected", None)) else getattr(mt5_obj, "is_connected", False)
            if is_conn:
                tick = mt5_obj.get_current_tick(self.settings.symbol, auto_reconnect=False)

        if tick:
            bid = tick.get("bid", 0.0)
            ask = tick.get("ask", 0.0)
            spread = tick.get("spread", 0.0)
            msg = (
                f"🏷️ <b>LIVE {self.settings.symbol} TICKER</b>\n"
                f"{'━' * 25}\n\n"
                f"<b>Bid:</b> <code>${bid:,.2f}</code>\n"
                f"<b>Ask:</b> <code>${ask:,.2f}</code>\n"
                f"<b>Spread:</b> <code>{spread:.1f} points</code>\n"
                f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
            )
        else:
            msg = f"🏷️ <b>{self.settings.symbol} TICKER</b>\n\n<i>MT5 not connected or markets closed.</i>"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Price", callback_data="cb_price")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Pause the trading bot."""
        if not self._is_authorized(update):
            return

        if self.bot_instance:
            self.bot_instance._trading_paused = True
            logger.warning("Bot trading paused via Telegram remote control")
            msg = "⏸️ <b>Trading PAUSED</b>\n\nThe bot will NOT open new trades. Existing positions will still be managed by trailing stops."
        else:
            msg = "⚠️ Bot instance not linked."

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶️ Resume Trading", callback_data="cb_resume")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Resume the trading bot."""
        if not self._is_authorized(update):
            return

        if self.bot_instance:
            self.bot_instance._trading_paused = False
            logger.info("Bot trading resumed via Telegram remote control")
            msg = "▶️ <b>Trading RESUMED</b>\n\nAutomated strategy scanning and execution is active."
        else:
            msg = "⚠️ Bot instance not linked."

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 View Status", callback_data="cb_status")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_confirm_closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt confirmation for emergency close all."""
        if not self._is_authorized(update):
            return

        msg = (
            f"⚠️ <b>EMERGENCY KILL-SWITCH CONFIRMATION</b> ⚠️\n\n"
            f"Are you sure you want to <b>CLOSE ALL OPEN POSITIONS</b> immediately?\n"
            f"This will execute market close orders on all active trades."
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🛑 YES, CLOSE ALL NOW", callback_data="cb_do_closeall")],
            [InlineKeyboardButton("❌ Cancel", callback_data="cb_positions")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_do_closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute emergency close all positions."""
        if not self._is_authorized(update):
            return

        closed_count = 0
        if self.bot_instance and hasattr(self.bot_instance, "trade_executor"):
            te = self.bot_instance.trade_executor
            if hasattr(te, "close_all_positions"):
                closed_count = te.close_all_positions(self.settings.symbol)
            elif hasattr(self.bot_instance, "mt5"):
                closed_count = self.bot_instance.mt5.close_all_positions(self.settings.symbol)
        elif self.bot_instance and hasattr(self.bot_instance, "mt5"):
            closed_count = self.bot_instance.mt5.close_all_positions(self.settings.symbol)

        msg = (
            f"🛑 <b>ALL POSITIONS CLOSED</b>\n\n"
            f"Successfully closed <b>{closed_count}</b> open position(s).\n"
            f"All trades have been flattened."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 View Status", callback_data="cb_status")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])

        if update.callback_query:
            await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")
        else:
            await update.effective_message.reply_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_close_single(self, update: Update, ticket: int):
        """Close a specific position by ticket number."""
        if not self._is_authorized(update):
            return

        success = False
        if self.bot_instance and hasattr(self.bot_instance, "trade_executor"):
            te = self.bot_instance.trade_executor
            if hasattr(te, "close_trade"):
                success = te.close_trade(ticket, reason="telegram_manual")
            elif hasattr(te, "close_position"):
                success = te.close_position(ticket, comment="Telegram manual close")
        elif self.bot_instance and hasattr(self.bot_instance, "mt5"):
            success = self.bot_instance.mt5.close_position(ticket, comment="telegram_manual")

        if success:
            msg = f"✅ Position <b>#{ticket}</b> closed successfully."
        else:
            msg = f"❌ Failed to close position <b>#{ticket}</b>. Check MT5 connection."

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 View Positions", callback_data="cb_positions")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])
        await update.callback_query.edit_message_text(text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_set_lot(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set default lot size via /setlot <size>."""
        if not self._is_authorized(update):
            return

        if not context.args:
            await update.effective_message.reply_text(
                "Usage: <code>/setlot 0.02</code> (range: 0.01 to 0.10)", parse_mode="HTML"
            )
            return

        try:
            new_lot = float(context.args[0])
            if new_lot < 0.01 or new_lot > 0.50:
                await update.effective_message.reply_text("❌ Lot size must be between 0.01 and 0.50.")
                return

            # Update live settings
            self.settings.trading_params.setdefault("risk", {})["default_lot_size"] = new_lot
            if self.bot_instance and hasattr(self.bot_instance, "risk_manager"):
                self.bot_instance.risk_manager.default_lot = new_lot

            await update.effective_message.reply_text(
                f"✅ <b>Default Lot Size Updated:</b> <code>{new_lot}</code>",
                parse_mode="HTML",
            )
            logger.info(f"Default lot size changed to {new_lot} via Telegram")

        except ValueError:
            await update.effective_message.reply_text("❌ Invalid number format. Example: <code>/setlot 0.02</code>")

    async def _handle_set_risk(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set max risk percent per trade via /setrisk <pct>."""
        if not self._is_authorized(update):
            return

        if not context.args:
            await update.effective_message.reply_text(
                "Usage: <code>/setrisk 2.5</code> (range: 0.5% to 5.0%)", parse_mode="HTML"
            )
            return

        try:
            new_risk = float(context.args[0])
            if new_risk < 0.5 or new_risk > 5.0:
                await update.effective_message.reply_text("❌ Risk per trade must be between 0.5% and 5.0%.")
                return

            self.settings.trading_params.setdefault("risk", {})["max_risk_per_trade_pct"] = new_risk
            if self.bot_instance and hasattr(self.bot_instance, "risk_manager"):
                self.bot_instance.risk_manager.max_risk_pct = new_risk

            await update.effective_message.reply_text(
                f"✅ <b>Max Risk Per Trade Updated:</b> <code>{new_risk:.1f}%</code>",
                parse_mode="HTML",
            )
            logger.info(f"Risk per trade changed to {new_risk}% via Telegram")

        except ValueError:
            await update.effective_message.reply_text("❌ Invalid number format. Example: <code>/setrisk 2.0</code>")

    async def _handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command."""
        if not self._is_authorized(update):
            return

        msg = (
            f"📖 <b>TELEGRAM BOT COMMAND CHEATSHEET</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>Navigation & Menus:</b>\n"
            f"• <code>/start</code> or <code>/menu</code> — Open interactive button dashboard\n"
            f"• <code>/help</code> — Show this cheatsheet\n\n"
            f"<b>Market & Account Monitoring:</b>\n"
            f"• <code>/status</code> — Account balance, equity, and bot health\n"
            f"• <code>/positions</code> — List open trades with floating P&L\n"
            f"• <code>/trades</code> — Recent closed trade log\n"
            f"• <code>/pnl</code> — Today's and 30-day performance\n"
            f"• <code>/news</code> — Macro news and Gemini sentiment\n"
            f"• <code>/regime</code> — Current market regime & active strategies\n"
            f"• <code>/price</code> — Real-time Gold Bid, Ask, Spread\n\n"
            f"<b>Remote Control & Emergency:</b>\n"
            f"• <code>/pause</code> — Pause opening new trades\n"
            f"• <code>/resume</code> — Resume automated trading\n"
            f"• <code>/closeall</code> — Flatten all open positions immediately\n"
            f"• <code>/setlot 0.02</code> — Set default lot size\n"
            f"• <code>/setrisk 2.5</code> — Set max risk percent"
        )
        await update.effective_message.reply_text(msg, parse_mode="HTML")

    async def _callback_router(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route callback queries from inline buttons with instant answer."""
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass

        data = query.data
        if data == "cb_menu":
            await self._handle_start(update, context)
        elif data == "cb_status":
            await self._handle_status(update, context)
        elif data == "cb_positions":
            await self._handle_positions(update, context)
        elif data == "cb_trades":
            await self._handle_trades(update, context)
        elif data == "cb_pnl":
            await self._handle_pnl(update, context)
        elif data == "cb_news":
            await self._handle_news(update, context)
        elif data == "cb_regime":
            await self._handle_regime(update, context)
        elif data == "cb_price":
            await self._handle_price(update, context)
        elif data == "cb_pause":
            await self._handle_pause(update, context)
        elif data == "cb_resume":
            await self._handle_resume(update, context)
        elif data == "cb_confirm_closeall":
            await self._handle_confirm_closeall(update, context)
        elif data == "cb_do_closeall":
            await self._handle_do_closeall(update, context)
        elif data.startswith("cb_close_"):
            ticket = int(data.split("_")[-1])
            await self._handle_close_single(update, ticket)

    # ── Background Polling Lifecycle ──────────────────────────────────────

    async def start_polling(self):
        """Start the interactive Telegram bot polling in the background."""
        if not self._enabled:
            return

        try:
            self._app = ApplicationBuilder().token(self.bot_token).build()

            # Register command handlers
            self._app.add_handler(CommandHandler(["start", "menu"], self._handle_start))
            self._app.add_handler(CommandHandler("status", self._handle_status))
            self._app.add_handler(CommandHandler(["positions", "pos"], self._handle_positions))
            self._app.add_handler(CommandHandler("trades", self._handle_trades))
            self._app.add_handler(CommandHandler("pnl", self._handle_pnl))
            self._app.add_handler(CommandHandler("news", self._handle_news))
            self._app.add_handler(CommandHandler("regime", self._handle_regime))
            self._app.add_handler(CommandHandler("price", self._handle_price))
            self._app.add_handler(CommandHandler("pause", self._handle_pause))
            self._app.add_handler(CommandHandler("resume", self._handle_resume))
            self._app.add_handler(CommandHandler("closeall", self._handle_confirm_closeall))
            self._app.add_handler(CommandHandler("setlot", self._handle_set_lot))
            self._app.add_handler(CommandHandler("setrisk", self._handle_set_risk))
            self._app.add_handler(CommandHandler("help", self._handle_help))

            # Register callback button router
            self._app.add_handler(CallbackQueryHandler(self._callback_router))

            await self._app.initialize()
            await self._app.start()
            await self._app.updater.start_polling(drop_pending_updates=True)
            self._is_polling = True
            logger.info("⚡ Telegram Interactive Bot polling started successfully")

        except Exception as e:
            logger.error(f"Failed to start Telegram polling: {e}")

    async def stop_polling(self):
        """Stop background polling gracefully."""
        if self._app and self._is_polling:
            try:
                await self._app.updater.stop()
                await self._app.stop()
                await self._app.shutdown()
                self._is_polling = False
                logger.info("Telegram Interactive Bot polling stopped")
            except Exception as e:
                logger.debug(f"Telegram stop error: {e}")

    # ── Outbound Notifications ────────────────────────────────────────────

    async def send_message(self, text: str, parse_mode: str = "HTML", reply_markup: Any = None):
        """Send a message to the configured owner chat."""
        if not self._enabled:
            return

        try:
            if self._app and self._app.bot:
                bot = self._app.bot
            else:
                from telegram import Bot
                bot = Bot(token=self.bot_token)

            await bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Exception as e:
            logger.error(f"Telegram send error: {e}")

    async def send_trade_opened(self, trade: dict):
        """Send trade entry alert with interactive quick-action buttons."""
        direction_emoji = "📈" if trade["direction"] == "BUY" else "📉"
        ticket = trade.get("ticket", "")

        msg = (
            f"{direction_emoji} <b>NEW TRADE OPENED</b>\n\n"
            f"<b>Direction:</b> <b>{trade['direction']}</b> ({trade['volume']} lots)\n"
            f"<b>Ticket:</b> <code>#{ticket}</code>\n"
            f"<b>Entry Price:</b> <code>${trade['entry_price']:,.2f}</code>\n"
            f"<b>Stop Loss:</b> <code>${trade['stop_loss']:,.2f}</code>\n"
            f"<b>Take Profit:</b> <code>${trade['take_profit']:,.2f}</code>\n"
            f"<b>Strategy:</b> <i>{trade['strategy']}</i>\n"
            f"<b>Confluence:</b> <b>{trade['confluence_score']:.0f}/100</b>\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )

        buttons = []
        if ticket:
            buttons.append([
                InlineKeyboardButton(f"❌ Close Trade #{ticket}", callback_data=f"cb_close_{ticket}")
            ])
        buttons.append([InlineKeyboardButton("📊 View Open Positions", callback_data="cb_positions")])

        await self.send_message(msg, reply_markup=InlineKeyboardMarkup(buttons))

    async def send_trade_closed(
        self,
        ticket: int,
        direction: str,
        profit: float,
        entry: float,
        exit_price: float,
        duration_min: int = 0,
        reason: str = "TP/SL",
    ):
        """Send trade close notification."""
        emoji = "✅" if profit > 0 else "❌"
        profit_color = "🟢" if profit > 0 else "🔴"

        msg = (
            f"{emoji} <b>TRADE CLOSED ({reason})</b>\n\n"
            f"<b>Ticket:</b> <code>#{ticket}</code> | <b>{direction}</b>\n"
            f"<b>Entry:</b> ${entry:,.2f} → <b>Exit:</b> ${exit_price:,.2f}\n"
            f"{profit_color} <b>Realized P&L:</b> <b>${profit:+,.2f}</b>\n"
            f"<b>Duration:</b> {duration_min} minutes\n"
            f"<b>Time:</b> {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("💰 View Daily P&L", callback_data="cb_pnl")],
        ])
        await self.send_message(msg, reply_markup=keyboard)

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
        profit_color = "🟢" if daily_pnl >= 0 else "🔴"

        msg = (
            f"{pnl_emoji} <b>DAILY TRADING SUMMARY</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>Balance:</b> <code>${balance:,.2f}</code>\n"
            f"{profit_color} <b>Today's Net P&L:</b> <code>${daily_pnl:+,.2f}</code>\n"
            f"<b>Total Trades:</b> {total_trades}\n"
            f"<b>Won:</b> {winning} | <b>Lost:</b> {losing}\n"
            f"<b>Win Rate:</b> <b>{win_rate:.1f}%</b>\n\n"
            f"📅 Date: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📜 View Trade History", callback_data="cb_trades")],
        ])
        await self.send_message(msg, reply_markup=keyboard)

    async def send_news_alert(self, headline: str, sentiment: str, impact: str, score: float):
        """Send high-impact news alert."""
        impact_emoji = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(impact, "⚪")
        sentiment_emoji = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "➡️"}.get(sentiment, "➡️")

        msg = (
            f"{impact_emoji} <b>HIGH IMPACT MACRO ALERT</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>Headline:</b> {headline}\n\n"
            f"{sentiment_emoji} <b>Sentiment:</b> <b>{sentiment}</b> (<code>{score:+.2f}</code>)\n"
            f"<b>Impact:</b> {impact}\n"
            f"<b>Action:</b> Pre-event cooling pause activated for new entries."
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📰 View News Digest", callback_data="cb_news")],
        ])
        await self.send_message(msg, reply_markup=keyboard)

    async def send_risk_alert(self, message: str):
        """Send risk management alert."""
        msg = f"⚠️ <b>RISK CONTROLLER ALERT</b>\n\n{message}"
        await self.send_message(msg)

    async def send_bot_status(self, status: str, details: str = ""):
        """Send bot status update."""
        emoji = "🟢" if status == "RUNNING" else ("🔴" if status == "STOPPED" else "🟡")
        msg = f"{emoji} <b>XAUUSD Bot Status: {status}</b>"
        if details:
            msg += f"\n\n{details}"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📱 Open Menu", callback_data="cb_menu")],
        ])
        await self.send_message(msg, reply_markup=keyboard)


    def run_standalone(self):
        """Run standalone Telegram interactive polling loop using run_polling()."""
        if not self._enabled:
            logger.error("Telegram bot is not enabled. Check TELEGRAM_BOT_TOKEN.")
            return

        app = ApplicationBuilder().token(self.bot_token).build()
        self._app = app

        # Register command handlers
        app.add_handler(CommandHandler(["start", "menu"], self._handle_start))
        app.add_handler(CommandHandler("status", self._handle_status))
        app.add_handler(CommandHandler(["positions", "pos"], self._handle_positions))
        app.add_handler(CommandHandler("trades", self._handle_trades))
        app.add_handler(CommandHandler("pnl", self._handle_pnl))
        app.add_handler(CommandHandler("news", self._handle_news))
        app.add_handler(CommandHandler("regime", self._handle_regime))
        app.add_handler(CommandHandler("price", self._handle_price))
        app.add_handler(CommandHandler("pause", self._handle_pause))
        app.add_handler(CommandHandler("resume", self._handle_resume))
        app.add_handler(CommandHandler("closeall", self._handle_confirm_closeall))
        app.add_handler(CommandHandler("setlot", self._handle_set_lot))
        app.add_handler(CommandHandler("setrisk", self._handle_set_risk))
        app.add_handler(CommandHandler("help", self._handle_help))

        # Register callback button router
        app.add_handler(CallbackQueryHandler(self._callback_router))

        async def post_init(application):
            logger.success("⚡ Telegram Bot is actively listening for your commands and button clicks!")
            try:
                await application.bot.send_message(
                    chat_id=self.chat_id,
                    text="⚡ <b>XAUUSD AI Trading Bot — Command Center Online!</b>\n\n"
                         "Your bot is actively listening with ZERO-LATENCY response.\n"
                         "Tap any button below to view status or control trading:",
                    reply_markup=self._get_main_keyboard(),
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.warning(f"Could not send welcome message: {e}")

        app.post_init = post_init
        logger.info("Starting Telegram Bot real-time polling (poll_interval=0.0s for instant response)...")
        app.run_polling(poll_interval=0.0, drop_pending_updates=False)
