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
from datetime import datetime, timedelta, timezone
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

        # Parse authorized chat IDs (supports comma-separated list of IDs)
        raw_chat_id = str(self.settings.telegram.chat_id or "").strip()
        self.authorized_ids: set[str] = {
            cid.strip()
            for cid in raw_chat_id.split(",")
            if cid.strip() and cid.strip() != "0"
        }

        self._app: Optional[Application] = None
        self._is_polling = False
        self._enabled = bool(self.bot_token and self.chat_id and self.chat_id != "0")

        # News alert deduplication cache
        self._sent_news_alert_hashes: set[str] = set()
        self._preload_alerted_news()

        if not self._enabled:
            logger.warning("Telegram bot not configured or chat ID missing — remote control disabled")

    def _preload_alerted_news(self):
        """Preload hashes of recent news from DB so restarts don't re-alert old high-impact items."""
        try:
            from database.models import get_session, NewsEvent
            from news.news_utils import compute_news_hash
            session = get_session()
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
                events = session.query(NewsEvent.headline, NewsEvent.url).filter(
                    NewsEvent.fetched_at >= cutoff
                ).all()
                for h_text, u_text in events:
                    if h_text:
                        self._sent_news_alert_hashes.add(compute_news_hash(h_text, u_text or ""))
            finally:
                session.close()
        except Exception as e:
            logger.debug(f"Could not preload alerted news: {e}")

    def set_bot_instance(self, bot_instance: Any):
        """Link the parent TradingBot instance for live data and control."""
        self.bot_instance = bot_instance

    def _is_authorized(self, update: Update) -> bool:
        """
        Verify message sender matches the authorized Telegram chat or user ID whitelist.
        Rejects unauthorized users with security logging.
        """
        if not self.authorized_ids:
            return False

        sender_chat_id = str(update.effective_chat.id) if update.effective_chat else ""
        sender_user_id = str(update.effective_user.id) if update.effective_user else ""
        username = update.effective_user.username if update.effective_user else "unknown"

        if sender_chat_id in self.authorized_ids or sender_user_id in self.authorized_ids:
            return True

        logger.warning(
            f"⛔ UNAUTHORIZED Telegram access attempt | User: @{username} "
            f"(User ID: {sender_user_id}, Chat ID: {sender_chat_id})"
        )
        return False


    async def _safe_edit_or_reply(self, update: Update, text: str, reply_markup: Any = None, parse_mode: str = "HTML"):
        """Safely edit the current callback message, handling 'Message is not modified' gracefully."""
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return
            except Exception as e:
                err_str = str(e)
                if "Message is not modified" in err_str:
                    try:
                        await update.callback_query.answer("Already up to date")
                    except Exception:
                        pass
                    return
                logger.debug(f"Could not edit message, falling back to reply: {e}")

        if update.effective_message:
            try:
                await update.effective_message.reply_text(
                    text=text,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except Exception as e:
                logger.error(f"Failed to send reply message: {e}")

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
                InlineKeyboardButton("🎓 Self-Learning & Adaptation", callback_data="cb_learning"),
                InlineKeyboardButton("🏷️ Gold Price & Spread", callback_data="cb_price"),
            ],
            [
                pause_btn,
                InlineKeyboardButton("🔄 Refresh Menu", callback_data="cb_menu"),
            ],
            [
                InlineKeyboardButton("🛑 EMERGENCY CLOSE ALL", callback_data="cb_confirm_closeall"),
            ],
        ]
        return InlineKeyboardMarkup(keyboard)

    # ── Command & Callback Handlers ──────────────────────────────────────

    async def _handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start or /menu command."""
        if not self.authorized_ids:
            sender_id = update.effective_chat.id if update.effective_chat else (update.effective_user.id if update.effective_user else "unknown")
            if update.effective_message:
                await update.effective_message.reply_text(
                    f"⚠️ <b>TELEGRAM BOT SETUP REQUIRED</b>\n\n"
                    f"Your Telegram ID is: <code>{sender_id}</code>\n\n"
                    f"To authorize this account, add this to your <code>config/.env</code> file:\n"
                    f"<code>TELEGRAM_CHAT_ID={sender_id}</code>\n\n"
                    f"Then restart the bot to activate remote control.",
                    parse_mode="HTML"
                )
            return

        if not self._is_authorized(update):
            if update.effective_message:
                await update.effective_message.reply_text(
                    "⛔ <b>Access Denied</b>\nThis bot is private and restricted to authorized operators.",
                    parse_mode="HTML"
                )
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
        await self._safe_edit_or_reply(
            update,
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
        else:
            from core.mt5_connector import MT5Connector
            mt5_obj = MT5Connector()

        is_conn = mt5_obj.is_connected() if callable(getattr(mt5_obj, "is_connected", None)) else getattr(mt5_obj, "is_connected", False)
        if not is_conn and hasattr(mt5_obj, "connect"):
            is_conn = mt5_obj.connect(max_retries=1, retry_delay=0.1)
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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /positions command or button."""
        if not self._is_authorized(update):
            return

        positions = []
        pending = []
        is_conn = False
        if self.bot_instance and hasattr(self.bot_instance, "mt5"):
            mt5_obj = self.bot_instance.mt5
        else:
            from core.mt5_connector import MT5Connector
            mt5_obj = MT5Connector()

        is_conn = mt5_obj.is_connected() if callable(getattr(mt5_obj, "is_connected", None)) else getattr(mt5_obj, "is_connected", False)
        if not is_conn and hasattr(mt5_obj, "connect"):
            is_conn = mt5_obj.connect(max_retries=1, retry_delay=0.1)
        if is_conn:
            positions = mt5_obj.get_open_positions(self.settings.symbol, auto_reconnect=False)
            if hasattr(mt5_obj, "get_pending_orders"):
                pending = mt5_obj.get_pending_orders(self.settings.symbol, auto_reconnect=False)

        keyboard_rows = []

        if not is_conn:
            msg = (
                f"📈 <b>OPEN POSITIONS</b>\n"
                f"{'━' * 25}\n\n"
                f"⚠️ <i>MT5 Terminal is currently Offline.</i>\n\n"
                f"Cannot query live positions. Please ensure MetaTrader 5 is launched on your desktop with your Exness account logged in."
            )
        elif not positions and not pending:
            msg = (
                f"📈 <b>OPEN POSITIONS & ORDERS</b>\n"
                f"{'━' * 25}\n\n"
                f"<i>No open positions or pending orders active on {self.settings.symbol}.</i>\n"
                f"The bot is scanning market regimes and waiting for high-confluence entry signals."
            )
        else:
            msg = ""
            if positions:
                msg += f"📈 <b>OPEN POSITIONS ({len(positions)})</b>\n{'━' * 25}\n\n"
                for pos in positions:
                    ticket = pos.get("ticket")
                    direction = pos.get("type", "BUY")
                    volume = pos.get("volume", 0.0)
                    entry = pos.get("price_open", pos.get("open_price", 0.0))
                    current = pos.get("price_current", pos.get("current_price", 0.0))
                    profit = pos.get("profit", 0.0)
                    p_emoji = "🟢" if profit >= 0 else "🔴"
                    dir_emoji = "📈" if direction == "BUY" else "📉"

                    msg += (
                        f"{dir_emoji} <b>Ticket #{ticket}</b> | {direction} {volume} lots\n"
                        f"   • Entry: <code>${entry:,.2f}</code> → Now: <code>${current:,.2f}</code>\n"
                        f"   • P&L: {p_emoji} <code>${profit:+,.2f}</code>\n"
                        f"   • SL: <code>${pos.get('sl', 0.0):,.2f}</code> | TP: <code>${pos.get('tp', 0.0):,.2f}</code>\n\n"
                    )
                    keyboard_rows.append([
                        InlineKeyboardButton(f"❌ Close #{ticket} (${profit:+,.1f})", callback_data=f"cb_close_{ticket}")
                    ])

            if pending:
                msg += f"📌 <b>SCHEDULED PENDING ORDERS ({len(pending)})</b>\n{'━' * 25}\n\n"
                for o in pending:
                    ticket = o.get("ticket")
                    direction = o.get("type", "LIMIT")
                    volume = o.get("volume", 0.01)
                    target_p = o.get("price", 0.0)
                    sl = o.get("sl", 0.0)
                    tp = o.get("tp", 0.0)
                    msg += (
                        f"⏳ <b>Order #{ticket}</b> | {direction} {volume} lots\n"
                        f"   • Trigger Price: <code>${target_p:,.2f}</code>\n"
                        f"   • SL: <code>${sl:,.2f}</code> | TP: <code>${tp:,.2f}</code>\n\n"
                    )
                    keyboard_rows.append([
                        InlineKeyboardButton(f"🗑️ Cancel Order #{ticket}", callback_data=f"cb_cancel_{ticket}")
                    ])

        keyboard_rows.append([
            InlineKeyboardButton("🔄 Refresh Positions", callback_data="cb_positions"),
            InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu"),
        ])

        reply_markup = InlineKeyboardMarkup(keyboard_rows)
        await self._safe_edit_or_reply(update, text=msg, reply_markup=reply_markup, parse_mode="HTML")

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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_news(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /news command or button."""
        if not self._is_authorized(update):
            return

        sentiment_score = crud.get_recent_sentiment(hours=24)
        sent_emoji = "📈 BULLISH" if sentiment_score > 0.1 else ("📉 BEARISH" if sentiment_score < -0.1 else "➡️ NEUTRAL")

        msg = (
            f"📰 <b>MARKET NEWS & AI SENTIMENT</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>Composite 24H Sentiment:</b> {sent_emoji} (<code>{sentiment_score:+.2f}</code>)\n"
            f"<b>AI Engine:</b> Gemini 3.6 Flash + Bullion Sentiment\n\n"
        )

        # Pull top distinct news events from DB
        session = crud.get_session()
        try:
            from database.models import NewsEvent
            from news.news_utils import normalize_headline
            events = session.query(NewsEvent).order_by(NewsEvent.id.desc()).limit(20).all()
            unique_events = []
            seen_headlines = set()
            for ev in events:
                norm = normalize_headline(ev.headline)
                if norm not in seen_headlines:
                    seen_headlines.add(norm)
                    unique_events.append(ev)
                if len(unique_events) >= 4:
                    break

            if unique_events:
                msg += "<b>Latest Macro Analysis:</b>\n"
                for ev in unique_events:
                    impact_emoji = "🔴" if ev.impact_level == "HIGH" else ("🟡" if ev.impact_level == "MEDIUM" else "🟢")
                    msg += (
                        f"{impact_emoji} <b>{ev.headline[:75]}...</b>\n"
                        f"   Sentiment: <b>{ev.sentiment}</b> (<code>{ev.sentiment_score:+.2f}</code>) | Source: <i>{ev.source}</i>\n"
                    )
                    if ev.gemini_analysis:
                        clean_note = ev.gemini_analysis[:110].replace("<", "&lt;").replace(">", "&gt;")
                        msg += f"   <i>AI Note:</i> {clean_note}...\n\n"
                    else:
                        msg += "\n"
            else:
                msg += "<i>No news cached yet. Tap '⚡ Fetch Fresh News' below to load live articles instantly.</i>\n"
        finally:
            session.close()

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⚡ Fetch Fresh News Now", callback_data="cb_fetch_fresh_news")],
            [InlineKeyboardButton("🔄 Refresh View", callback_data="cb_news")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_fetch_fresh_news(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fetch live news from Finnhub & Alpha Vantage on-demand and update message."""
        if not self._is_authorized(update):
            return

        loading_msg = "⏳ <i>Fetching & analyzing latest market news from Finnhub and Alpha Vantage...</i>"
        await self._safe_edit_or_reply(update, text=loading_msg, parse_mode="HTML")

        try:
            from news.news_fetcher import NewsFetcher
            from news.news_analyzer import NewsAnalyzer

            fetcher = NewsFetcher()
            analyzer = NewsAnalyzer()
            articles = await fetcher.fetch_all_news()

            for article in articles[:5]:
                headline = article.get("headline", "")
                url = article.get("url", "")
                if crud.is_news_already_saved(headline, url):
                    continue
                analysis = await analyzer.analyze_article(article)
                crud.save_news_event(
                    source=article.get("source", ""),
                    headline=headline,
                    summary=article.get("summary", ""),
                    url=url,
                    sentiment=analysis["sentiment"],
                    sentiment_score=analysis["combined_score"],
                    finbert_score=analysis["finbert"]["score"],
                    gemini_score=analysis.get("gemini", {}).get("score", 0),
                    gemini_analysis=analysis.get("gemini", {}).get("analysis", ""),
                    impact_level=analysis["impact_level"],
                    published_at=article.get("published_at"),
                )
        except Exception as e:
            logger.error(f"On-demand news fetch failed: {e}")

        # Render updated news
        await self._handle_news(update, context)

    async def _handle_regime(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /regime command or button with real-time on-demand calculation."""
        if not self._is_authorized(update):
            return

        msg = (
            f"🧠 <b>MARKET REGIME & ACTIVE STRATEGIES</b>\n"
            f"{'━' * 28}\n\n"
        )

        regime = None
        if self.bot_instance and hasattr(self.bot_instance, "_last_regime"):
            regime = getattr(self.bot_instance, "_last_regime", None)

        if not regime:
            # Dynamic on-demand regime computation via MT5 H4 candles
            try:
                from core.mt5_connector import MT5Connector
                from strategies.regime_detector import RegimeDetector
                from analysis.technical import TechnicalAnalyzer

                mt5_obj = getattr(self.bot_instance, "mt5", None)
                if not mt5_obj:
                    mt5_obj = MT5Connector()

                if mt5_obj.connect(max_retries=1, retry_delay=0.1):
                    df_h4 = mt5_obj.get_rates(timeframe="H4", count=200, auto_reconnect=False)
                    if df_h4 is not None and not df_h4.empty:
                        ta = TechnicalAnalyzer()
                        df_analyzed = ta.add_all_indicators(df_h4.copy())
                        rd = RegimeDetector()
                        regime = rd.analyze(df_analyzed)
                        if self.bot_instance:
                            setattr(self.bot_instance, "_last_regime", regime)
            except Exception as e:
                logger.warning(f"On-demand regime analysis failed: {e}")

        if regime:
            regime_emoji = "📈" if "BULL" in regime.regime.value else ("📉" if "BEAR" in regime.regime.value else "🔄")
            msg += (
                f"<b>Current Regime:</b> {regime_emoji} <code>{regime.regime.value}</code>\n"
                f"<b>Trend Strength (ADX):</b> <code>{regime.adx_value:.1f}</code>\n"
                f"<b>Volatility Percentile:</b> <code>{regime.volatility_percentile:.1f}% ({regime.volatility_label})</code>\n"
                f"<b>Position Sizing Modifier:</b> <code>{regime.position_size_modifier:.2f}x</code>\n"
                f"<b>Trading Allowed:</b> {'✅ YES' if regime.should_trade else '⏸️ PAUSED'}\n\n"
                f"<b>Active Recommended Strategies:</b>\n"
            )
            for s in regime.recommended_strategies:
                msg += f"   • <code>{s.upper()}</code>\n"

            # Temporal Self-Attention metrics (MetaQuotes Book Ch. 5)
            if self.bot_instance and hasattr(self.bot_instance, "attention_scorer"):
                try:
                    mt5_obj = getattr(self.bot_instance, "mt5", None)
                    if mt5_obj and mt5_obj.is_connected:
                        df_m15 = mt5_obj.get_rates(timeframe="M15", count=25, auto_reconnect=False)
                        if df_m15 is not None and len(df_m15) >= 20:
                            att_prof = self.bot_instance.attention_scorer.compute_attention(df_m15)
                            conc = att_prof.get("concentration", 0.0)
                            anchor = att_prof.get("anchor_type", "PIVOT")
                            msg += (
                                f"\n🧠 <b>Temporal Self-Attention:</b>\n"
                                f"   • Focus Concentration: <code>{conc:.1f}%</code>\n"
                                f"   • Structural Anchor: <code>{anchor}</code>\n"
                            )
                except Exception:
                    pass
        else:
            msg += "<i>MT5 offline or H4 candle data unavailable. Ensure MT5 is running on your desktop.</i>\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Regime", callback_data="cb_regime")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_learning(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /learning command or callback button."""
        if not self._is_authorized(update):
            return

        try:
            from ai.trade_learner import trade_learner
            metrics = trade_learner.get_learning_metrics()
        except Exception as e:
            logger.error(f"Error getting learning metrics: {e}")
            metrics = {}

        mults = metrics.get("strategy_multipliers", {})
        scalp = mults.get("scalping", 1.0)
        day = mults.get("day_trading", 1.0)
        swing = mults.get("swing_trading", 1.0)

        weights = metrics.get("adaptive_weights", {})
        tech = weights.get("technical", 40.0)
        ai = weights.get("ai_prediction", 25.0)
        sent = weights.get("sentiment", 20.0)
        reg = weights.get("regime", 15.0)

        memorized_count = metrics.get("active_mistakes_memorized", 0)
        recent_lessons = metrics.get("recent_lessons", [])

        msg = (
            f"🎓 <b>AUTONOMOUS SELF-LEARNING & ADAPTATION</b>\n"
            f"{'━' * 28}\n\n"
            f"<b>Adaptive Strategy Multipliers:</b>\n"
            f"  • <b>Scalping:</b> <code>{scalp:.2f}x</code> {'(✅ Conviction Boost)' if scalp > 1.0 else ('(⚠️ Cautious Sizing)' if scalp < 1.0 else '')}\n"
            f"  • <b>Day Trading:</b> <code>{day:.2f}x</code> {'(✅ Conviction Boost)' if day > 1.0 else ('(⚠️ Cautious Sizing)' if day < 1.0 else '')}\n"
            f"  • <b>Swing:</b> <code>{swing:.2f}x</code>\n\n"
            f"<b>Dynamic Confluence Distribution:</b>\n"
            f"  • 📊 Technical: <code>{tech:.1f}%</code>\n"
            f"  • 🤖 AI Model: <code>{ai:.1f}%</code>\n"
            f"  • 📰 News Sentiment: <code>{sent:.1f}%</code>\n"
            f"  • 🧠 Market Regime: <code>{reg:.1f}%</code>\n\n"
            f"<b>Mistake Memory Guard:</b>\n"
            f"  • <b>Active Guarded Traps:</b> <code>{memorized_count}</code>\n"
        )

        if recent_lessons:
            latest = recent_lessons[0]
            cat = latest.get("category", "LESSON")
            rule = latest.get("rule", latest.get("summary", "Keep risk contained."))
            msg += f"  • <b>Latest Learned Rule ({cat}):</b>\n    <i>\"{rule}\"</i>\n"
        else:
            msg += "  • <i>Mistake Memory Guard active — monitoring all trade closes.</i>\n"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Refresh Learning", callback_data="cb_learning")],
            [InlineKeyboardButton("🔙 Back to Main Menu", callback_data="cb_menu")],
        ])

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_confirm_closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Prompt confirmation for emergency close all."""
        if not self._is_authorized(update):
            return

        mt5_obj = getattr(self.bot_instance, "mt5", None)
        is_conn = False
        if mt5_obj:
            is_conn = mt5_obj.is_connected() or mt5_obj.connect(max_retries=1, retry_delay=0.1)

        if not is_conn:
            msg = (
                f"⚠️ <b>CANNOT CLOSE POSITIONS — MT5 OFFLINE</b>\n\n"
                f"MetaTrader 5 terminal is not running or connected.\n"
                f"Please start your MetaTrader 5 terminal first."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Status", callback_data="cb_status")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
            ])
            await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")
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

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_do_closeall(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute emergency close all positions."""
        if not self._is_authorized(update):
            return

        mt5_obj = getattr(self.bot_instance, "mt5", None)
        is_conn = False
        if mt5_obj:
            is_conn = mt5_obj.is_connected() or mt5_obj.connect(max_retries=1, retry_delay=0.1)

        if not is_conn:
            msg = (
                f"⚠️ <b>CANNOT CLOSE POSITIONS — MT5 OFFLINE</b>\n\n"
                f"MetaTrader 5 terminal is not running or connected.\n"
                f"Please launch MetaTrader 5 on your desktop and verify your Exness login."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 View Status", callback_data="cb_status")],
                [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
            ])
            await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")
            return

        closed_count = 0
        if self.bot_instance and hasattr(self.bot_instance, "trade_executor"):
            te = self.bot_instance.trade_executor
            if hasattr(te, "close_all_positions"):
                closed_count = te.close_all_positions(self.settings.symbol)
            elif mt5_obj:
                closed_count = mt5_obj.close_all_positions(self.settings.symbol)
        elif mt5_obj:
            closed_count = mt5_obj.close_all_positions(self.settings.symbol)

        if closed_count > 0:
            msg = (
                f"🛑 <b>ALL POSITIONS CLOSED</b>\n\n"
                f"Successfully closed <b>{closed_count}</b> open position(s).\n"
                f"All active trades have been flattened."
            )
        else:
            msg = (
                f"ℹ️ <b>NO OPEN POSITIONS</b>\n\n"
                f"There were no active positions open to close."
            )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 View Status", callback_data="cb_status")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])

        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

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
        else:
            from core.mt5_connector import MT5Connector
            mt5_obj = MT5Connector()
            success = mt5_obj.close_position(ticket, comment="telegram_manual")

        if success:
            msg = f"✅ Position <b>#{ticket}</b> closed successfully."
        else:
            msg = f"❌ Failed to close position <b>#{ticket}</b>. Check MT5 connection."

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 View Positions", callback_data="cb_positions")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])
        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

    async def _handle_cancel_single(self, update: Update, ticket: int):
        """Cancel a specific pending order by ticket number."""
        if not self._is_authorized(update):
            return

        success = False
        if self.bot_instance and hasattr(self.bot_instance, "mt5"):
            success = self.bot_instance.mt5.cancel_order(ticket)
        else:
            from core.mt5_connector import MT5Connector
            mt5_obj = MT5Connector()
            success = mt5_obj.cancel_order(ticket)

        if success:
            msg = f"🗑️ Scheduled Pending Order <b>#{ticket}</b> canceled successfully."
        else:
            msg = f"❌ Failed to cancel Order <b>#{ticket}</b>. It may have already triggered or expired."

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 View Positions & Orders", callback_data="cb_positions")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="cb_menu")],
        ])
        await self._safe_edit_or_reply(update, text=msg, reply_markup=keyboard, parse_mode="HTML")

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
        """Route callback queries from inline buttons with gatekeeper authorization check."""
        query = update.callback_query
        if not query:
            return

        if not self._is_authorized(update):
            try:
                await query.answer("⛔ Unauthorized: You are not authorized to control this bot.", show_alert=True)
            except Exception:
                pass
            return

        try:
            await query.answer()
        except Exception:
            pass

        data = query.data
        try:
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
            elif data == "cb_fetch_fresh_news":
                await self._handle_fetch_fresh_news(update, context)
            elif data == "cb_regime":
                await self._handle_regime(update, context)
            elif data == "cb_learning":
                await self._handle_learning(update, context)
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
            elif data.startswith("cb_cancel_"):
                ticket = int(data.split("_")[-1])
                await self._handle_cancel_single(update, ticket)
        except Exception as e:
            logger.error(f"Callback error for {data}: {e}")
            try:
                if query.message:
                    await query.message.reply_text(f"⚠️ Operation error: {e}")
            except Exception:
                pass

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
            self._app.add_handler(CommandHandler("learning", self._handle_learning))
            self._app.add_handler(CommandHandler("price", self._handle_price))
            self._app.add_handler(CommandHandler("pause", self._handle_pause))
            self._app.add_handler(CommandHandler("resume", self._handle_resume))
            self._app.add_handler(CommandHandler("closeall", self._handle_confirm_closeall))
            self._app.add_handler(CommandHandler("setlot", self._handle_set_lot))
            self._app.add_handler(CommandHandler("setrisk", self._handle_set_risk))
            self._app.add_handler(CommandHandler("help", self._handle_help))

            # Register callback button router
            self._app.add_handler(CallbackQueryHandler(self._callback_router))

            # Register error handler for network/conflict issues
            async def _on_telegram_error(update: object, context: ContextTypes.DEFAULT_TYPE):
                err = context.error
                err_msg = str(err)
                if "Conflict" in type(err).__name__ or "terminated by other getUpdates" in err_msg:
                    logger.warning(
                        "⚠️ Telegram Conflict: Another bot instance is currently active on Telegram. "
                        "Trading alerts will still be sent, but interactive chat commands are handled by the other instance."
                    )
                else:
                    logger.error(f"Telegram error: {err}")

            self._app.add_error_handler(_on_telegram_error)

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
            err_msg = str(e)
            if self.bot_token:
                err_msg = err_msg.replace(self.bot_token, "***BOT_TOKEN***")
            logger.error(f"Telegram send error: {err_msg}")

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
        ticket: int | dict,
        direction: str = "",
        profit: float = 0.0,
        entry: float = 0.0,
        exit_price: float = 0.0,
        duration_min: int = 0,
        reason: str = "TP/SL",
    ):
        """Send trade close notification."""
        if isinstance(ticket, dict):
            d = ticket
            ticket = d.get("ticket", 0)
            direction = d.get("direction", "")
            profit = d.get("profit", 0.0)
            entry = d.get("entry_price", d.get("entry", 0.0))
            exit_price = d.get("exit_price", d.get("close_price", 0.0))
            duration_min = d.get("duration_minutes", d.get("duration_min", 0))
            reason = d.get("reason", "TP/SL")

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
        """Send high-impact news alert with strict deduplication."""
        from news.news_utils import compute_news_hash
        h_hash = compute_news_hash(headline)
        if h_hash in self._sent_news_alert_hashes:
            logger.info(f"Skipping duplicate Telegram news alert for: {headline[:60]}")
            return
        self._sent_news_alert_hashes.add(h_hash)

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
        app.add_handler(CommandHandler("learning", self._handle_learning))
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
                from telegram import BotCommand
                cmds = [
                    BotCommand("start", "Command Center & Main Menu"),
                    BotCommand("status", "Account Balance, Equity & Health"),
                    BotCommand("positions", "Open Positions & Pending Orders"),
                    BotCommand("learning", "Autonomous Self-Learning Metrics"),
                    BotCommand("news", "Macro News & Gemini Sentiment"),
                    BotCommand("regime", "Market Regime & Active Strategies"),
                    BotCommand("price", "Live Gold Price & Spread"),
                    BotCommand("trades", "Recent Trade History"),
                    BotCommand("pnl", "Daily & Monthly P&L Stats"),
                    BotCommand("pause", "Pause Automatic Order Execution"),
                    BotCommand("resume", "Resume Automatic Order Execution"),
                    BotCommand("closeall", "Emergency Close All Positions"),
                ]
                await application.bot.set_my_commands(cmds)
                logger.info("⚡ Registered native Telegram Menu commands via set_my_commands")
            except Exception as e:
                logger.warning(f"Could not set menu commands: {e}")
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
