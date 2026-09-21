"""
Main Bot Orchestrator

The central event loop that coordinates all components:
Data → Analysis → Strategy → AI → Sentiment → Confluence → Execution
"""

import asyncio
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from analysis.sentiment import SentimentAggregator
from analysis.technical import TechnicalAnalyzer
from ai.price_predictor import PricePredictor
from ai.signal_classifier import SignalClassifier
from config.settings import get_settings, LOGS_DIR
from core.mt5_connector import MT5Connector
from database import crud
from database.models import init_database
from execution.risk_manager import RiskManager
from execution.trade_executor import TradeExecutor
from execution.trailing_stop import TrailingStopManager
from news.news_fetcher import NewsFetcher
from news.news_analyzer import NewsAnalyzer
from strategies.day_trading import DayTradingStrategy
from strategies.regime_detector import RegimeDetector
from strategies.scalping import ScalpingStrategy
from strategies.signal_aggregator import SignalAggregator
from strategies.swing_trading import SwingTradingStrategy
from notifications.telegram_bot import TelegramNotifier


class TradingBot:
    """
    Main trading bot orchestrator.

    Manages the trading loop:
    1. Fetch market data from MT5
    2. Analyze with technical indicators
    3. Detect market regime
    4. Run active strategies based on regime
    5. Get AI predictions
    6. Check news sentiment
    7. Calculate confluence score
    8. Execute trade if conditions are met
    9. Manage trailing stops
    10. Repeat
    """

    def __init__(self):
        self.settings = get_settings()
        self._running = False
        self._shutdown_event = asyncio.Event()

        # ── Core Components ──────────────────────────────────────────────
        self.mt5 = MT5Connector()
        self.risk_manager = RiskManager(self.mt5)
        self.trade_executor = TradeExecutor(self.mt5, self.risk_manager)
        self.trailing_stop = TrailingStopManager(self.mt5)

        # ── Analysis ─────────────────────────────────────────────────────
        self.technical = TechnicalAnalyzer()
        self.regime_detector = RegimeDetector()
        self.signal_aggregator = SignalAggregator()
        self.sentiment_aggregator = SentimentAggregator()

        # ── Strategies ───────────────────────────────────────────────────
        self.strategies = {
            "scalping": ScalpingStrategy(),
            "day_trading": DayTradingStrategy(),
            "swing_trading": SwingTradingStrategy(),
        }

        # ── AI ───────────────────────────────────────────────────────────
        self.price_predictor = PricePredictor()
        self.signal_classifier = SignalClassifier()

        # ── News ─────────────────────────────────────────────────────────
        self.news_fetcher = NewsFetcher()
        self.news_analyzer = NewsAnalyzer()

        # ── Notifications ────────────────────────────────────────────────
        self.telegram = TelegramNotifier(bot_instance=self)

        # ── State ────────────────────────────────────────────────────────
        self._cycle_count = 0
        self._last_news_check: Optional[datetime] = None
        self._last_regime = None
        self._trading_paused = False

    def _setup_logging(self):
        """Configure loguru logging."""
        logger.remove()  # Remove default handler

        # Console output
        logger.add(
            sys.stdout,
            format=(
                "<green>{time:HH:mm:ss}</green> | "
                "<level>{level: <8}</level> | "
                "<cyan>{name}</cyan>:<cyan>{function}</cyan> | "
                "<level>{message}</level>"
            ),
            level=self.settings.log_level,
            colorize=True,
        )

        # File output (rotated daily)
        logger.add(
            str(LOGS_DIR / "bot_{time:YYYY-MM-DD}.log"),
            rotation="1 day",
            retention="30 days",
            level="DEBUG",
            format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} | {message}",
        )

    async def start(self):
        """Start the trading bot."""
        self._setup_logging()

        logger.info("=" * 60)
        logger.info("  XAUUSD AI Trading Bot — Starting Up")
        logger.info("=" * 60)

        # Initialize database
        init_database()

        # Connect to MT5
        if not self.mt5.connect():
            logger.critical("Failed to connect to MT5 — aborting")
            return

        # Load AI models
        self.price_predictor.load_model()
        self.signal_classifier.load_model()

        # Display account info
        account = self.mt5.get_account_info()
        if account:
            logger.info(
                f"Account: {account['login']} | "
                f"Balance: ${account['balance']:,.2f} | "
                f"Equity: ${account['equity']:,.2f} | "
                f"Leverage: 1:{account['leverage']}"
            )

        if self.settings.demo_mode:
            logger.warning("⚠️ DEMO MODE — Trades will execute on demo account")

        # Send startup notification via Telegram
        mode = "DEMO" if self.settings.demo_mode else "LIVE"
        balance_str = f"${account['balance']:,.2f}" if account else "N/A"
        await self.telegram.send_bot_status(
            "RUNNING",
            f"Mode: {mode}\nBalance: {balance_str}\nSymbol: XAUUSD"
        )

        # Start interactive 2-way Telegram polling in background
        await self.telegram.start_polling()

        # Register shutdown handlers
        self._running = True

        # Start main loop
        try:
            await self._main_loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.critical(f"Bot crashed: {e}")
            raise
        finally:
            await self.stop()

    async def stop(self):
        """Gracefully stop the bot."""
        logger.info("Shutting down...")
        self._running = False
        await self.telegram.stop_polling()
        self.mt5.disconnect()
        logger.info("Bot stopped successfully")

    async def _main_loop(self):
        """Main trading loop."""
        # Determine loop intervals based on active strategies
        loop_interval = 30  # seconds (check every 30s)

        logger.info(f"Main loop started | Check interval: {loop_interval}s")

        while self._running:
            try:
                self._cycle_count += 1
                cycle_start = time.time()

                # ── Step 1: Ensure MT5 connection ────────────────────────
                if not self.mt5.ensure_connected():
                    logger.warning("MT5 disconnected — waiting for reconnect...")
                    await asyncio.sleep(10)
                    continue

                # ── Step 2: Fetch market data ────────────────────────────
                # Get data for multiple timeframes
                df_m5 = self.mt5.get_rates(timeframe="M5", count=500)
                df_h1 = self.mt5.get_rates(timeframe="H1", count=500)
                df_h4 = self.mt5.get_rates(timeframe="H4", count=500)
                df_d1 = self.mt5.get_rates(timeframe="D1", count=500)

                if df_h1 is None:
                    logger.warning("Failed to fetch H1 data — skipping cycle")
                    await asyncio.sleep(loop_interval)
                    continue

                # ── Step 3: Detect market regime ─────────────────────────
                df_h4_analyzed = self.technical.add_all_indicators(df_h4.copy()) if df_h4 is not None else None
                if df_h4_analyzed is not None:
                    regime = self.regime_detector.analyze(df_h4_analyzed)
                    self._last_regime = regime
                else:
                    regime = None

                # ── Step 4: Get AI predictions ───────────────────────────
                ai_prediction = self.signal_classifier.predict(df_h1)

                # ── Step 5: Check news (every N minutes) ─────────────────
                if self.news_fetcher.should_fetch():
                    await self._process_news()

                sentiment = self.sentiment_aggregator.get_signal()

                # ── Step 6: Run active strategies ────────────────────────
                best_signal = None
                best_confluence = None

                # Skip strategy execution if paused via Telegram remote control
                if getattr(self, "_trading_paused", False):
                    best_signal = None
                else:
                    for strategy_name, strategy in self.strategies.items():
                    if not strategy.enabled:
                        continue

                    # Check if regime recommends this strategy
                    if regime and not self.regime_detector.is_strategy_recommended(
                        strategy_name, regime
                    ):
                        continue

                    # Select appropriate dataframe for the strategy
                    if strategy_name == "scalping" and df_m5 is not None:
                        df = df_m5.copy()
                    elif strategy_name == "day_trading":
                        df = df_h1.copy()
                    elif strategy_name == "swing_trading" and df_h4 is not None:
                        df = df_h4.copy()
                    else:
                        continue

                    # Run strategy
                    signal = strategy.run(df)

                    if not signal.is_actionable:
                        continue

                    # Calculate confluence
                    confluence = self.signal_aggregator.calculate_confluence(
                        strategy_signal=signal,
                        ai_prediction=ai_prediction,
                        sentiment=sentiment,
                        regime_analysis={
                            "is_recommended": True,
                            "position_modifier": regime.position_size_modifier if regime else 1.0,
                        },
                        min_score=strategy.min_confluence_score,
                    )

                    # Keep the best signal
                    if confluence.should_execute:
                        if best_confluence is None or confluence.total_score > best_confluence.total_score:
                            best_signal = signal
                            best_confluence = confluence

                # ── Step 7: Execute if conditions met ────────────────────
                if best_signal and best_confluence and best_confluence.should_execute:
                    result = self.trade_executor.execute_signal(
                        signal=best_signal,
                        confluence_score=best_confluence.total_score,
                        sentiment_score=sentiment.get("score", 0) if sentiment else 0,
                        ai_prediction=ai_prediction.get("direction", ""),
                        ai_confidence=ai_prediction.get("confidence", 0),
                        regime=regime.regime.value if regime else "",
                        risk_modifier=regime.position_size_modifier if regime else 1.0,
                    )

                    if result:
                        logger.success(f"🎯 Trade opened: {result}")
                        # Send Telegram notification
                        await self.telegram.send_trade_opened(result)

                # ── Step 8: Manage trailing stops ────────────────────────
                if df_h1 is not None and "atr" not in df_h1.columns:
                    df_h1 = self.technical.add_atr(df_h1)
                current_atr = float(df_h1["atr"].iloc[-1]) if df_h1 is not None and "atr" in df_h1.columns else 2.0
                self.trailing_stop.update_all_positions(current_atr)

                # ── Step 9: Sync positions ───────────────────────────────
                self.trade_executor.sync_positions()

                # ── Step 10: Performance snapshot (every 100 cycles) ─────
                if self._cycle_count % 100 == 0:
                    await self._save_performance_snapshot()

                # ── Timing ───────────────────────────────────────────────
                elapsed = time.time() - cycle_start
                sleep_time = max(0, loop_interval - elapsed)

                if self._cycle_count % 10 == 0:
                    logger.debug(
                        f"Cycle #{self._cycle_count} complete in {elapsed:.2f}s | "
                        f"Regime: {regime.regime.value if regime else 'N/A'} | "
                        f"Sentiment: {sentiment.get('direction', 'N/A') if sentiment else 'N/A'}"
                    )

                await asyncio.sleep(sleep_time)

            except Exception as e:
                logger.error(f"Error in main loop cycle #{self._cycle_count}: {e}")
                await asyncio.sleep(loop_interval)

    async def _process_news(self):
        """Fetch and analyze news."""
        try:
            articles = await self.news_fetcher.fetch_all_news()

            for article in articles[:10]:  # Process top 10 most recent
                analysis = await self.news_analyzer.analyze_article(article)

                # Add to sentiment aggregator
                self.sentiment_aggregator.add_sentiment(
                    score=analysis["combined_score"],
                    impact_level=analysis["impact_level"],
                    published_at=article.get("published_at"),
                )

                # Save to database
                crud.save_news_event(
                    source=article.get("source", ""),
                    headline=article.get("headline", ""),
                    summary=article.get("summary", ""),
                    url=article.get("url", ""),
                    sentiment=analysis["sentiment"],
                    sentiment_score=analysis["combined_score"],
                    finbert_score=analysis["finbert"]["score"],
                    gemini_score=analysis.get("gemini", {}).get("score", 0),
                    gemini_analysis=analysis.get("gemini", {}).get("analysis", ""),
                    impact_level=analysis["impact_level"],
                    published_at=article.get("published_at"),
                )

                # Pause trading for HIGH impact news
                if analysis["impact_level"] == "HIGH":
                    logger.warning(
                        f"⚠️ HIGH IMPACT NEWS: {article['headline'][:80]}"
                    )
                    self.regime_detector.set_news_pause(True)

                    # Notify via Telegram
                    await self.telegram.send_news_alert(
                        headline=article.get("headline", ""),
                        sentiment=analysis["sentiment"],
                        impact=analysis["impact_level"],
                        score=analysis["combined_score"],
                    )

                    # Schedule resume after pause period
                    pause_minutes = self.settings.news_params.get("high_impact_pause_minutes", 30)
                    asyncio.get_event_loop().call_later(
                        pause_minutes * 60,
                        lambda: self.regime_detector.set_news_pause(False),
                    )

        except Exception as e:
            logger.error(f"News processing error: {e}")

    async def _save_performance_snapshot(self):
        """Save periodic performance metrics."""
        try:
            account = self.mt5.get_account_info()
            if not account:
                return

            stats = crud.get_trade_stats(days=30)
            daily_pnl = crud.get_daily_pnl()

            crud.save_performance_snapshot(
                balance=account["balance"],
                equity=account["equity"],
                daily_pnl=daily_pnl,
                total_pnl=account["profit"],
                total_trades=stats["total_trades"],
                winning_trades=stats["winning_trades"],
                losing_trades=stats["losing_trades"],
                win_rate=stats["win_rate"],
                profit_factor=stats["profit_factor"],
            )

        except Exception as e:
            logger.error(f"Performance snapshot error: {e}")
