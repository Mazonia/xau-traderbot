"""
Risk Manager — Position Sizing & Safety Controls

Enforces:
- Max risk per trade (2-5% of account)
- Daily loss limit (stop trading if exceeded)
- Max concurrent open trades
- Minimum free margin
- Spread filter
- Correlation checks
"""

from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from config.settings import get_settings
from core.mt5_connector import MT5Connector
from database import crud


class RiskManager:
    """
    Controls position sizing and enforces risk limits.

    This is the safety layer between signal generation and trade execution.
    Every trade must pass through the risk manager before being placed.
    """

    def __init__(self, mt5: MT5Connector):
        self.mt5 = mt5
        settings = get_settings()
        params = settings.risk_params

        self.max_risk_pct = params.get("max_risk_per_trade_pct", 3.0)
        self.max_daily_loss_pct = params.get("max_daily_loss_pct", 5.0)
        self.max_concurrent = params.get("max_concurrent_trades", 3)
        self.min_free_margin_pct = params.get("min_free_margin_pct", 50.0)
        self.max_spread = params.get("max_spread_points", 40)
        self.default_lot = params.get("default_lot_size", 0.01)
        self.max_lot = params.get("max_lot_size", 1.0)

        self._daily_loss_triggered = False
        self._last_reset_date = None

    def can_trade(self, symbol: str | None = None) -> tuple[bool, str]:
        """
        Check if trading is currently allowed.

        Returns:
            Tuple of (can_trade: bool, reason: str)
        """
        # Reset daily loss trigger at start of new day
        today = datetime.now(timezone.utc).date()
        if self._last_reset_date != today:
            self._daily_loss_triggered = False
            self._last_reset_date = today

        # 1. Daily loss limit check
        if self._daily_loss_triggered:
            return False, "Daily loss limit already triggered — trading paused"

        daily_pnl = crud.get_daily_pnl()
        account = self.mt5.get_account_info()
        if not account:
            return False, "Cannot retrieve account info"

        balance = account["balance"]
        max_daily_loss = balance * (self.max_daily_loss_pct / 100)

        if abs(daily_pnl) >= max_daily_loss and daily_pnl < 0:
            self._daily_loss_triggered = True
            logger.critical(
                f"⛔ DAILY LOSS LIMIT HIT: ${daily_pnl:.2f} "
                f"(limit: -${max_daily_loss:.2f}) — TRADING PAUSED"
            )
            return False, f"Daily loss limit hit (${daily_pnl:.2f})"

        # 2. Max concurrent trades
        open_positions = self.mt5.get_open_positions(symbol)
        if len(open_positions) >= self.max_concurrent:
            return False, f"Max concurrent trades reached ({len(open_positions)}/{self.max_concurrent})"

        # 3. Free margin check
        if account["margin_level"] and account["margin_level"] < self.min_free_margin_pct:
            return False, f"Margin level too low ({account['margin_level']:.1f}% < {self.min_free_margin_pct}%)"

        free_margin_pct = (account["free_margin"] / balance * 100) if balance > 0 else 0
        if free_margin_pct < self.min_free_margin_pct:
            return False, f"Free margin too low ({free_margin_pct:.1f}%)"

        # 4. Spread check
        tick = self.mt5.get_current_tick(symbol)
        if tick and tick["spread"] > self.max_spread:
            return False, f"Spread too wide ({tick['spread']:.1f} > {self.max_spread} points)"

        # 5. Trading allowed on account
        if not account.get("trade_allowed", True):
            return False, "Trading not allowed on this account"

        return True, "All risk checks passed"

    def calculate_lot_size(
        self,
        entry_price: float,
        stop_loss: float,
        symbol: str | None = None,
        risk_modifier: float = 1.0,
    ) -> float:
        """
        Calculate optimal lot size based on risk parameters.

        Uses the formula:
        lot_size = (account_balance * risk_pct) / (SL_distance * pip_value * contract_size)

        Args:
            entry_price: Expected entry price
            stop_loss: Stop loss price
            symbol: Trading symbol
            risk_modifier: Multiplier from regime detector (0.7 - 1.2)

        Returns:
            Calculated lot size (rounded to symbol's volume step)
        """
        account = self.mt5.get_account_info()
        if not account:
            logger.warning("Cannot get account info — using default lot size")
            return self.default_lot

        balance = account["balance"]

        # Risk amount in account currency
        risk_amount = balance * (self.max_risk_pct / 100) * risk_modifier

        # SL distance in price
        sl_distance = abs(entry_price - stop_loss)
        if sl_distance == 0:
            logger.warning("SL distance is 0 — using default lot size")
            return self.default_lot

        # Get symbol info for contract size and pip value
        symbol_info = self.mt5.get_symbol_info(symbol)
        if not symbol_info:
            return self.default_lot

        contract_size = symbol_info.get("trade_contract_size", 100)
        point = symbol_info.get("point", 0.01)
        volume_step = symbol_info.get("volume_step", 0.01)
        volume_min = symbol_info.get("volume_min", 0.01)
        volume_max = symbol_info.get("volume_max", 100)

        # Calculate lot size
        # For XAUUSD: 1 lot = 100 oz, pip value ≈ $1 per pip per lot
        pip_value_per_lot = contract_size * point
        if pip_value_per_lot == 0:
            return self.default_lot

        sl_pips = sl_distance / point
        lot_size = risk_amount / (sl_pips * pip_value_per_lot)

        # Apply constraints
        lot_size = max(volume_min, lot_size)
        lot_size = min(volume_max, lot_size)
        lot_size = min(self.max_lot, lot_size)

        # Round to volume step
        lot_size = round(lot_size / volume_step) * volume_step
        lot_size = round(lot_size, 2)  # Ensure 2 decimal places

        logger.info(
            f"Position sizing: balance=${balance:.2f} risk={self.max_risk_pct}% "
            f"SL_dist={sl_distance:.2f} → {lot_size} lots "
            f"(risk=${risk_amount:.2f}, modifier={risk_modifier:.1f})"
        )

        return lot_size

    def validate_trade(
        self,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        lot_size: float,
        symbol: str | None = None,
    ) -> tuple[bool, str]:
        """
        Final validation before executing a trade.

        Args:
            direction: BUY or SELL
            entry_price: Expected entry price
            stop_loss: Stop loss price
            take_profit: Take profit price
            lot_size: Proposed lot size
            symbol: Trading symbol

        Returns:
            Tuple of (valid: bool, reason: str)
        """
        # 1. SL and TP must be set
        if stop_loss == 0:
            return False, "Stop loss must be set"

        if take_profit == 0:
            return False, "Take profit must be set"

        # 2. SL must be on correct side
        if direction == "BUY":
            if stop_loss >= entry_price:
                return False, f"BUY SL ({stop_loss}) must be below entry ({entry_price})"
            if take_profit <= entry_price:
                return False, f"BUY TP ({take_profit}) must be above entry ({entry_price})"
        elif direction == "SELL":
            if stop_loss <= entry_price:
                return False, f"SELL SL ({stop_loss}) must be above entry ({entry_price})"
            if take_profit >= entry_price:
                return False, f"SELL TP ({take_profit}) must be below entry ({entry_price})"

        # 3. Risk-reward ratio must be at least 1:1
        sl_distance = abs(entry_price - stop_loss)
        tp_distance = abs(entry_price - take_profit)
        rr_ratio = tp_distance / sl_distance if sl_distance > 0 else 0

        if rr_ratio < 1.0:
            return False, f"Risk-reward ratio too low ({rr_ratio:.2f} < 1.0)"

        # 4. Lot size must be valid
        if lot_size <= 0:
            return False, "Lot size must be positive"
        if lot_size > self.max_lot:
            return False, f"Lot size ({lot_size}) exceeds max ({self.max_lot})"

        # 5. Check minimum stops level
        symbol_info = self.mt5.get_symbol_info(symbol)
        if symbol_info:
            stops_level = symbol_info.get("trade_stops_level", 0) * symbol_info.get("point", 0.01)
            if sl_distance < stops_level:
                return False, f"SL distance ({sl_distance:.2f}) below broker minimum ({stops_level:.2f})"

        return True, "Trade validated successfully"

    def check_conflicting_positions(
        self,
        direction: str,
        symbol: str | None = None,
    ) -> bool:
        """Check if there's already an opposing position open."""
        positions = self.mt5.get_open_positions(symbol)
        for pos in positions:
            if pos["type"] != direction:
                logger.warning(
                    f"Conflicting position found: existing {pos['type']} "
                    f"vs proposed {direction}"
                )
                return True
        return False
