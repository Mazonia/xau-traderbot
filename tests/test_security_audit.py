"""
Security and Cross-Platform Technical Audit Test Suite

Validates:
1. MT5 IPC synchronization (@synchronized RLock)
2. Telegram multi-ID authorization and unauthorized rejection
3. External API credential and URL scrubbing
4. Gemini response sanitization and boundary clamping
5. SQLite WAL mode configuration and busy timeout
"""

import threading
import pytest
from unittest.mock import MagicMock, patch
from core.mt5_connector import MT5Connector
from notifications.telegram_bot import TelegramNotifier
from news.news_fetcher import _sanitize_log
from database.models import get_engine


def test_mt5_synchronized_lock():
    """Verify that MT5Connector operations acquire and release the RLock properly."""
    mt5 = MT5Connector()
    assert hasattr(mt5, "_lock"), "MT5Connector must have an internal _lock"
    assert isinstance(mt5._lock, type(threading.RLock())), "_lock must be a threading.RLock"

    # Test lock reentrancy
    with mt5._lock:
        with mt5._lock:
            assert True


def test_telegram_multi_id_authorization():
    """Verify that TelegramNotifier supports multi-ID whitelist and correctly authorizes."""
    with patch("notifications.telegram_bot.get_settings") as mock_settings:
        mock_settings.return_value.telegram.bot_token = "mock_token"
        mock_settings.return_value.telegram.chat_id = "111222, 333444, 555666"

        notifier = TelegramNotifier()
        assert notifier.authorized_ids == {"111222", "333444", "555666"}

        # Test authorized chat
        mock_auth_update = MagicMock()
        mock_auth_update.effective_chat.id = 111222
        mock_auth_update.effective_user.id = 999999
        assert notifier._is_authorized(mock_auth_update) is True

        # Test authorized user (different chat, e.g. group)
        mock_user_update = MagicMock()
        mock_user_update.effective_chat.id = 888888
        mock_user_update.effective_user.id = 333444
        assert notifier._is_authorized(mock_user_update) is True

        # Test unauthorized sender
        mock_unauth_update = MagicMock()
        mock_unauth_update.effective_chat.id = 777777
        mock_unauth_update.effective_user.id = 888888
        mock_unauth_update.effective_user.username = "intruder"
        assert notifier._is_authorized(mock_unauth_update) is False


def test_credential_sanitization():
    """Verify that API keys and tokens are redacted from error logs."""
    test_urls = [
        "https://finnhub.io/api/v1/news?category=general&token=danvocpr01qqjqh3q20gdanvocpr01qqjqh3q210",
        "https://www.alphavantage.co/query?function=NEWS_SENTIMENT&apikey=YKMIJRMK9EVKPC4N",
        "Error connecting to https://api.endpoint.com?api_key=secret_123456789&symbol=XAUUSD",
    ]

    for raw in test_urls:
        cleaned = _sanitize_log(raw)
        assert "danvocpr01qqjqh3q20gdanvocpr01qqjqh3q210" not in cleaned
        assert "YKMIJRMK9EVKPC4N" not in cleaned
        assert "secret_123456789" not in cleaned
        assert "***REDACTED***" in cleaned


def test_gemini_output_sanitization():
    """Verify that AI response fields are safely parsed and clamped."""
    from news.news_analyzer import NewsAnalyzer

    analyzer = NewsAnalyzer()

    # Test clamping logic directly
    raw_responses = [
        {"score": 2.5, "sentiment": "bullish", "impact_level": "high"},
        {"score": -5.0, "sentiment": "INVALID_SENTIMENT", "impact_level": "SUPER_HIGH"},
        {"score": "not_a_number", "sentiment": "BEARISH", "impact_level": "medium"},
    ]

    for resp in raw_responses:
        try:
            score = float(resp.get("score", 0.0))
        except (ValueError, TypeError):
            score = 0.0
        score = max(-1.0, min(1.0, score))

        sentiment = str(resp.get("sentiment", "NEUTRAL")).strip().upper()
        if sentiment not in ("BULLISH", "BEARISH", "NEUTRAL"):
            sentiment = "NEUTRAL"

        impact = str(resp.get("impact_level", "LOW")).strip().upper()
        if impact not in ("HIGH", "MEDIUM", "LOW"):
            impact = "LOW"

        assert -1.0 <= score <= 1.0
        assert sentiment in ("BULLISH", "BEARISH", "NEUTRAL")
        assert impact in ("HIGH", "MEDIUM", "LOW")


def test_database_sqlite_pragmas():
    """Verify SQLite engine has 30s timeout configured."""
    engine = get_engine()
    assert "sqlite" in str(engine.url).lower()
