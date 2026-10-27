"""
Detailed Backtest & Comparative Audit on Last Week's Real Price Action (XAUUSD)

Compares:
A. The OLD V1 bot (no multi-TF gates, flat regime scores, no volume intensity filter)
B. The NEW V2 hardened bot (H1/H4/D1 multi-TF trend gates, scaled regime conviction, volume confirmation, circuit breaker)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timezone
import MetaTrader5 as mt5
import pandas as pd
from loguru import logger

from analysis.technical import TechnicalAnalyzer
from ai.signal_classifier import SignalClassifier
from strategies.scalping import ScalpingStrategy
from strategies.day_trading import DayTradingStrategy
from strategies.swing_trading import SwingTradingStrategy
from strategies.regime_detector import RegimeDetector
from strategies.signal_aggregator import SignalAggregator
from backtesting.backtester import Backtester


def run_detailed_backtest():
    print("=" * 75)
    print("   XAUUSD REAL HISTORICAL AUDIT & BACKTEST: LAST WEEK'S PRICE ACTION")
    print("=" * 75)

    if not mt5.initialize():
        print("[-] MetaTrader 5 initialization failed.")
        return

    symbol = "XAUUSD"
    mt5.symbol_select(symbol, True)

    # 1. Fetch Real Historical Candles
    # H1 bars: 400 candles covers ~1 month of October up to now
    rates_h1 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H1, 0, 400)
    # H4 bars: 200 candles covers ~2 months for higher-TF trend validation
    rates_h4 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_H4, 0, 200)
    # M5 bars: 1500 candles covers ~1.5 weeks for scalping validation
    rates_m5 = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 1500)

    mt5.shutdown()

    if rates_h1 is None or rates_h4 is None or rates_m5 is None:
        print("[-] Failed to retrieve complete multi-timeframe candles from MT5.")
        return

    df_h1 = pd.DataFrame(rates_h1)
    df_h1["time"] = pd.to_datetime(df_h1["time"], unit="s")
    if "volume" not in df_h1.columns and "tick_volume" in df_h1.columns:
        df_h1["volume"] = df_h1["tick_volume"]

    df_h4 = pd.DataFrame(rates_h4)
    df_h4["time"] = pd.to_datetime(df_h4["time"], unit="s")
    if "volume" not in df_h4.columns and "tick_volume" in df_h4.columns:
        df_h4["volume"] = df_h4["tick_volume"]

    df_m5 = pd.DataFrame(rates_m5)
    df_m5["time"] = pd.to_datetime(df_m5["time"], unit="s")
    if "volume" not in df_m5.columns and "tick_volume" in df_m5.columns:
        df_m5["volume"] = df_m5["tick_volume"]

    print(f"\n[+] Real Historical Market Data Loaded from MT5:")
    print(f"    - M5 Candles: {len(df_m5):,} bars ({df_m5['time'].iloc[0].strftime('%Y-%m-%d')} -> {df_m5['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')})")
    print(f"    - H1 Candles: {len(df_h1):,} bars ({df_h1['time'].iloc[0].strftime('%Y-%m-%d')} -> {df_h1['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')})")
    print(f"    - H4 Candles: {len(df_h4):,} bars ({df_h4['time'].iloc[0].strftime('%Y-%m-%d')} -> {df_h4['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')})")
    print(f"    - Price Span: ${df_h1['low'].min():.2f} - ${df_h1['high'].max():.2f}")

    # Load ML Classifier
    clf = SignalClassifier()
    clf_loaded = clf.load_model()
    print(f"    - XGBoost Classifier v2 Active: {clf_loaded}")

    # ── Simulate Bar-By-Bar Signal Generation on Last Week's Action ──
    # Focus on the last ~120 H1 candles (covers the past 5 trading days: Oct 19 - Oct 24)
    eval_bars = min(120, len(df_h1) - 150)
    start_idx = len(df_h1) - eval_bars

    print("\n" + "=" * 75)
    print(f"EVALUATING SIGNALS ACROSS LAST WEEK ({df_h1['time'].iloc[start_idx].strftime('%Y-%m-%d %H:%M')} to {df_h1['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')} UTC)")
    print("=" * 75)

    ta = TechnicalAnalyzer()
    regime_detector = RegimeDetector()
    aggregator = SignalAggregator()
    day_strat = DayTradingStrategy()

    v1_signals_count = 0
    v2_signals_count = 0
    v2_vetoed_by_htf = 0
    v2_vetoed_by_confluence = 0

    trades_executed = []

    for i in range(start_idx, len(df_h1)):
        sub_h1 = df_h1.iloc[:i + 1]
        current_time = sub_h1["time"].iloc[-1]
        current_price = sub_h1["close"].iloc[-1]

        # Slice H4 data up to current_time
        sub_h4 = df_h4[df_h4["time"] <= current_time]

        # 1. Market Regime
        regime = regime_detector.analyze(sub_h1)

        # 2. AI Prediction
        ai_pred = clf.predict(sub_h1)

        # 3. Day Trading Strategy Signal
        analysis_v2 = day_strat.analyze(sub_h1, higher_tf_df=sub_h4)
        sig_v2 = day_strat.generate_signal(sub_h1, analysis_v2)

        # Legacy V1 analysis (without higher_tf_df)
        analysis_v1 = day_strat.analyze(sub_h1, higher_tf_df=None)
        sig_v1 = day_strat.generate_signal(sub_h1, analysis_v1)

        if sig_v1.is_actionable:
            v1_signals_count += 1

        if sig_v2.is_actionable:
            v2_signals_count += 1
            # Check Confluence
            conf = aggregator.calculate_confluence(
                strategy_signal=sig_v2,
                ai_prediction=ai_pred,
                sentiment={"direction": "NEUTRAL", "score": 0.0},
                regime_analysis={
                    "is_recommended": True,
                    "position_modifier": regime.position_size_modifier,
                    "regime": regime.regime.value if hasattr(regime.regime, "value") else str(regime.regime),
                    "trend_direction": getattr(regime, "trend_direction", "NEUTRAL"),
                    "adx": getattr(regime, "adx_value", 20.0),
                },
                min_score=55.0,
            )

            if conf.should_execute:
                trades_executed.append({
                    "time": current_time,
                    "price": current_price,
                    "direction": sig_v2.direction.value,
                    "confluence": conf.total_score,
                    "stop_loss": sig_v2.stop_loss,
                    "take_profit": sig_v2.take_profit,
                    "reasons": sig_v2.reasons[:2],
                })
            else:
                v2_vetoed_by_confluence += 1
        else:
            # Check if it was vetoed by HTF gate
            if any("HTF GATE" in r for r in sig_v2.reasons):
                v2_vetoed_by_htf += 1

    print(f"\n[+] SIGNAL SCREENING SUMMARY (Past 5 Trading Days):")
    print(f"    - Raw V1 Unfiltered Strategy Signals:         {v1_signals_count:>3} potential entries")
    print(f"    - VETOED by V2 Multi-TF Confirmation Gate:     {v2_vetoed_by_htf:>3} counter-trend traps blocked")
    print(f"    - VETOED by Scaled Confluence Threshold (<55): {v2_vetoed_by_confluence:>3} low-conviction setups blocked")
    print(f"    - High-Assurance V2 Trades Qualified:         {len(trades_executed):>3} entries executed")

    if trades_executed:
        print("\n" + "-" * 75)
        print("QUALIFIED TRADES BREAKDOWN:")
        print("-" * 75)
        for t in trades_executed:
            print(f" * {t['time'].strftime('%Y-%m-%d %H:%M')} | {t['direction']:<4} @ ${t['price']:.2f} | Conf: {t['confluence']:.1f}/100 | SL: ${t['stop_loss']:.2f} | TP: ${t['take_profit']:.2f}")

    # ── Run the Complete Backtest Engine across H1 with H4 macro confirmation ──
    print("\n" + "=" * 75)
    print("SIMULATING H1 PORTFOLIO PERFORMANCE (Day Trading / Swing on Real Candles)")
    print("=" * 75)

    bt_h1 = Backtester(
        initial_balance=10_000.0,
        lot_size=0.02,
        spread_points=0.25,
        slippage_points=0.05,
        min_confluence_score=50.0,
        trailing_stop_enabled=True,
        classifier=clf,
    )
    metrics_h1 = bt_h1.run(df_h1, higher_tf_df=df_h4, warmup_bars=100)

    # ── Run M5 Scalping Backtest with H1 macro confirmation ──
    print("\n" + "=" * 75)
    print("SIMULATING M5 SCALPING PERFORMANCE (High-Frequency Real Candles)")
    print("=" * 75)

    bt_m5 = Backtester(
        initial_balance=10_000.0,
        lot_size=0.02,
        spread_points=0.25,
        slippage_points=0.05,
        min_confluence_score=50.0,
        trailing_stop_enabled=True,
        classifier=clf,
    )
    metrics_m5 = bt_m5.run(df_m5, higher_tf_df=df_h1, warmup_bars=150)


if __name__ == "__main__":
    run_detailed_backtest()
