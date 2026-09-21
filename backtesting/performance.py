"""
Performance Metrics Calculator for Backtesting and Live Trading.

Calculates key quantitative metrics:
- Win Rate, Profit Factor, Sharpe Ratio, Sortino Ratio
- Maximum Drawdown ($ and %), Calmar Ratio
- Average Win, Average Loss, Risk-Reward Ratio
- Expectancy and Profitability Curves
"""

import math
from dataclasses import dataclass, field
from typing import Any, List, Optional
import numpy as np
import pandas as pd


@dataclass
class BacktestTrade:
    """Record of a simulated or historical trade."""
    trade_id: int
    symbol: str
    strategy: str
    direction: str             # BUY or SELL
    entry_time: Any
    exit_time: Any
    entry_price: float
    exit_price: float
    lot_size: float
    pnl: float                 # Net profit/loss in dollars
    pnl_pips: float            # Profit/loss in pips (0.1 for XAUUSD)
    pnl_pct: float             # Profit/loss in % of balance
    exit_reason: str           # TP, SL, TRAILING_STOP, TIMEOUT
    confluence_score: float
    bars_held: int


@dataclass
class PerformanceMetrics:
    """Comprehensive performance summary."""
    initial_balance: float
    final_balance: float
    total_pnl: float
    total_return_pct: float

    total_trades: int
    winning_trades: int
    losing_trades: int
    break_even_trades: int
    win_rate: float            # Percentage (0-100)

    gross_profit: float
    gross_loss: float
    profit_factor: float

    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    win_loss_ratio: float
    expectancy: float

    max_drawdown_amount: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float

    avg_bars_held: float
    best_trade_pnl: float
    worst_trade_pnl: float
    trades_by_strategy: dict = field(default_factory=dict)
    equity_curve: List[float] = field(default_factory=list)


def calculate_metrics(
    trades: List[BacktestTrade],
    initial_balance: float = 10_000.0,
    risk_free_rate: float = 0.04,
) -> PerformanceMetrics:
    """
    Compute full quantitative performance metrics from a list of closed trades.
    """
    if not trades:
        return PerformanceMetrics(
            initial_balance=initial_balance,
            final_balance=initial_balance,
            total_pnl=0.0,
            total_return_pct=0.0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            break_even_trades=0,
            win_rate=0.0,
            gross_profit=0.0,
            gross_loss=0.0,
            profit_factor=0.0,
            avg_trade_pnl=0.0,
            avg_win=0.0,
            avg_loss=0.0,
            win_loss_ratio=0.0,
            expectancy=0.0,
            max_drawdown_amount=0.0,
            max_drawdown_pct=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            avg_bars_held=0.0,
            best_trade_pnl=0.0,
            worst_trade_pnl=0.0,
            trades_by_strategy={},
            equity_curve=[initial_balance],
        )

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    evens = [p for p in pnls if p == 0]

    winning_trades = len(wins)
    losing_trades = len(losses)
    break_even_trades = len(evens)
    total_trades = len(trades)

    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    total_pnl = sum(pnls)
    final_balance = initial_balance + total_pnl
    total_return_pct = (total_pnl / initial_balance) * 100.0

    win_rate = (winning_trades / total_trades) * 100.0 if total_trades > 0 else 0.0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (999.0 if gross_profit > 0 else 0.0)

    avg_trade_pnl = total_pnl / total_trades if total_trades > 0 else 0.0
    avg_win = (gross_profit / winning_trades) if winning_trades > 0 else 0.0
    avg_loss = (gross_loss / losing_trades) if losing_trades > 0 else 0.0
    win_loss_ratio = (avg_win / avg_loss) if avg_loss > 0 else 0.0

    # Mathematical expectancy: (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
    p_win = winning_trades / total_trades if total_trades > 0 else 0
    p_loss = losing_trades / total_trades if total_trades > 0 else 0
    expectancy = (p_win * avg_win) - (p_loss * avg_loss)

    # Equity curve & Max Drawdown
    equity = initial_balance
    equity_curve = [initial_balance]
    peak = initial_balance
    max_dd_amount = 0.0
    max_dd_pct = 0.0

    returns_list = []
    for p in pnls:
        equity += p
        equity_curve.append(equity)
        ret = p / (equity - p) if (equity - p) > 0 else 0
        returns_list.append(ret)

        if equity > peak:
            peak = equity
        dd = peak - equity
        dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
        if dd > max_dd_amount:
            max_dd_amount = dd
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    # Sharpe & Sortino (annualized based on 252 trading days, assuming ~5 trades/day)
    trades_per_year = min(len(returns_list), 252 * 5)
    if len(returns_list) > 1 and np.std(returns_list) > 0:
        mean_ret = np.mean(returns_list)
        std_ret = np.std(returns_list)
        r_f_per_trade = risk_free_rate / max(1, trades_per_year)
        sharpe_ratio = float((mean_ret - r_f_per_trade) / std_ret * math.sqrt(trades_per_year))

        downside_returns = [r for r in returns_list if r < 0]
        if downside_returns and np.std(downside_returns) > 0:
            sortino_ratio = float((mean_ret - r_f_per_trade) / np.std(downside_returns) * math.sqrt(trades_per_year))
        else:
            sortino_ratio = 999.0 if mean_ret > 0 else 0.0
    else:
        sharpe_ratio = 0.0
        sortino_ratio = 0.0

    # Strategy breakdown
    trades_by_strategy = {}
    for t in trades:
        strat = t.strategy
        if strat not in trades_by_strategy:
            trades_by_strategy[strat] = {"count": 0, "wins": 0, "pnl": 0.0}
        trades_by_strategy[strat]["count"] += 1
        trades_by_strategy[strat]["pnl"] += t.pnl
        if t.pnl > 0:
            trades_by_strategy[strat]["wins"] += 1

    for s, data in trades_by_strategy.items():
        data["win_rate"] = round((data["wins"] / data["count"]) * 100.0, 1) if data["count"] > 0 else 0.0
        data["pnl"] = round(data["pnl"], 2)

    avg_bars_held = float(np.mean([t.bars_held for t in trades])) if trades else 0.0
    best_trade_pnl = max(pnls) if pnls else 0.0
    worst_trade_pnl = min(pnls) if pnls else 0.0

    return PerformanceMetrics(
        initial_balance=round(initial_balance, 2),
        final_balance=round(final_balance, 2),
        total_pnl=round(total_pnl, 2),
        total_return_pct=round(total_return_pct, 2),
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        break_even_trades=break_even_trades,
        win_rate=round(win_rate, 2),
        gross_profit=round(gross_profit, 2),
        gross_loss=round(gross_loss, 2),
        profit_factor=round(profit_factor, 2),
        avg_trade_pnl=round(avg_trade_pnl, 2),
        avg_win=round(avg_win, 2),
        avg_loss=round(avg_loss, 2),
        win_loss_ratio=round(win_loss_ratio, 2),
        expectancy=round(expectancy, 2),
        max_drawdown_amount=round(max_dd_amount, 2),
        max_drawdown_pct=round(max_dd_pct, 2),
        sharpe_ratio=round(sharpe_ratio, 2),
        sortino_ratio=round(sortino_ratio, 2),
        avg_bars_held=round(avg_bars_held, 1),
        best_trade_pnl=round(best_trade_pnl, 2),
        worst_trade_pnl=round(worst_trade_pnl, 2),
        trades_by_strategy=trades_by_strategy,
        equity_curve=equity_curve,
    )
