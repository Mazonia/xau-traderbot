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


@pytest.mark.anyio
async def test_handle_start_authorized_and_unauthorized():
    from unittest.mock import AsyncMock
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    # Authorized user
    mock_auth = MagicMock()
    mock_auth.effective_chat.id = 123456
    mock_auth.effective_user.id = 123456
    mock_auth.effective_message = MagicMock()
    mock_auth.effective_message.reply_text = AsyncMock()
    mock_auth.callback_query = None

    await notifier._handle_start(mock_auth, MagicMock())
    assert mock_auth.effective_message.reply_text.called

    # Unauthorized user
    mock_unauth = MagicMock()
    mock_unauth.effective_chat.id = 999999
    mock_unauth.effective_user.id = 999999
    mock_unauth.effective_message = MagicMock()
    mock_unauth.effective_message.reply_text = AsyncMock()
    mock_unauth.callback_query = None

    await notifier._handle_start(mock_unauth, MagicMock())
    assert "Access Denied" in str(mock_unauth.effective_message.reply_text.call_args)


@pytest.mark.anyio
async def test_handle_status_with_mock_account():
    from unittest.mock import AsyncMock
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = MagicMock()
    mock_update.effective_message.reply_text = AsyncMock()
    mock_update.callback_query = None

    from unittest.mock import patch
    with patch.object(notifier, "_get_mt5") as mock_mt5, patch.object(notifier, "_sync_mt5_deals_safe"):
        conn = MagicMock()
        conn.is_connected.return_value = True
        conn.get_account_info.return_value = {
            "balance": 10000.0,
            "equity": 10050.0,
            "profit": 50.0,
            "margin_level": 500.0,
            "free_margin": 9800.0,
        }
        mock_mt5.return_value = conn

        await notifier._handle_status(mock_update, MagicMock())
        assert mock_update.effective_message.reply_text.called
        call_text = mock_update.effective_message.reply_text.call_args[1].get("text", "")
        assert "$10,000.00" in call_text
        assert "$10,050.00" in call_text


@pytest.mark.anyio
async def test_mt5_visibility_controls():
    from unittest.mock import AsyncMock
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = MagicMock()
    mock_update.effective_message.reply_text = AsyncMock()
    mock_update.callback_query = None

    from unittest.mock import patch
    with patch.object(notifier, "_get_mt5") as mock_mt5:
        conn = MagicMock()
        conn.toggle_terminal_visibility.return_value = True
        conn.is_terminal_visible.return_value = True
        mock_mt5.return_value = conn

        await notifier._handle_toggle_mt5(mock_update, MagicMock())
        assert conn.toggle_terminal_visibility.called
        assert mock_update.effective_message.reply_text.called

        await notifier._handle_show_mt5(mock_update, MagicMock())
        assert conn.show_terminal.called

        await notifier._handle_hide_mt5(mock_update, MagicMock())
        assert conn.hide_terminal.called


@pytest.mark.anyio
async def test_pause_and_resume_controls():
    from unittest.mock import AsyncMock
    bot_mock = MagicMock()
    bot_mock._trading_paused = False
    notifier = TelegramNotifier(bot_instance=bot_mock)
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = MagicMock()
    mock_update.effective_message.reply_text = AsyncMock()
    mock_update.callback_query = None

    await notifier._handle_pause(mock_update, MagicMock())
    assert bot_mock._trading_paused is True
    assert mock_update.effective_message.reply_text.called

    await notifier._handle_resume(mock_update, MagicMock())
    assert bot_mock._trading_paused is False


@pytest.mark.anyio
async def test_webapp_handler():
    from unittest.mock import AsyncMock
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_update.effective_message = MagicMock()
    mock_update.effective_message.reply_text = AsyncMock()
    mock_update.callback_query = None

    await notifier._handle_webapp(mock_update, MagicMock())
    assert mock_update.effective_message.reply_text.called


@pytest.mark.anyio
async def test_callback_router_dispatch():
    notifier = TelegramNotifier()
    notifier.authorized_ids = {"123456"}

    mock_update = MagicMock()
    mock_update.effective_chat.id = 123456
    mock_update.effective_user.id = 123456
    mock_cb = MagicMock()
    mock_cb.data = "cb_menu"
    mock_update.callback_query = mock_cb

    from unittest.mock import patch, AsyncMock
    mock_cb.answer = AsyncMock()
    mock_cb.edit_message_text = AsyncMock()

    with patch.object(notifier, "_handle_start", new_callable=AsyncMock) as mock_start:
        await notifier._callback_router(mock_update, MagicMock())
        assert mock_start.called

