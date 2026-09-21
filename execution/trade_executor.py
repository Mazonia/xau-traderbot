"""
Trade Executor — MT5 Order Management

Handles the full lifecycle of trade execution:
- Opening trades with proper SL/TP
- Partial closes
- Position modifications
- Order logging to database
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from core.mt5_connector import MT5Connector
from database import crud
from execution.risk_manager import RiskManager
from strategies.base_strategy import TradingSignal, SignalDirection


class TradeExecutor:
    """
    Executes trades through MT5 with full risk management validation.

    Every trade passes through: Risk Check → Validation → Execution → Logging.
    """

    def __init__(self, mt5: MT5Connector, risk_manager: RiskManager):
        self.mt5 = mt5
        self.risk = risk_manager
        self._magic_number = 123456  # Bot identifier for MT5 orders

    def execute_signal(
        self,
        signal: TradingSignal,
        confluence_score: float = 0.0,
        sentiment_score: float = 0.0,
        ai_prediction: str = "",
        ai_confidence: float = 0.0,
        regime: str = "",
        risk_modifier: float = 1.0,
    ) -> Optional[dict]:
        """
        Execute a trading signal after full risk validation.

        Args:
            signal: The TradingSignal to execute.
            confluence_score: Overall confluence score.
            sentiment_score: News sentiment score.
            ai_prediction: AI direction prediction.
            ai_confidence: AI confidence level.
            regime: Current market regime.
            risk_modifier: Position size modifier from regime.

        Returns:
            Trade result dict or None if rejected.
        """
        if signal.direction == SignalDirection.HOLD:
            logger.debug("Signal is HOLD — skipping execution")
            return None

        direction = signal.direction.value  # "BUY" or "SELL"
        symbol = None  # Uses default from settings

        # ── 1. Risk Check ────────────────────────────────────────────────
        can_trade, reason = self.risk.can_trade(symbol)
        if not can_trade:
            logger.warning(f"Risk check failed: {reason}")
            # Record the rejected signal
            crud.create_signal(
                direction=direction,
                strategy=signal.strategy,
                timeframe=signal.timeframe,
                confluence_score=confluence_score,
                technical_score=signal.technical_score,
                sentiment_score=sentiment_score,
                was_executed=False,
                rejection_reason=reason,
                price_at_signal=signal.entry_price,
            )
            return None

        # ── 2. Check Conflicting Positions ───────────────────────────────
        if self.risk.check_conflicting_positions(direction, symbol):
            reason = f"Conflicting {direction} position already open"
            logger.warning(reason)
            crud.create_signal(
                direction=direction,
                strategy=signal.strategy,
                timeframe=signal.timeframe,
                confluence_score=confluence_score,
                technical_score=signal.technical_score,
                sentiment_score=sentiment_score,
                was_executed=False,
                rejection_reason=reason,
                price_at_signal=signal.entry_price,
            )
            return None

        # ── 3. Calculate Position Size ───────────────────────────────────
        lot_size = self.risk.calculate_lot_size(
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            symbol=symbol,
            risk_modifier=risk_modifier,
        )

        # ── 4. Validate Trade ────────────────────────────────────────────
        valid, validation_reason = self.risk.validate_trade(
            direction=direction,
            entry_price=signal.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            lot_size=lot_size,
            symbol=symbol,
        )

        if not valid:
            logger.warning(f"Trade validation failed: {validation_reason}")
            crud.create_signal(
                direction=direction,
                strategy=signal.strategy,
                timeframe=signal.timeframe,
                confluence_score=confluence_score,
                technical_score=signal.technical_score,
                sentiment_score=sentiment_score,
                was_executed=False,
                rejection_reason=validation_reason,
                price_at_signal=signal.entry_price,
            )
            return None

        # ── 5. Execute Trade ─────────────────────────────────────────────
        comment = f"{signal.strategy}|conf={confluence_score:.0f}"

        result = self.mt5.send_market_order(
            order_type=direction,
            symbol=symbol,
            volume=lot_size,
            sl=signal.stop_loss,
            tp=signal.take_profit,
            comment=comment,
            magic=self._magic_number,
        )

        if result is None or result.get("retcode") != 10009:  # TRADE_RETCODE_DONE
            error_msg = result.get("comment", "Unknown error") if result else "No response"
            logger.error(f"Trade execution failed: {error_msg}")
            crud.create_signal(
                direction=direction,
                strategy=signal.strategy,
                timeframe=signal.timeframe,
                confluence_score=confluence_score,
                technical_score=signal.technical_score,
                sentiment_score=sentiment_score,
                was_executed=False,
                rejection_reason=f"Execution error: {error_msg}",
                price_at_signal=signal.entry_price,
            )
            return None

        # ── 6. Record Trade ──────────────────────────────────────────────
        actual_price = result.get("price", signal.entry_price)
        ticket = result.get("order", 0)

        crud.create_trade(
            ticket=ticket,
            order_type=direction,
            strategy=signal.strategy,
            volume=lot_size,
            entry_price=actual_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            confluence_score=confluence_score,
            sentiment_score=sentiment_score,
            ai_prediction=ai_prediction,
            ai_confidence=ai_confidence,
            regime=regime,
            comment=comment,
        )

        # Record executed signal
        crud.create_signal(
            direction=direction,
            strategy=signal.strategy,
            timeframe=signal.timeframe,
            confluence_score=confluence_score,
            technical_score=signal.technical_score,
            sentiment_score=sentiment_score,
            was_executed=True,
            price_at_signal=actual_price,
        )

        logger.success(
            f"🎯 TRADE EXECUTED | {direction} {lot_size} lots @ {actual_price} | "
            f"SL: {signal.stop_loss} | TP: {signal.take_profit} | "
            f"Strategy: {signal.strategy} | Confluence: {confluence_score:.0f}"
        )

        return {
            "ticket": ticket,
            "direction": direction,
            "volume": lot_size,
            "entry_price": actual_price,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "strategy": signal.strategy,
            "confluence_score": confluence_score,
        }

    def close_trade(self, ticket: int, reason: str = "manual") -> bool:
        """Close a specific trade and update records."""
        positions = self.mt5.get_open_positions()
        position = next((p for p in positions if p["ticket"] == ticket), None)

        if not position:
            logger.warning(f"Position {ticket} not found")
            return False

        success = self.mt5.close_position(ticket, comment=f"close_{reason}")

        if success:
            crud.close_trade(
                ticket=ticket,
                exit_price=position["price_current"],
                profit=position["profit"],
                swap=position["swap"],
            )
            logger.info(
                f"Trade {ticket} closed | P&L: ${position['profit']:+.2f} | Reason: {reason}"
            )

        return success

    def close_partial(self, ticket: int, close_pct: float = 50.0) -> bool:
        """Close a percentage of a position."""
        positions = self.mt5.get_open_positions()
        position = next((p for p in positions if p["ticket"] == ticket), None)

        if not position:
            return False

        close_volume = round(position["volume"] * (close_pct / 100), 2)
        if close_volume < 0.01:
            close_volume = 0.01

        return self.mt5.close_position(
            ticket,
            volume=close_volume,
            comment=f"partial_{close_pct:.0f}pct",
        )

    def sync_positions(self) -> list[dict]:
        """
        Sync open MT5 positions with database records.
        Detect externally closed positions, fetch exact deal history, and return closed events.
        """
        db_open_trades = crud.get_open_trades()
        mt5_positions = self.mt5.get_open_positions()
        mt5_tickets = {p["ticket"] for p in mt5_positions}

        closed_events = []
        for trade in db_open_trades:
            if trade.ticket not in mt5_tickets:
                logger.info(f"Position {trade.ticket} closed externally — fetching deal history")
                deal_info = self.mt5.get_closed_deal_info(trade.ticket)
                if deal_info:
                    exit_price = deal_info["exit_price"]
                    profit = deal_info["profit"]
                    swap = deal_info["swap"]
                    commission = deal_info.get("commission", 0.0)
                    reason = deal_info.get("comment", "SL/TP hit")
                else:
                    exit_price = trade.entry_price
                    profit = 0.0
                    swap = 0.0
                    commission = 0.0
                    reason = "Closed externally"

                crud.close_trade(
                    ticket=trade.ticket,
                    exit_price=exit_price,
                    profit=profit,
                    swap=swap,
                    commission=commission,
                )
                closed_events.append({
                    "ticket": trade.ticket,
                    "symbol": trade.symbol,
                    "direction": trade.order_type,
                    "entry_price": trade.entry_price,
                    "exit_price": exit_price,
                    "profit": profit,
                    "swap": swap,
                    "commission": commission,
                    "reason": reason,
                })

        return closed_events

    def close_position(self, ticket: int, comment: str = "manual") -> bool:
        """Alias for close_trade for compatibility."""
        return self.close_trade(ticket=ticket, reason=comment)

    def close_all_positions(self, symbol: str | None = None) -> int:
        """Close all open positions and update database records immediately."""
        positions = self.mt5.get_open_positions(symbol)
        closed_count = 0
        for pos in positions:
            if self.close_trade(pos["ticket"], reason="emergency_closeall"):
                closed_count += 1
        return closed_count
