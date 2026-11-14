"""
Unit Tests for Federated Learning & Multi-Tenant Risk Normalization (v3)
"""

import json
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

from ai.trade_learner import TradeLearner
from ai.federated_sync import FederatedSync
from scripts.sync_hub import app, load_all_lessons, save_all_lessons


@pytest.fixture
def learner(tmp_path):
    tl = TradeLearner()
    tl.reset_adaptive_state()
    # Point federated pool to a temporary file
    tl.federated_sync.pool_path = tmp_path / "test_pool.json"
    return tl


def test_normalized_risk_conservative_user(learner):
    """Conservative user with normal lot size and sound risk management."""
    trade_data = {
        "profit": 40.0,
        "volume": 0.02,
        "entry_price": 2700.0,
        "stop_loss": 2680.0,
        "balance": 5000.0,
    }
    metrics = learner._calculate_normalized_risk(trade_data)
    assert metrics["recklessness_tier"] == "CONSERVATIVE"
    assert metrics["sanity_weight"] == 1.00
    assert metrics["risk_pct"] < 2.0
    assert metrics["r_multiple"] == pytest.approx(1.0, 0.1)


def test_normalized_risk_reckless_user(learner):
    """Reckless user trading oversized lot on a micro balance."""
    trade_data = {
        "profit": -150.0,
        "volume": 0.50,
        "entry_price": 2700.0,
        "stop_loss": 2690.0,
        "balance": 250.0,
    }
    metrics = learner._calculate_normalized_risk(trade_data)
    assert metrics["recklessness_tier"] == "RECKLESS"
    assert metrics["sanity_weight"] == 0.20
    assert metrics["risk_pct"] > 50.0  # Massive risk relative to equity


def test_reckless_loss_does_not_destroy_strategy_multiplier(learner):
    """
    Crucial test: If a reckless gambler blows up their account with huge lots,
    the bot must NOT heavily penalize the strategy because the fault was sizing.
    """
    # 1. Simulate a normal disciplined loss
    learner.strategy_multipliers["scalping"] = 1.0
    normal_loss = {
        "ticket": 1001,
        "strategy": "scalping",
        "direction": "BUY",
        "profit": -20.0,
        "volume": 0.02,
        "entry_price": 2700.0,
        "stop_loss": 2690.0,
        "balance": 2000.0,
        "regime": "TREND_UP",
        "confluence_score": 75.0,
    }
    learner.on_trade_closed(normal_loss)
    normal_mult = learner.strategy_multipliers["scalping"]
    # Normal loss should decay multiplier significantly (~0.78x)
    assert normal_mult < 0.85

    # 2. Reset and simulate reckless loss with same strategy
    learner.strategy_multipliers["scalping"] = 1.0
    reckless_loss = {
        "ticket": 1002,
        "strategy": "scalping",
        "direction": "BUY",
        "profit": -300.0,
        "volume": 0.80,  # Extreme lot
        "entry_price": 2700.0,
        "stop_loss": 2695.0,
        "balance": 400.0,  # Micro account
        "regime": "TREND_UP",
        "confluence_score": 75.0,
    }
    res = learner.on_trade_closed(reckless_loss)
    reckless_mult = learner.strategy_multipliers["scalping"]

    # Reckless multiplier should remain much higher because sanity_weight was 0.20
    assert reckless_mult > normal_mult
    assert reckless_mult > 0.90
    assert res["category"] == "OVERSIZED_LOT_BLOWOUT"


def test_slippage_spread_expansion_diagnostic(learner):
    """Detects when an exit slipped far past planned SL distance."""
    trade_data = {
        "ticket": 1003,
        "strategy": "day_trading",
        "direction": "BUY",
        "profit": -55.0,
        "volume": 0.02,
        "entry_price": 2700.0,
        "stop_loss": 2690.0,  # Initial planned risk = 10 * 100 * 0.02 = $20
        "balance": 2000.0,    # Loss $55 is -2.75R!
        "regime": "TREND_UP",
        "confluence_score": 76.0,
    }
    res = learner.on_trade_closed(trade_data)
    assert res["category"] == "SLIPPAGE_SPREAD_EXPANSION"
    assert res["r_multiple"] < -1.4


def test_federated_sync_aggregation_and_blending(tmp_path):
    """Test multi-lesson aggregation and weight blending."""
    pool_file = tmp_path / "sync_pool.json"
    fed = FederatedSync()
    fed.pool_path = pool_file

    sample_lessons = [
        {
            "strategy": "scalping",
            "outcome": "WIN",
            "r_multiple": 1.5,
            "sanity_weight": 1.0,
            "confluence_score": 78.0,
            "regime": "TREND_UP",
        },
        {
            "strategy": "scalping",
            "outcome": "WIN",
            "r_multiple": 1.2,
            "sanity_weight": 1.0,
            "confluence_score": 74.0,
            "regime": "TREND_UP",
        },
        {
            "strategy": "day_trading",
            "outcome": "LOSS",
            "r_multiple": -1.0,
            "sanity_weight": 1.0,
            "confluence_score": 70.0,
            "regime": "RANGING",
            "mistake_category": "COUNTER_REGIME_FADE",
            "mistake_signature": {"trap_type": "counter_trend", "direction": "SELL"},
            "defensive_rule": "Do not sell into uptrend",
        },
        # Reckless trade: should have almost no effect
        {
            "strategy": "swing_trading",
            "outcome": "LOSS",
            "r_multiple": -2.0,
            "sanity_weight": 0.15,
            "confluence_score": 50.0,
            "regime": "RANGING",
            "mistake_category": "OVERSIZED_LOT_BLOWOUT",
        },
    ]

    consensus = fed.aggregate_lessons(sample_lessons)
    assert consensus["strategy_multipliers"]["scalping"] > 1.0
    assert consensus["strategy_multipliers"]["day_trading"] < 1.0
    # Swing trading barely budged because sanity_weight was 0.15
    assert consensus["strategy_multipliers"]["swing_trading"] > 0.95

    # Test blending
    local_mults = {"scalping": 1.0, "day_trading": 1.0, "swing_trading": 1.0}
    blended = fed.blend_multipliers(local_mults, consensus["strategy_multipliers"])
    assert blended["scalping"] > 1.0


def test_sync_hub_fastapi_endpoints(tmp_path, monkeypatch):
    """Test the standalone cloud sync hub API."""
    test_db = tmp_path / "test_hub_data.json"
    monkeypatch.setattr("scripts.sync_hub.DATA_STORE", test_db)

    client = TestClient(app)

    # 1. Health check
    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"

    # 2. Submit lesson
    payload = {
        "client_id": "test_node_alpha",
        "ticket_hash": "hash_123",
        "symbol": "XAUUSD",
        "strategy": "scalping",
        "order_type": "BUY",
        "profit": 45.0,
        "outcome": "WIN",
        "mistake_category": "WINNING_EXECUTION",
        "lesson_summary": "Clean trend follow",
        "defensive_rule": "Follow trend",
        "mistake_signature": {},
        "r_multiple": 1.5,
        "risk_pct": 1.5,
        "lot_to_balance_ratio": 0.015,
        "recklessness_tier": "CONSERVATIVE",
        "sanity_weight": 1.0,
        "confluence_score": 80.0,
        "sentiment_score": 0.3,
        "regime": "TREND_UP",
        "user_mode": "moderate",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res_post = client.post("/api/telemetry/lesson", json=payload)
    assert res_post.status_code == 200
    assert res_post.json()["status"] == "accepted"

    # 3. Get global state
    res_state = client.get("/api/telemetry/global_state")
    assert res_state.status_code == 200
    data = res_state.json()
    assert data["total_lessons"] == 1
    assert data["strategy_multipliers"]["scalping"] > 1.0

    # 4. Get stats
    res_stats = client.get("/api/telemetry/stats")
    assert res_stats.status_code == 200
    assert res_stats.json()["total_lessons"] == 1
    assert res_stats.json()["win_rate_pct"] == 100.0
