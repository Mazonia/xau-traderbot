"""
XAUUSD AI Trading Bot — Entry Point

Usage:
    python main.py              # Start the trading bot
    python main.py --train      # Train AI models first, then start
    python main.py --backtest   # Run backtesting only
    python main.py --dashboard  # Start web dashboard only
"""

import argparse
import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from loguru import logger


def parse_args():
    parser = argparse.ArgumentParser(
        description="XAUUSD AI Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Train AI models before starting the bot",
    )
    parser.add_argument(
        "--train-only",
        action="store_true",
        help="Train AI models and exit without starting the bot",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run backtesting only (no live trading)",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Start web dashboard only (no trading)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Start interactive Telegram Command Center only",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        default=True,
        help="Run in demo mode (default: True)",
    )
    return parser.parse_args()


async def train_models():
    """Train AI models using historical data."""
    from core.mt5_connector import MT5Connector
    from ai.price_predictor import PricePredictor
    from ai.signal_classifier import SignalClassifier

    logger.info("=" * 60)
    logger.info("  Training AI Models")
    logger.info("=" * 60)

    mt5 = MT5Connector()
    if not mt5.connect():
        logger.error("Cannot connect to MT5 for training data")
        return

    try:
        from scripts.train_ai import run_training_pipeline
        run_training_pipeline(timeframe="M15", count=3000)

        # Optional LSTM if TensorFlow is installed
        try:
            import tensorflow
            df = mt5.get_rates(timeframe="H1", count=2000)
            if df is not None:
                lstm = PricePredictor()
                lstm.train(df, epochs=10)
        except Exception:
            pass

        logger.success("✅ AI models trained and ready for live execution")

    finally:
        mt5.disconnect()


def start_dashboard():
    """Start the web dashboard server."""
    import uvicorn
    from config.settings import get_settings

    settings = get_settings()
    logger.info(f"Starting dashboard on http://{settings.dashboard.host}:{settings.dashboard.port}")

    uvicorn.run(
        "dashboard.app:app",
        host=settings.dashboard.host,
        port=settings.dashboard.port,
        reload=False,
    )


def run_telegram():
    """Run interactive Telegram Command Center in standalone mode with native long-polling."""
    from notifications.telegram_bot import TelegramNotifier
    from core.mt5_connector import MT5Connector

    logger.info("=" * 60)
    logger.info("  Starting Telegram Command Center (Standalone Mode)")
    logger.info("=" * 60)

    mt5 = MT5Connector()
    mt5.connect(max_retries=1, retry_delay=1)

    from strategies.regime_detector import RegimeDetector
    from analysis.technical import TechnicalAnalyzer

    class StandaloneBot:
        def __init__(self, mt5_conn):
            self.mt5 = mt5_conn
            self.regime_detector = RegimeDetector()
            self.technical = TechnicalAnalyzer()
            self._last_regime = None
            self._trading_paused = False

    bot_wrapper = StandaloneBot(mt5)
    notifier = TelegramNotifier(bot_instance=bot_wrapper)
    try:
        notifier.run_standalone()
    except KeyboardInterrupt:
        logger.info("Telegram Bot terminated by user")


def run_backtest():
    """Run historical backtesting simulation."""
    from backtesting.backtester import Backtester
    from core.mt5_connector import MT5Connector

    logger.info("=" * 60)
    logger.info("  Starting XAUUSD Multi-Strategy Backtester")
    logger.info("=" * 60)

    bt = Backtester(initial_balance=10_000.0, lot_size=0.02)
    df = None

    # Try fetching real data from MT5 first if available
    try:
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=1):
            logger.info("Fetching real historical H1 data from MT5...")
            df = mt5.get_rates(timeframe="H1", count=2000)
            mt5.disconnect()
    except Exception as e:
        logger.debug(f"MT5 historical data fetch skipped: {e}")

    if df is None or len(df) < 500:
        logger.info("Using high-fidelity synthetic Gold benchmark data (1,500 candles)...")
        df = bt.generate_benchmark_data(bars=1500)

    bt.run(df)


def main():
    args = parse_args()

    if args.dashboard:
        start_dashboard()
        return

    if args.telegram:
        run_telegram()
        return

    if args.backtest:
        run_backtest()
        return

    if args.train_only:
        asyncio.run(train_models())
        return

    if args.train:
        asyncio.run(train_models())

    # Start the live trading bot
    from core.bot import TradingBot

    bot = TradingBot()
    asyncio.run(bot.start())


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot terminated by user")
        sys.exit(0)
