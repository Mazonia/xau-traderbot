"""
XAUUSD Last Week Real Historical Backtest Runner

Fetches real historical M5/H1/H4 data from MT5 for the past week
and runs the complete V2 multi-timeframe backtest engine.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone
import MetaTrader5 as mt5
import pandas as pd
from loguru import logger

from backtesting.backtester import Backtester


def run_last_week_backtest():
    print("=" * 70)
    print("   XAUUSD REAL HISTORICAL BACKTEST - LAST WEEK'S PRICE ACTION")
    print("=" * 70)

    if not mt5.initialize():
        print("[-] Failed to initialize MT5")
        return

    symbol = "XAUUSD"
    # Select symbol
    mt5.symbol_select(symbol, True)

    # Fetch 500 H1 bars (~3 weeks of data including last week + warmup)
    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 450)
    # Fetch 250 H4 bars for higher-TF trend confirmation
    rates_h4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 250)

    mt5.shutdown()

    if rates_h1 is None or len(rates_h1) < 200:
        print("[-] Insufficient H1 data from MT5")
        return

    df_h1 = pd.DataFrame(rates_h1)
    df_h1["time"] = pd.to_datetime(df_h1["time"], unit="s")

    df_h4 = pd.DataFrame(rates_h4) if rates_h4 is not None else None
    if df_h4 is not None:
        df_h4["time"] = pd.to_datetime(df_h4["time"], unit="s")

    print(f"\n[+] Loaded {len(df_h1)} H1 candles:")
    print(f"    Start Date: {df_h1['time'].iloc[0].strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"    End Date:   {df_h1['time'].iloc[-1].strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"    Price Range: ${df_h1['low'].min():.2f} - ${df_h1['high'].max():.2f}")
    if df_h4 is not None:
        print(f"[+] Loaded {len(df_h4)} H4 candles for macro confirmation")

    print("\n" + "=" * 70)
    print("RUNNING BACKTEST WITH V2 MULTI-TIMEFRAME CONFIRMATION & RESILIENCE")
    print("=" * 70)

    # Initialize Backtester with standard moderate mode settings
    bt = Backtester(
        initial_balance=10_000.0,
        lot_size=0.02,
        spread_points=0.25,
        slippage_points=0.05,
        min_confluence_score=55.0,
        trailing_stop_enabled=True,
    )

    metrics = bt.run(df_h1, higher_tf_df=df_h4, warmup_bars=150)

    return metrics


if __name__ == "__main__":
    run_last_week_backtest()
