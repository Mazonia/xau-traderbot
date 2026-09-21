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
        # Fetch 6 months of H1 data for training
        df = mt5.get_rates(timeframe="H1", count=5000)

        if df is None or len(df) < 1000:
            logger.error("Insufficient historical data for training")
            return

        logger.info(f"Training data: {len(df)} H1 candles")

        # Train LSTM
        lstm = PricePredictor()
        lstm_result = lstm.train(df, epochs=50)
        logger.info(f"LSTM result: {lstm_result}")

        # Train XGBoost
        xgb = SignalClassifier()
        xgb_result = xgb.train(df)
        logger.info(f"XGBoost result: {xgb_result}")

        logger.success("✅ AI models trained successfully")

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


async def main():
    args = parse_args()

    if args.train:
        await train_models()

    if args.backtest:
        logger.info("Backtesting mode — not yet implemented")
        # TODO: Implement backtesting
        return

    if args.dashboard:
        start_dashboard()
        return

    # Start the trading bot
    from core.bot import TradingBot

    bot = TradingBot()
    await bot.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot terminated by user")
        sys.exit(0)
