"""
Trailing Stop Manager

Dynamic stop-loss management for open positions:
- ATR-based trailing stop that tightens as trade moves in profit
- Breakeven trigger (move SL to entry after reaching 1:1 RR)
- Partial close at first TP target
"""

from loguru import logger

from config.settings import get_settings
from core.mt5_connector import MT5Connector


class TrailingStopManager:
    """
    Manages trailing stops for all open positions.

    Called periodically by the main bot loop to adjust SL levels.
    """

    def __init__(self, mt5: MT5Connector):
        self.mt5 = mt5
        settings = get_settings()
        params = settings.trailing_stop_params

        self.enabled = params.get("enabled", True)
        self.breakeven_rr = params.get("breakeven_trigger_rr", 1.0)
        self.partial_close_pct = params.get("partial_close_pct", 50)
        self.atr_trail_multiplier = params.get("atr_trail_multiplier", 2.0)

        # Track which positions have had breakeven applied
        self._breakeven_applied: set[int] = set()
        self._partial_closed: set[int] = set()

    def update_all_positions(self, current_atr: float):
        """
        Update trailing stops for all open positions.

        Args:
            current_atr: Current ATR value for the symbol.
        """
        if not self.enabled:
            return

        positions = self.mt5.get_open_positions()
        open_tickets = {p["ticket"] for p in positions}
        self.cleanup_closed(open_tickets)

        for pos in positions:
            self._update_position(pos, current_atr)

    def _update_position(self, position: dict, current_atr: float):
        """Update trailing stop for a single position."""
        ticket = position["ticket"]
        entry_price = position["price_open"]
        current_price = position["price_current"]
        current_sl = position["sl"]
        current_tp = position["tp"]
        pos_type = position["type"]
        volume = position["volume"]

        if current_sl == 0 or current_tp == 0:
            return  # Skip positions without SL/TP

        sl_distance = abs(entry_price - current_sl)
        tp_distance = abs(current_tp - entry_price)

        # ── 1. Breakeven Check ───────────────────────────────────────────
        if ticket not in self._breakeven_applied:
            if pos_type == "BUY":
                profit_distance = current_price - entry_price
                breakeven_target = sl_distance * self.breakeven_rr

                if profit_distance >= breakeven_target:
                    # Move SL to breakeven (entry + small buffer)
                    tick = self.mt5.get_current_tick()
                    spread = tick["spread"] / 100 if tick else 0.5
                    new_sl = round(entry_price + spread, 2)

                    if new_sl > current_sl:
                        success = self.mt5.modify_position(ticket, sl=new_sl, tp=current_tp)
                        if success:
                            self._breakeven_applied.add(ticket)
                            logger.info(
                                f"🔒 Breakeven applied to #{ticket} | "
                                f"SL moved: {current_sl} → {new_sl}"
                            )

            elif pos_type == "SELL":
                profit_distance = entry_price - current_price
                breakeven_target = sl_distance * self.breakeven_rr

                if profit_distance >= breakeven_target:
                    tick = self.mt5.get_current_tick()
                    spread = tick["spread"] / 100 if tick else 0.5
                    new_sl = round(entry_price - spread, 2)

                    if new_sl < current_sl:
                        success = self.mt5.modify_position(ticket, sl=new_sl, tp=current_tp)
                        if success:
                            self._breakeven_applied.add(ticket)
                            logger.info(
                                f"🔒 Breakeven applied to #{ticket} | "
                                f"SL moved: {current_sl} → {new_sl}"
                            )

        # ── 2. ATR Trailing Stop ─────────────────────────────────────────
        trail_distance = current_atr * self.atr_trail_multiplier

        if pos_type == "BUY":
            # Trail up: new SL = current_price - (ATR * multiplier)
            proposed_sl = round(current_price - trail_distance, 2)

            # Only move SL up, never down
            if proposed_sl > current_sl and proposed_sl < current_price:
                success = self.mt5.modify_position(ticket, sl=proposed_sl, tp=current_tp)
                if success:
                    logger.debug(
                        f"📈 Trailing stop updated #{ticket} | "
                        f"SL: {current_sl} → {proposed_sl} "
                        f"(price: {current_price}, ATR trail: {trail_distance:.2f})"
                    )

        elif pos_type == "SELL":
            # Trail down: new SL = current_price + (ATR * multiplier)
            proposed_sl = round(current_price + trail_distance, 2)

            # Only move SL down (for shorts), never up
            if proposed_sl < current_sl and proposed_sl > current_price:
                success = self.mt5.modify_position(ticket, sl=proposed_sl, tp=current_tp)
                if success:
                    logger.debug(
                        f"📉 Trailing stop updated #{ticket} | "
                        f"SL: {current_sl} → {proposed_sl}"
                    )

    def cleanup_closed(self, open_tickets: set[int]):
        """Remove closed tickets from tracking sets."""
        self._breakeven_applied -= (self._breakeven_applied - open_tickets)
        self._partial_closed -= (self._partial_closed - open_tickets)
