"""
MT5 Connector — MetaTrader 5 Connection & Data Manager

Handles:
- MT5 initialization with auto-reconnect
- Historical OHLCV data fetching
- Real-time tick data
- Account info & margin tracking
- Trade execution primitives
"""

import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

import MetaTrader5 as mt5
import numpy as np
import pandas as pd
from loguru import logger

from config.settings import get_settings


class Timeframe(Enum):
    """MT5 timeframe mappings."""

    M1 = mt5.TIMEFRAME_M1
    M5 = mt5.TIMEFRAME_M5
    M15 = mt5.TIMEFRAME_M15
    M30 = mt5.TIMEFRAME_M30
    H1 = mt5.TIMEFRAME_H1
    H4 = mt5.TIMEFRAME_H4
    D1 = mt5.TIMEFRAME_D1
    W1 = mt5.TIMEFRAME_W1
    MN1 = mt5.TIMEFRAME_MN1


# Map string names to Timeframe enum
TIMEFRAME_MAP: dict[str, Timeframe] = {tf.name: tf for tf in Timeframe}


class MT5Connector:
    """
    Manages the connection to MetaTrader 5 via the Python API.

    Provides methods for:
    - Connecting/disconnecting from MT5
    - Fetching historical OHLCV data
    - Getting real-time ticks
    - Querying account information
    - Sending trade orders
    """

    def __init__(self):
        self.settings = get_settings()
        self._connected = False
        self._max_retries = 5
        self._retry_delay = 5  # seconds

    # ── Connection Management ────────────────────────────────────────────

    def connect(self, max_retries: int | None = None, retry_delay: float | None = None) -> bool:
        """
        Initialize connection to MT5 terminal with auto-retry.

        Returns:
            True if connected successfully, False otherwise.
        """
        retries = max_retries if max_retries is not None else self._max_retries
        delay = retry_delay if retry_delay is not None else self._retry_delay
        for attempt in range(1, retries + 1):
            try:
                # Initialize MT5
                init_kwargs = {
                    "login": self.settings.mt5.login,
                    "server": self.settings.mt5.server,
                    "password": self.settings.mt5.password,
                    "timeout": self.settings.mt5.timeout,
                }

                # Only pass path if it's set and valid
                if self.settings.mt5.path:
                    init_kwargs["path"] = self.settings.mt5.path

                if not mt5.initialize(**init_kwargs):
                    error = mt5.last_error()
                    logger.warning(
                        f"MT5 init attempt {attempt}/{retries} failed: {error}"
                    )
                    if attempt < retries:
                        time.sleep(delay * attempt)  # Exponential backoff
                    continue

                self._connected = True
                account_info = mt5.account_info()

                if account_info:
                    logger.success(
                        f"Connected to MT5 | "
                        f"Account: {account_info.login} | "
                        f"Server: {account_info.server} | "
                        f"Balance: ${account_info.balance:,.2f} | "
                        f"Leverage: 1:{account_info.leverage}"
                    )
                else:
                    logger.success("Connected to MT5 (account info unavailable)")

                return True

            except Exception as e:
                logger.error(f"MT5 connection error (attempt {attempt}): {e}")
                if attempt < retries:
                    time.sleep(delay * attempt)

        logger.critical("Failed to connect to MT5 after all retries")
        return False

    def disconnect(self):
        """Safely shut down the MT5 connection."""
        if self._connected:
            mt5.shutdown()
            self._connected = False
            logger.info("MT5 connection closed")

    def is_connected(self) -> bool:
        """Check if MT5 is still connected and responsive."""
        if not self._connected:
            return False
        try:
            info = mt5.terminal_info()
            return info is not None
        except Exception:
            self._connected = False
            return False

    def ensure_connected(self) -> bool:
        """Reconnect if the connection was lost."""
        if not self.is_connected():
            logger.warning("MT5 connection lost — attempting reconnect...")
            return self.connect()
        return True

    # ── Market Data ──────────────────────────────────────────────────────

    def get_rates(
        self,
        symbol: str | None = None,
        timeframe: str = "H1",
        count: int = 500,
    ) -> pd.DataFrame | None:
        """
        Fetch historical OHLCV data from MT5.

        Args:
            symbol: Trading symbol (defaults to configured XAUUSD).
            timeframe: Timeframe string (M1, M5, M15, M30, H1, H4, D1, W1, MN1).
            count: Number of candles to fetch.

        Returns:
            DataFrame with columns: time, open, high, low, close, tick_volume, spread
        """
        if not self.ensure_connected():
            return None

        symbol = symbol or self.settings.symbol
        tf = TIMEFRAME_MAP.get(timeframe)

        if tf is None:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        rates = mt5.copy_rates_from_pos(symbol, tf.value, 0, count)

        if rates is None or len(rates) == 0:
            error = mt5.last_error()
            logger.error(f"Failed to get rates for {symbol} {timeframe}: {error}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)

        # Rename columns for consistency
        df.rename(
            columns={
                "tick_volume": "volume",
                "real_volume": "real_volume",
            },
            inplace=True,
        )

        logger.debug(
            f"Fetched {len(df)} candles for {symbol} {timeframe} "
            f"({df.index[0]} → {df.index[-1]})"
        )
        return df

    def get_rates_range(
        self,
        start_date: datetime,
        end_date: datetime,
        symbol: str | None = None,
        timeframe: str = "H1",
    ) -> pd.DataFrame | None:
        """Fetch historical data for a specific date range."""
        if not self.ensure_connected():
            return None

        symbol = symbol or self.settings.symbol
        tf = TIMEFRAME_MAP.get(timeframe)

        if tf is None:
            logger.error(f"Invalid timeframe: {timeframe}")
            return None

        rates = mt5.copy_rates_range(symbol, tf.value, start_date, end_date)

        if rates is None or len(rates) == 0:
            error = mt5.last_error()
            logger.error(f"Failed to get rate range for {symbol}: {error}")
            return None

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        df.set_index("time", inplace=True)
        return df

    def get_current_tick(self, symbol: str | None = None) -> dict | None:
        """
        Get the latest tick (bid/ask) for the symbol.

        Returns:
            Dict with: bid, ask, last, volume, time, spread
        """
        if not self.ensure_connected():
            return None

        symbol = symbol or self.settings.symbol
        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            logger.error(f"Failed to get tick for {symbol}")
            return None

        return {
            "bid": tick.bid,
            "ask": tick.ask,
            "last": tick.last,
            "volume": tick.volume,
            "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
            "spread": round((tick.ask - tick.bid) * 100, 1),  # In points
        }

    def get_symbol_info(self, symbol: str | None = None) -> dict | None:
        """Get symbol specifications (pip value, lot size, etc.)."""
        if not self.ensure_connected():
            return None

        symbol = symbol or self.settings.symbol
        info = mt5.symbol_info(symbol)

        if info is None:
            logger.error(f"Symbol info not found: {symbol}")
            return None

        return {
            "name": info.name,
            "description": info.description,
            "point": info.point,
            "digits": info.digits,
            "spread": info.spread,
            "trade_contract_size": info.trade_contract_size,
            "volume_min": info.volume_min,
            "volume_max": info.volume_max,
            "volume_step": info.volume_step,
            "trade_stops_level": info.trade_stops_level,
            "swap_long": info.swap_long,
            "swap_short": info.swap_short,
        }

    # ── Account Information ──────────────────────────────────────────────

    def get_account_info(self, auto_reconnect: bool = True) -> dict | None:
        """Get current account information."""
        if not self.is_connected():
            if not auto_reconnect or not self.ensure_connected():
                return None

        info = mt5.account_info()
        if info is None:
            return None

        return {
            "login": info.login,
            "server": info.server,
            "balance": info.balance,
            "equity": info.equity,
            "margin": info.margin,
            "free_margin": info.margin_free,
            "margin_level": info.margin_level,
            "profit": info.profit,
            "leverage": info.leverage,
            "currency": info.currency,
            "trade_allowed": info.trade_allowed,
        }

    def get_open_positions(self, symbol: str | None = None) -> list[dict]:
        """Get all open positions, optionally filtered by symbol."""
        if not self.ensure_connected():
            return []

        if symbol:
            positions = mt5.positions_get(symbol=symbol)
        else:
            positions = mt5.positions_get()

        if positions is None:
            return []

        return [
            {
                "ticket": pos.ticket,
                "symbol": pos.symbol,
                "type": "BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL",
                "volume": pos.volume,
                "price_open": pos.price_open,
                "price_current": pos.price_current,
                "sl": pos.sl,
                "tp": pos.tp,
                "profit": pos.profit,
                "swap": pos.swap,
                "time": datetime.fromtimestamp(pos.time, tz=timezone.utc),
                "comment": pos.comment,
                "magic": pos.magic,
            }
            for pos in positions
        ]

    def get_pending_orders(self, symbol: str | None = None) -> list[dict]:
        """Get all pending orders."""
        if not self.ensure_connected():
            return []

        if symbol:
            orders = mt5.orders_get(symbol=symbol)
        else:
            orders = mt5.orders_get()

        if orders is None:
            return []

        order_type_map = {
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY_LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL_LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY_STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL_STOP",
        }

        return [
            {
                "ticket": order.ticket,
                "symbol": order.symbol,
                "type": order_type_map.get(order.type, "UNKNOWN"),
                "volume": order.volume_current,
                "price": order.price_open,
                "sl": order.sl,
                "tp": order.tp,
                "time": datetime.fromtimestamp(order.time_setup, tz=timezone.utc),
                "comment": order.comment,
            }
            for order in orders
        ]

    # ── Trade Execution (Primitives) ─────────────────────────────────────

    def send_market_order(
        self,
        order_type: str,
        symbol: str | None = None,
        volume: float = 0.01,
        sl: float = 0.0,
        tp: float = 0.0,
        comment: str = "XAUUSD_AI_BOT",
        magic: int = 123456,
    ) -> dict | None:
        """
        Send a market order (BUY or SELL).

        Args:
            order_type: "BUY" or "SELL"
            symbol: Trading symbol
            volume: Lot size
            sl: Stop loss price (0 = no SL)
            tp: Take profit price (0 = no TP)
            comment: Order comment
            magic: Magic number for order identification

        Returns:
            Order result dict or None on failure
        """
        if not self.ensure_connected():
            return None

        symbol = symbol or self.settings.symbol
        tick = mt5.symbol_info_tick(symbol)

        if tick is None:
            logger.error(f"Cannot get price for {symbol}")
            return None

        # Determine price based on order type
        if order_type.upper() == "BUY":
            price = tick.ask
            mt5_type = mt5.ORDER_TYPE_BUY
        elif order_type.upper() == "SELL":
            price = tick.bid
            mt5_type = mt5.ORDER_TYPE_SELL
        else:
            logger.error(f"Invalid order type: {order_type}")
            return None

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": volume,
            "type": mt5_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,  # Max price deviation in points
            "magic": magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result is None:
            logger.error(f"Order send returned None: {mt5.last_error()}")
            return None

        result_dict = {
            "retcode": result.retcode,
            "deal": result.deal,
            "order": result.order,
            "volume": result.volume,
            "price": result.price,
            "comment": result.comment,
        }

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.success(
                f"✅ {order_type} {volume} lots {symbol} @ {result.price} "
                f"| SL: {sl} | TP: {tp} | Ticket: {result.order}"
            )
        else:
            logger.error(
                f"❌ Order failed: {result.retcode} — {result.comment}"
            )

        return result_dict

    def modify_position(
        self,
        ticket: int,
        sl: float = 0.0,
        tp: float = 0.0,
    ) -> bool:
        """Modify SL/TP of an existing position."""
        if not self.ensure_connected():
            return False

        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "position": ticket,
            "sl": sl,
            "tp": tp,
        }

        result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.info(f"Modified position {ticket} | SL: {sl} | TP: {tp}")
            return True

        error = result.comment if result else mt5.last_error()
        logger.error(f"Failed to modify position {ticket}: {error}")
        return False

    def close_position(
        self,
        ticket: int,
        volume: float | None = None,
        comment: str = "AI_BOT_CLOSE",
    ) -> bool:
        """
        Close an open position (full or partial).

        Args:
            ticket: Position ticket number
            volume: Volume to close (None = close entire position)
            comment: Close comment
        """
        if not self.ensure_connected():
            return False

        # Get current position info
        positions = mt5.positions_get(ticket=ticket)
        if not positions:
            logger.error(f"Position {ticket} not found")
            return False

        position = positions[0]
        close_volume = volume if volume else position.volume
        symbol = position.symbol

        # Determine close order type (opposite of position)
        if position.type == mt5.ORDER_TYPE_BUY:
            close_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(symbol).bid
        else:
            close_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": close_volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 20,
            "magic": position.magic,
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            logger.success(
                f"Closed position {ticket} | "
                f"Volume: {close_volume} | "
                f"P&L: ${position.profit:+.2f}"
            )
            return True

        error = result.comment if result else mt5.last_error()
        logger.error(f"Failed to close position {ticket}: {error}")
        return False

    def close_all_positions(self, symbol: str | None = None) -> int:
        """Close all open positions. Returns count of successfully closed."""
        positions = self.get_open_positions(symbol)
        closed = 0
        for pos in positions:
            if self.close_position(pos["ticket"]):
                closed += 1
        logger.info(f"Closed {closed}/{len(positions)} positions")
        return closed

    # ── Context Manager ──────────────────────────────────────────────────

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
