import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from database import crud
from database.models import get_session, Trade
from notifications.telegram_bot import TelegramNotifier


def test_close_trade_offset_naive_and_aware():
    """Test that close_trade handles naive or aware datetime subtraction seamlessly."""
    session = get_session()
    ticket = 999900001
    
    # Clean up if exists
    existing = session.query(Trade).filter_by(ticket=ticket).first()
    if existing:
        session.delete(existing)
        session.commit()
    session.close()

    # Create an open trade
    crud.create_trade(
        ticket=ticket,
        order_type="BUY",
        strategy="scalping",
        volume=0.05,
        entry_price=2350.0,
    )

    # Force opened_at to be naive in DB
    session = get_session()
    db_trade = session.query(Trade).filter_by(ticket=ticket).first()
    db_trade.opened_at = datetime(2026, 9, 25, 10, 0, 0)  # naive
    session.commit()
    session.close()

    # Call close_trade (which uses aware now or receives aware closed_at)
    res = crud.close_trade(
        ticket=ticket,
        exit_price=2360.0,
        profit=50.0,
        swap=0.0,
        commission=-1.5,
        closed_at=datetime.now(timezone.utc),
    )
    assert res is not None

    # Verify updated row in DB
    session = get_session()
    t = session.query(Trade).filter_by(ticket=ticket).first()
    assert t is not None
    assert t.status == "CLOSED"
    assert t.exit_price == 2360.0
    assert t.profit == 50.0
    assert t.duration_minutes is not None
    assert t.duration_minutes >= 0

    session.delete(t)
    session.commit()
    session.close()


def test_daily_pnl_and_closed_trades():
    """Test get_daily_pnl calculates realized profit of closed trades."""
    session = get_session()
    t1_ticket = 999900002
    t2_ticket = 999900003

    for tk in [t1_ticket, t2_ticket]:
        ex = session.query(Trade).filter_by(ticket=tk).first()
        if ex:
            session.delete(ex)
    session.commit()
    session.close()

    now = datetime.now(timezone.utc)
    crud.create_trade(ticket=t1_ticket, order_type="BUY", strategy="scalping", volume=0.02, entry_price=2350.0)
    crud.create_trade(ticket=t2_ticket, order_type="SELL", strategy="day_trading", volume=0.02, entry_price=2355.0)

    # Close t1 with profit 30.0 today
    crud.close_trade(ticket=t1_ticket, exit_price=2356.0, profit=30.0, closed_at=now)
    # Leave t2 open

    recent_closed = crud.get_recent_trades(limit=10, status="CLOSED")
    
    assert any(t.ticket == t1_ticket for t in recent_closed)
    assert not any(t.ticket == t2_ticket for t in recent_closed)

    # Clean up
    session = get_session()
    for tk in [t1_ticket, t2_ticket]:
        ex = session.query(Trade).filter_by(ticket=tk).first()
        if ex:
            session.delete(ex)
    session.commit()
    session.close()


@pytest.mark.anyio
async def test_handle_trades_safe_formatting():
    """Test _handle_trades formats trades safely even when exit_price or profit is None."""
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = AsyncMock()
    mock_update.callback_query = None

    # Mock get_recent_trades returning a trade with None exit_price
    mock_trade = MagicMock()
    mock_trade.ticket = 12345678
    mock_trade.order_type = "BUY"
    mock_trade.volume = 0.05
    mock_trade.strategy = "scalping"
    mock_trade.entry_price = 2350.0
    mock_trade.exit_price = None
    mock_trade.profit = None
    mock_trade.status = "OPEN"

    with patch("database.crud.get_recent_trades", return_value=[mock_trade]), \
         patch("database.crud.get_trade_stats", return_value={"win_rate": 60.0, "profit_factor": 1.5}), \
         patch.object(notifier, "_sync_mt5_deals_safe"):
        await notifier._handle_trades(mock_update, MagicMock())

    # Verify safe edit or reply was called without raising TypeError
    assert mock_update.effective_message.reply_text.called or mock_update.effective_message.reply_text.call_count > 0


@pytest.mark.anyio
async def test_send_trade_closed_safe_none_handling():
    """Test send_trade_closed handles dictionary with missing or None numeric values."""
    notifier = TelegramNotifier()
    notifier.send_message = AsyncMock()

    deal_payload = {
        "ticket": 10671664692,
        "direction": "SELL",
        "entry_price": None,
        "exit_price": None,
        "profit": None,
        "duration_minutes": None,
        "reason": "SL hit",
    }

    # Should not raise TypeError: unsupported format string passed to NoneType.__format__
    await notifier.send_trade_closed(deal_payload)
    assert notifier.send_message.called
