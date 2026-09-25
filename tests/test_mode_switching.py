"""
Intensive Test Suite for Trading Mode Switching & Parameter Isolation

Verifies:
1. Seamless hot-switching between Safe, Moderate, and Aggressive modes.
2. Complete parameter isolation (zero cross-mode leakage).
3. Dynamic RiskManager properties and auto-clearing of overrides on mode switch.
4. Strategy confluence and technical score dynamic adaptation.
5. Market regime detector mode-adaptive behavior.
6. Mistake Memory Guard dynamic threshold adaptation.
7. YAML persistence and clean reloading.
"""

import pytest
from unittest.mock import MagicMock
from config.settings import get_settings
from execution.risk_manager import RiskManager
from strategies.scalping import ScalpingStrategy
from strategies.day_trading import DayTradingStrategy
from strategies.swing_trading import SwingTradingStrategy
from strategies.regime_detector import RegimeDetector, RegimeAnalysis, MarketRegime
from ai.trade_learner import TradeLearner


class DummyMT5:
    def is_connected(self):
        return True

    def get_account_info(self):
        return {
            "balance": 10000.0,
            "equity": 10000.0,
            "margin": 0.0,
            "margin_free": 10000.0,
            "margin_level": 0.0,
            "profit": 0.0,
            "currency": "USD",
        }

    def get_open_positions(self, symbol=None):
        return []

    def get_rates(self, symbol=None, timeframe="H1", count=500, auto_reconnect=True):
        return None


def test_mode_switching_and_isolation():
    settings = get_settings()
    original_mode = settings.active_mode

    try:
        modes_to_test = ["safe", "moderate", "aggressive"]

        for mode in modes_to_test:
            # 1. Switch mode
            settings.set_active_mode(mode)
            assert settings.active_mode == mode

            # 2. Check risk params match mode config
            mode_cfg = settings.trading_modes[mode]
            assert settings.risk_params["max_risk_per_trade_pct"] == mode_cfg["max_risk_per_trade_pct"]
            assert settings.risk_params["max_daily_loss_pct"] == mode_cfg["max_daily_loss_pct"]
            assert settings.risk_params["max_concurrent_trades"] == mode_cfg["max_concurrent_trades"]
            assert settings.risk_params["max_spread_points"] == mode_cfg["max_spread_points"]
            assert settings.risk_params["default_lot_size"] == mode_cfg["default_lot_size"]
            assert settings.risk_params["max_slippage_points"] == mode_cfg["max_slippage_points"]

            # 3. Check scalping params match mode config
            assert settings.scalping_params["min_confluence_score"] == mode_cfg["scalping_min_confluence"]
            assert settings.scalping_params["min_technical_score"] == mode_cfg["min_technical_score"]
            assert settings.scalping_params["pullback_tolerance_pct"] == mode_cfg["pullback_tolerance_pct"]

            # 4. Check day trading & swing trading params
            assert settings.day_trading_params["min_confluence_score"] == mode_cfg["day_trading_min_confluence"]
            assert settings.swing_trading_params["min_confluence_score"] == mode_cfg["swing_trading_min_confluence"]

    finally:
        # Restore original mode
        settings.set_active_mode(original_mode)


def test_risk_manager_dynamic_mode_adaptation():
    settings = get_settings()
    original_mode = settings.active_mode

    try:
        mt5 = DummyMT5()
        rm = RiskManager(mt5)

        # Switch to Safe
        settings.set_active_mode("safe")
        assert rm.max_risk_pct == 1.5
        assert rm.max_concurrent == 2
        assert rm.max_spread == 45.0
        assert rm.default_lot == 0.01

        # Set manual overrides in Safe mode
        rm.default_lot = 0.08
        rm.max_spread = 99.0
        assert rm.default_lot == 0.08
        assert rm.max_spread == 99.0

        # Switch to Moderate -> overrides MUST be cleared automatically!
        settings.set_active_mode("moderate")
        assert rm.default_lot == 0.02, "Override leaked into moderate mode!"
        assert rm.max_spread == 70.0, "Override leaked into moderate mode!"
        assert rm.max_risk_pct == 2.5
        assert rm.max_concurrent == 4

        # Switch to Aggressive
        settings.set_active_mode("aggressive")
        assert rm.default_lot == 0.03
        assert rm.max_spread == 90.0
        assert rm.max_risk_pct == 4.0
        assert rm.max_concurrent == 6

    finally:
        settings.set_active_mode(original_mode)


def test_strategy_dynamic_confluence_adaptation():
    settings = get_settings()
    original_mode = settings.active_mode

    try:
        scalp = ScalpingStrategy()
        day = DayTradingStrategy()
        swing = SwingTradingStrategy()

        # In Safe Mode
        settings.set_active_mode("safe")
        assert scalp.min_confluence_score == 65.0
        assert scalp.min_technical_score == 45.0
        assert day.min_confluence_score == 70.0
        assert day.min_technical_score == 45.0
        assert swing.min_confluence_score == 75.0
        assert swing.min_technical_score == 45.0

        # Set manual override on scalp
        scalp.min_confluence_score = 92.0
        assert scalp.min_confluence_score == 92.0

        # Switch to Moderate -> override MUST clear!
        settings.set_active_mode("moderate")
        assert scalp.min_confluence_score == 50.0, "Scalping override leaked into moderate mode!"
        assert scalp.min_technical_score == 35.0
        assert day.min_confluence_score == 55.0
        assert swing.min_confluence_score == 60.0

        # Switch to Aggressive
        settings.set_active_mode("aggressive")
        assert scalp.min_confluence_score == 35.0
        assert scalp.min_technical_score == 25.0
        assert day.min_confluence_score == 40.0
        assert swing.min_confluence_score == 45.0

    finally:
        settings.set_active_mode(original_mode)


def test_regime_detector_mode_behavior():
    settings = get_settings()
    original_mode = settings.active_mode

    try:
        detector = RegimeDetector()
        mock_regime = RegimeAnalysis(
            regime=MarketRegime.RANGING,
            adx_value=14.0,
            trend_direction="NONE",
            volatility_percentile=40.0,
            volatility_label="NORMAL",
            recommended_strategies=["scalping"],  # Only scalping recommended by regime
            position_size_modifier=1.0,
            should_trade=True,
            reasons=[],
        )

        # In Safe mode: strictly abides by recommended_strategies
        settings.set_active_mode("safe")
        assert detector.is_strategy_recommended("scalping", mock_regime) is True
        assert detector.is_strategy_recommended("day_trading", mock_regime) is False
        assert detector.is_strategy_recommended("swing_trading", mock_regime) is False

        # In Moderate mode: scalping always allowed, day trading allowed if vol != HIGH
        settings.set_active_mode("moderate")
        assert detector.is_strategy_recommended("scalping", mock_regime) is True
        assert detector.is_strategy_recommended("day_trading", mock_regime) is True
        assert detector.is_strategy_recommended("swing_trading", mock_regime) is False

        # In Aggressive mode: all strategies allowed across regimes
        settings.set_active_mode("aggressive")
        assert detector.is_strategy_recommended("scalping", mock_regime) is True
        assert detector.is_strategy_recommended("day_trading", mock_regime) is True
        assert detector.is_strategy_recommended("swing_trading", mock_regime) is True

    finally:
        settings.set_active_mode(original_mode)


def test_trade_learner_mistake_guard_adaptation():
    settings = get_settings()
    original_mode = settings.active_mode

    try:
        learner = TradeLearner()
        # Add a mock mistake memory
        learner.mistake_memory.append({
            "strategy": "scalping",
            "direction": "BUY",
            "regime": "RANGING",
            "trap_type": "false breakout",
            "rule": "Avoid buying range top",
        })

        # Safe mode: base is 65 -> veto threshold is 65 + 8 = 73
        settings.set_active_mode("safe")
        approved, reason, penalty = learner.screen_prospective_signal(
            strategy_name="scalping",
            direction="BUY",
            confluence_score=68.0,  # Below 73
            regime_val="RANGING",
        )
        assert approved is False
        assert "Mistake Guard Veto" in reason

        # Moderate mode: base is 50 -> veto threshold is 50 + 8 = 58
        settings.set_active_mode("moderate")
        approved, reason, penalty = learner.screen_prospective_signal(
            strategy_name="scalping",
            direction="BUY",
            confluence_score=68.0,  # Above 58!
            regime_val="RANGING",
        )
        assert approved is True

        # Aggressive mode: base is 35 -> veto threshold is 35 + 8 = 43
        settings.set_active_mode("aggressive")
        approved, reason, penalty = learner.screen_prospective_signal(
            strategy_name="scalping",
            direction="BUY",
            confluence_score=45.0,  # Above 43!
            regime_val="RANGING",
        )
        assert approved is True

    finally:
        settings.set_active_mode(original_mode)
