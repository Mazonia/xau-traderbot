"""
Unit tests for Risk Manager (Position sizing, daily loss limit, margin safety).
"""

from unittest.mock import MagicMock
import pytest

from execution.risk_manager import RiskManager


@pytest.fixture
def mock_mt5():
    """Create a mock MT5 connector."""
    mock = MagicMock()
    mock.get_account_info.return_value = {
        "login": 12345678,
        "balance": 10_000.0,
        "equity": 10_000.0,
        "margin": 200.0,
        "margin_free": 9_800.0,
        "margin_level": 5000.0,
        "profit": 0.0,
        "trade_allowed": True,
    }
    mock.get_symbol_info.return_value = {
        "name": "XAUUSD",
        "trade_contract_size": 100,
        "point": 0.01,
        "volume_step": 0.01,
        "volume_min": 0.01,
        "volume_max": 100.0,
        "spread": 20,
    }
    mock.get_open_positions.return_value = []
    mock.get_current_tick.return_value = {
        "bid": 2650.0,
        "ask": 2650.25,
        "spread": 25,
    }
    return mock


def test_can_trade_normal_conditions(mock_mt5):
    rm = RiskManager(mock_mt5)
    allowed, reason = rm.can_trade("XAUUSD")
    assert allowed is True
    assert "passed" in reason.lower()


def test_cannot_trade_low_free_margin(mock_mt5):
    mock_mt5.get_account_info.return_value = {
        "balance": 10_000.0,
        "equity": 4_000.0,
        "margin": 2_000.0,
        "margin_free": 2_000.0,  # Only 20% of balance (min is 50%)
        "trade_allowed": True,
    }
    rm = RiskManager(mock_mt5)
    allowed, reason = rm.can_trade("XAUUSD")
    assert allowed is False
    assert "margin" in reason.lower()


def test_cannot_trade_excessive_spread(mock_mt5):
    mock_mt5.get_current_tick.return_value = {
        "bid": 2650.0,
        "ask": 2650.95,
        "spread": 95,  # Exceeds max_spread
    }
    rm = RiskManager(mock_mt5)
    allowed, reason = rm.can_trade("XAUUSD")
    assert allowed is False
    assert "spread" in reason.lower()


def test_calculate_lot_size(mock_mt5):
    rm = RiskManager(mock_mt5)
    entry_price = 2650.0
    stop_loss = 2640.0  # 10 dollar / 1000 point distance
    lot = rm.calculate_lot_size(entry_price, stop_loss, symbol="XAUUSD")
    # Balance: 10,000, 2.5% risk = $250 risk.
    # $250 / ($10 * 100) = 0.25 lots.
    assert 0.01 <= lot <= rm.max_lot
    assert round(lot, 2) == lot


def test_can_trade_zero_margin_positions(mock_mt5):
    """Test that account with 0 open positions (margin=0.0, margin_level=0.0 in MT5) passes risk check."""
    mock_mt5.get_account_info.return_value = {
        "login": 12345678,
        "balance": 100_000.0,
        "equity": 100_000.0,
        "margin": 0.0,
        "free_margin": 100_000.0,
        "margin_level": 0.0,  # MT5 default when margin is 0
        "profit": 0.0,
        "trade_allowed": True,
    }
    mock_mt5.get_current_tick.return_value = {
        "bid": 2650.0,
        "ask": 2650.25,
        "spread": 25,
    }
    rm = RiskManager(mock_mt5)
    allowed, reason = rm.can_trade("XAUUSD")
    assert allowed is True
    assert "passed" in reason.lower()


def test_trading_modes_switching(mock_mt5):
    """Test that switching trading modes alters risk parameters dynamically."""
    from config.settings import get_settings
    settings = get_settings()
    
    # Safe Mode
    settings.set_active_mode("safe")
    rm = RiskManager(mock_mt5)
    assert rm.max_risk_pct == 1.5
    assert rm.max_spread == 45.0
    assert rm.max_concurrent == 2

    # Moderate Mode
    settings.set_active_mode("moderate")
    assert rm.max_risk_pct == 2.5
    assert rm.max_spread == 70.0
    assert rm.max_concurrent == 4

    # Aggressive Mode
    settings.set_active_mode("aggressive")
    assert rm.max_risk_pct == 4.0
    assert rm.max_spread == 90.0
    assert rm.max_concurrent == 6

    # Return to moderate
    settings.set_active_mode("moderate")
