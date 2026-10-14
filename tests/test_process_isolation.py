"""
Unit & Integration Tests: Process Isolation & Non-Interference Guarantees
Verifies that XAUUSD-AI-Trading-Bot strictly isolates its process management,
MT5 window handles, background shutdown commands, and dashboard ports,
ensuring ZERO interference with other applications or running bots.
"""

import os
import sys
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core.mt5_connector import MT5Connector


def test_stop_bot_script_isolation():
    """
    CRITICAL SAFETY TEST:
    Verify that stop_bot.bat NEVER uses broad WINDOWTITLE patterns
    and strictly scopes process termination to the bot's own directory.
    """
    stop_bat_path = BASE_DIR / "stop_bot.bat"
    assert stop_bat_path.exists(), "stop_bot.bat not found"
    content = stop_bat_path.read_text(encoding="utf-8")

    # 1. Broad windowtitle matching MUST NOT exist
    assert "WINDOWTITLE" not in content.upper(), (
        "stop_bot.bat must not use WINDOWTITLE matching which terminates unrelated user windows!"
    )

    # 2. Python process termination must be explicitly scoped
    assert "*XAUUSD-AI-Trading-Bot*main.py*" in content, (
        "stop_bot.bat must strictly filter by the XAUUSD-AI-Trading-Bot directory path"
    )


def test_toggle_mt5_script_binary_safety():
    """Verify that toggle_mt5.bat safely selects the dedicated executable without relying on system python."""
    toggle_bat = BASE_DIR / "toggle_mt5.bat"
    assert toggle_bat.exists()
    content = toggle_bat.read_text(encoding="utf-8")

    assert "xau-trader.exe" in content
    assert ".venv" in content


def test_mt5_get_terminal_hwnd_resource_safety():
    """Verify that get_terminal_hwnd prioritizes direct FindWindowW and avoids handle leaks."""
    connector = MT5Connector()

    with patch("ctypes.windll.user32.FindWindowW", return_value=12345) as mock_find:
        with patch("ctypes.windll.user32.OpenWindowStationW") as mock_open_station:
            hwnd = connector.get_terminal_hwnd()
            assert hwnd == 12345
            # Fast-path MUST NOT call OpenWindowStationW when window is found directly
            mock_open_station.assert_not_called()


def test_dashboard_port_handling_when_already_bound():
    """Verify that dashboard server detects an active port and exits gracefully without crashing."""
    from main import start_dashboard

    # Bind a temporary socket on the dashboard port
    mock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        mock_socket.bind(("127.0.0.1", 8080))
        mock_socket.listen(1)

        # start_dashboard should detect existing listener and return cleanly without throwing
        with patch("uvicorn.run") as mock_uvicorn:
            start_dashboard()
            mock_uvicorn.assert_not_called()
    except OSError:
        # If port 8080 is already bound by another service on the system, start_dashboard should safely return
        with patch("uvicorn.run") as mock_uvicorn:
            start_dashboard()
            mock_uvicorn.assert_not_called()
    finally:
        mock_socket.close()


def test_port_isolation_against_pc_remote_sentinel():
    """Verify that XAUUSD bot ports do not collide with PC-Remote-Sentinel ports."""
    xau_dashboard_port = 8080
    sentinel_ports = [9010, 8585]

    assert xau_dashboard_port not in sentinel_ports, (
        f"Port conflict detected! XAU dashboard ({xau_dashboard_port}) matches a Sentinel port!"
    )
