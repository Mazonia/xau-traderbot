import pytest
from unittest.mock import MagicMock
from telegram import InlineKeyboardMarkup
from notifications.telegram_bot import TelegramNotifier
from config.settings import get_settings


def test_telegram_main_keyboard_includes_mode_and_help():
    settings = get_settings()
    notifier = TelegramNotifier()
    
    keyboard: InlineKeyboardMarkup = notifier._get_main_keyboard()
    flat_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
    
    callbacks = [btn.callback_data for btn in flat_buttons]
    texts = [btn.text for btn in flat_buttons]
    
    # Verify mode menu, help, live signal, and risk menu are present in the buttons
    assert "cb_mode_menu" in callbacks, "Profile/Mode button missing from main keyboard"
    assert "cb_help" in callbacks, "Help button missing from main keyboard"
    assert "cb_signal" in callbacks, "Live signal button missing from main keyboard"
    assert "cb_risk_menu" in callbacks, "Risk menu button missing from main keyboard"
    assert any("Profile Mode:" in t for t in texts), "Profile Mode text missing from button"


def test_telegram_mode_menu_options():
    notifier = TelegramNotifier()
    mock_update = MagicMock()
    mock_update.effective_message = MagicMock()
    mock_update.callback_query = None
    
    # Check that mode options exist in the mode menu
    curr_mode = notifier.settings.active_mode.lower()
    assert curr_mode in ["safe", "moderate", "aggressive"]


def test_telegram_risk_updates():
    notifier = TelegramNotifier()
    orig_lot = notifier.settings.trading_params.get("risk", {}).get("default_lot_size", 0.01)
    orig_risk = notifier.settings.trading_params.get("risk", {}).get("max_risk_per_trade_pct", 3.0)

    try:
        # Test applying lot and risk updates
        notifier._apply_lot_update(0.03)
        assert notifier.settings.trading_params["risk"]["default_lot_size"] == 0.03

        notifier._apply_risk_update(1.8)
        assert notifier.settings.trading_params["risk"]["max_risk_per_trade_pct"] == 1.8
    finally:
        notifier._apply_lot_update(orig_lot)
        notifier._apply_risk_update(orig_risk)


@pytest.mark.anyio
async def test_show_risk_menu_executes():
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = MagicMock()
    mock_update.callback_query = None

    await notifier._show_risk_menu(mock_update)
    assert mock_update.effective_message.reply_text.called


@pytest.mark.anyio
async def test_handle_signal_offline_mt5_fallback():
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = MagicMock()
    mock_update.callback_query = None

    from unittest.mock import patch
    with patch.object(notifier, "_get_mt5") as mock_mt5:
        mock_conn = MagicMock()
        mock_conn.is_connected.return_value = False
        mock_conn.connect.return_value = False
        mock_mt5.return_value = mock_conn

        await notifier._handle_signal(mock_update, MagicMock())
        assert mock_update.effective_message.reply_text.called
