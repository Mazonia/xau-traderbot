"""
Backtesting Engine for XAUUSD AI Trading Bot

Simulates realistic multi-strategy execution against historical price data:
- Zero lookahead bias (evaluates bars sequentially)
- Dynamic ATR-based Stop Loss & Take Profit
- Trailing stop simulation
- Realistic spread & slippage modeling
- Confluence score filtering
- Detailed quantitative performance reporting
"""

import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np
import pandas as pd
from loguru import logger

from analysis.technical import TechnicalAnalyzer
from strategies.day_trading import DayTradingStrategy
from strategies.regime_detector import RegimeDetector
from strategies.scalping import ScalpingStrategy
from strategies.signal_aggregator import SignalAggregator
from strategies.swing_trading import SwingTradingStrategy
from backtesting.performance import BacktestTrade, PerformanceMetrics, calculate_metrics


class Backtester:
    """
    Simulates trading strategies on historical or synthetic candle data.
    """

    def __init__(
        self,
        initial_balance: float = 10_000.0,
        lot_size: float = 0.02,
        spread_points: float = 0.25,        # ~$0.25 on gold
        slippage_points: float = 0.05,
        min_confluence_score: float = 65.0,
        trailing_stop_enabled: bool = True,
    ):
        self.initial_balance = initial_balance
        self.lot_size = lot_size
        self.spread = spread_points
        self.slippage = slippage_points
        self.min_confluence = min_confluence_score
        self.trailing_enabled = trailing_stop_enabled

        self.ta = TechnicalAnalyzer()
        self.regime_detector = RegimeDetector()
        self.aggregator = SignalAggregator()

        self.strategies = {
            "scalping": ScalpingStrategy(),
            "day_trading": DayTradingStrategy(),
            "swing_trading": SwingTradingStrategy(),
        }

    def generate_benchmark_data(self, bars: int = 1500, start_price: float = 2650.0) -> pd.DataFrame:
        """
        Generate realistic historical XAUUSD price action using
        Geometric Brownian Motion with intraday volatility regime shifts.
        """
        np.random.seed(42)
        dt_start = datetime.now() - timedelta(hours=bars)
        timestamps = [dt_start + timedelta(hours=i) for i in range(bars)]

        dt = 1.0 / 24.0
        mu = 0.0001
        base_sigma = 0.008

        # Generate volatility regimes (clustering)
        regimes = np.random.choice([0.7, 1.0, 1.8], size=bars, p=[0.5, 0.35, 0.15])
        sigmas = base_sigma * regimes

        prices = [start_price]
        for i in range(1, bars):
            shock = np.random.normal(0, 1)
            ret = (mu - 0.5 * sigmas[i]**2) * dt + sigmas[i] * math.sqrt(dt) * shock
            p = prices[-1] * math.exp(ret)
            prices.append(max(100.0, p))

        opens, highs, lows, closes, volumes = [], [], [], [], []
        for i in range(bars):
            close = prices[i]
            open_p = prices[i-1] if i > 0 else close * 0.999
            bar_range = abs(close - open_p) + (close * sigmas[i] * 0.5)
            high = max(open_p, close) + abs(np.random.normal(0, bar_range * 0.6))
            low = min(open_p, close) - abs(np.random.normal(0, bar_range * 0.6))
            vol = int(np.random.uniform(500, 5000))

            opens.append(round(open_p, 2))
            highs.append(round(high, 2))
            lows.append(round(low, 2))
            closes.append(round(close, 2))
            volumes.append(vol)

        df = pd.DataFrame({
            "time": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        })
        return df

    def run(self, df: pd.DataFrame, warmup_bars: int = 200) -> PerformanceMetrics:
        """
        Run the backtest across historical bars.
        """
        if len(df) <= warmup_bars:
            raise ValueError(f"Dataframe length ({len(df)}) must exceed warmup_bars ({warmup_bars})")

        logger.info(f"🚀 Starting backtest on {len(df)} candles (Warmup: {warmup_bars} bars)...")

        # Precalculate technical indicators on the full dataset
        df_indicators = self.ta.add_all_indicators(df.copy())

        closed_trades: List[BacktestTrade] = []
        open_position: Optional[dict] = None
        trade_counter = 0

        # Point value for XAUUSD (1 standard lot = 100 oz, so 1 point move = $100 on 1.0 lot, $100 * lot_size)
        dollar_per_point = 100.0 * self.lot_size

        for i in range(warmup_bars, len(df_indicators)):
            current_bar = df_indicators.iloc[i]
            prev_bar = df_indicators.iloc[i - 1]
            sub_df = df_indicators.iloc[:i + 1]

            current_high = current_bar["high"]
            current_low = current_bar["low"]
            current_close = current_bar["close"]
            current_time = current_bar.get("time", i)
            atr = float(current_bar.get("atr", 3.0))

            # ── 1. Manage existing open position ───────────────────────
            if open_position is not None:
                open_position["bars_held"] += 1
                pos = open_position
                direction = pos["direction"]
                entry_price = pos["entry_price"]
                sl = pos["stop_loss"]
                tp = pos["take_profit"]

                closed = False
                exit_price = 0.0
                exit_reason = ""

                # Check SL and TP within bar
                if direction == "BUY":
                    # Check Stop Loss first (conservative)
                    if current_low <= sl:
                        exit_price = sl - self.slippage
                        exit_reason = "STOP_LOSS"
                        closed = True
                    elif current_high >= tp:
                        exit_price = tp
                        exit_reason = "TAKE_PROFIT"
                        closed = True
                    elif self.trailing_enabled:
                        # Update Trailing Stop if price moved in profit by 1.5 ATR
                        gain = current_close - entry_price
                        if gain > 1.5 * atr:
                            new_sl = current_close - 1.2 * atr
                            if new_sl > pos["stop_loss"]:
                                pos["stop_loss"] = new_sl

                elif direction == "SELL":
                    if current_high >= sl:
                        exit_price = sl + self.slippage
                        exit_reason = "STOP_LOSS"
                        closed = True
                    elif current_low <= tp:
                        exit_price = tp
                        exit_reason = "TAKE_PROFIT"
                        closed = True
                    elif self.trailing_enabled:
                        gain = entry_price - current_close
                        if gain > 1.5 * atr:
                            new_sl = current_close + 1.2 * atr
                            if new_sl < pos["stop_loss"]:
                                pos["stop_loss"] = new_sl

                if closed:
                    # Calculate P&L
                    if direction == "BUY":
                        points_diff = exit_price - entry_price
                    else:
                        points_diff = entry_price - exit_price

                    pnl_dollars = points_diff * dollar_per_point
                    pips = points_diff * 10.0  # 1 pip = 0.1 on gold
                    pnl_pct = (pnl_dollars / self.initial_balance) * 100.0

                    trade = BacktestTrade(
                        trade_id=pos["trade_id"],
                        symbol="XAUUSD",
                        strategy=pos["strategy"],
                        direction=direction,
                        entry_time=pos["entry_time"],
                        exit_time=current_time,
                        entry_price=round(entry_price, 2),
                        exit_price=round(exit_price, 2),
                        lot_size=self.lot_size,
                        pnl=round(pnl_dollars, 2),
                        pnl_pips=round(pips, 1),
                        pnl_pct=round(pnl_pct, 2),
                        exit_reason=exit_reason,
                        confluence_score=pos["confluence_score"],
                        bars_held=pos["bars_held"],
                    )
                    closed_trades.append(trade)
                    open_position = None

            # ── 2. Evaluate new entries if no position is open ────────
            if open_position is None:
                regime = self.regime_detector.analyze(sub_df)
                if not regime.should_trade:
                    continue

                best_signal = None
                best_confluence = None

                for strat_name, strat in self.strategies.items():
                    if not self.regime_detector.is_strategy_recommended(strat_name, regime):
                        continue

                    sig = strat.run(sub_df)
                    if not sig.is_actionable:
                        continue

                    # Confluence check
                    confluence = self.aggregator.calculate_confluence(
                        strategy_signal=sig,
                        ai_prediction={"direction": "HOLD", "confidence": 0.0},
                        sentiment={"direction": "NEUTRAL", "score": 0.0},
                        regime_analysis={
                            "is_recommended": True,
                            "position_modifier": regime.position_size_modifier,
                        },
                        min_score=self.min_confluence,
                    )

                    if confluence.should_execute:
                        if best_confluence is None or confluence.total_score > best_confluence.total_score:
                            best_signal = sig
                            best_confluence = confluence

                if best_signal and best_confluence and best_confluence.should_execute:
                    direction = best_signal.direction
                    raw_price = current_close

                    # Apply realistic execution spread & slippage
                    if direction == "BUY":
                        entry_price = raw_price + (self.spread / 2.0) + self.slippage
                        sl = best_signal.stop_loss or (entry_price - 2.0 * atr)
                        tp = best_signal.take_profit or (entry_price + 3.0 * atr)
                    else:
                        entry_price = raw_price - (self.spread / 2.0) - self.slippage
                        sl = best_signal.stop_loss or (entry_price + 2.0 * atr)
                        tp = best_signal.take_profit or (entry_price - 3.0 * atr)

                    trade_counter += 1
                    open_position = {
                        "trade_id": trade_counter,
                        "strategy": best_signal.strategy_name,
                        "direction": direction,
                        "entry_time": current_time,
                        "entry_price": entry_price,
                        "stop_loss": sl,
                        "take_profit": tp,
                        "confluence_score": best_confluence.total_score,
                        "bars_held": 0,
                    }

        # Calculate and print performance
        metrics = calculate_metrics(closed_trades, initial_balance=self.initial_balance)
        self._print_report(metrics)
        return metrics

    def _print_report(self, m: PerformanceMetrics):
        """Display a formatted quantitative performance report."""
        border = "=" * 62
        divider = "-" * 62

        lines = [
            "",
            border,
            "         [+] XAUUSD AI TRADING BOT - BACKTEST REPORT [+]",
            border,
            f" Initial Capital:      ${m.initial_balance:>10,.2f}",
            f" Final Capital:        ${m.final_balance:>10,.2f}",
            f" Net Profit / Loss:    ${m.total_pnl:>10,.2f} ({m.total_return_pct:+.2f}%)",
            divider,
            f" Total Trades:         {m.total_trades:>10}",
            f" Winning Trades:       {m.winning_trades:>10} ({m.win_rate:.1f}%)",
            f" Losing Trades:        {m.losing_trades:>10} ({100 - m.win_rate:.1f}%)",
            f" Profit Factor:        {m.profit_factor:>10.2f}",
            divider,
            f" Average Win:          ${m.avg_win:>10.2f}",
            f" Average Loss:         ${m.avg_loss:>10.2f}",
            f" Win/Loss Ratio:       {m.win_loss_ratio:>10.2f}",
            f" Expectancy / Trade:   ${m.expectancy:>10.2f}",
            divider,
            f" Max Drawdown:         ${m.max_drawdown_amount:>10.2f} ({m.max_drawdown_pct:.2f}%)",
            f" Sharpe Ratio:         {m.sharpe_ratio:>10.2f}",
            f" Sortino Ratio:        {m.sortino_ratio:>10.2f}",
            f" Avg Bars Held:        {m.avg_bars_held:>10.1f} bars",
            divider,
            " Performance by Strategy:",
        ]
        if m.trades_by_strategy:
            for s_name, data in m.trades_by_strategy.items():
                lines.append(f"   * {s_name:<16}: {data['count']:>3} trades | WR: {data['win_rate']:>5.1f}% | PnL: ${data['pnl']:>8,.2f}")
        else:
            lines.append("   (No completed trades executed)")
        lines.append(border)
        lines.append("")
        print("\n".join(lines))
