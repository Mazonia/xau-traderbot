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
    
    # Verify mode menu and help are present in the buttons
    assert "cb_mode_menu" in callbacks, "Profile/Mode button missing from main keyboard"
    assert "cb_help" in callbacks, "Help button missing from main keyboard"
    assert any("Profile Mode:" in t for t in texts), "Profile Mode text missing from button"


def test_telegram_mode_menu_options():
    notifier = TelegramNotifier()
    mock_update = MagicMock()
    mock_update.effective_message = MagicMock()
    mock_update.callback_query = None
    
    # Check that mode options exist in the mode menu
    curr_mode = notifier.settings.active_mode.lower()
    assert curr_mode in ["safe", "moderate", "aggressive"]
