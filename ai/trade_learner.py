"""
Continuous Self-Learning & Mistake Adaptation Engine

Equips the XAUUSD AI Trading Bot with:
1. Post-Trade Performance Attribution & Mistake Diagnostics.
2. Online Reinforcement Learning (Multi-Armed Bandit / ExpGrad) for Strategy & Confluence Weights.
3. Mistake Memory Guard: An active screening layer preventing repeating known losing setups.
4. Continuous Knowledge Persistence across restarts.
"""

import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from loguru import logger

from database import crud
from database.models import TradeLesson, AdaptiveWeight
from config.settings import get_settings


class TradeLearner:
    """
    Autonomous trade learning and adaptive optimization engine.
    Continuously monitors closed trades, diagnoses errors, adjusts weights,
    and maintains an active memory guard against market traps.
    """

    def __init__(self):
        self.settings = get_settings()
        
        # Confluence component baseline weights (sums to 100)
        self.component_weights: dict[str, float] = {
            "technical": 40.0,
            "ai_prediction": 25.0,
            "sentiment": 20.0,
            "regime": 15.0,
        }

        # Strategy performance multipliers (bounded between 0.40 and 1.60)
        self.strategy_multipliers: dict[str, float] = {
            "scalping": 1.0,
            "day_trading": 1.0,
            "swing_trading": 1.0,
        }

        # Rolling active mistake memory signatures
        self.mistake_memory: list[dict] = []
        
        # Load persisted adaptive state from database
        self._load_persisted_state()

    def _load_persisted_state(self):
        """Load saved adaptive weights and mistake history from database."""
        try:
            persisted = crud.get_all_adaptive_weights()
            for comp, data in persisted.items():
                if comp in self.component_weights:
                    self.component_weights[comp] = float(data.get("weight", self.component_weights[comp]))
                elif comp.startswith("strat_"):
                    s_name = comp.replace("strat_", "")
                    if s_name in self.strategy_multipliers:
                        self.strategy_multipliers[s_name] = float(data.get("multiplier", 1.0))

            # Load recent mistake lessons into memory guard
            lessons = crud.get_recent_lessons(limit=25)
            for l in lessons:
                if l.outcome == "LOSS" and l.mistake_signature:
                    try:
                        sig = json.loads(l.mistake_signature)
                        sig["lesson_id"] = l.id
                        sig["rule"] = l.defensive_rule
                        sig["created_at"] = l.created_at
                        self.mistake_memory.append(sig)
                    except Exception:
                        pass

            logger.info(
                f"🧠 Self-Learning Engine initialized | Adaptive Multipliers: {self.strategy_multipliers} "
                f"| Active Mistake Memories: {len(self.mistake_memory)}"
            )
        except Exception as e:
            logger.warning(f"Could not load persisted learning state (using defaults): {e}")

    # ── Post-Trade Analysis & Adaptation ──────────────────────────────────

    def on_trade_closed(self, trade_data: dict, deal_info: Optional[dict] = None) -> dict:
        """
        Main learning trigger called immediately when an MT5 trade is closed.
        Analyzes outcome, extracts mistake patterns, updates weights, and saves lessons.
        """
        ticket = trade_data.get("ticket", 0)
        profit = float(trade_data.get("profit", 0.0))
        strategy = trade_data.get("strategy", "scalping").lower()
        order_type = trade_data.get("direction") or trade_data.get("order_type") or "BUY"
        regime = trade_data.get("regime", "RANGING")
        confluence = float(trade_data.get("confluence_score", 70.0))
        sentiment = float(trade_data.get("sentiment_score", 0.0))

        # Determine outcome
        if profit > 1.0:
            outcome = "WIN"
        elif profit < -1.0:
            outcome = "LOSS"
        else:
            outcome = "SCRATCH"

        # 1. Adapt Strategy Multipliers
        current_strat_mult = self.strategy_multipliers.get(strategy, 1.0)
        if outcome == "WIN":
            # Reward successful strategy
            new_strat_mult = min(1.60, current_strat_mult * 1.05)
            lesson_cat = "WINNING_EXECUTION"
            summary = f"Successful {strategy.upper()} {order_type} execution in {regime} market. Captured +${profit:.2f} profit."
            defensive_rule = f"Maintain conviction on {strategy.upper()} when {regime} confluence exceeds {confluence:.0f}."
            sig = {}
        elif outcome == "LOSS":
            # Penalize and diagnose mistake
            new_strat_mult = max(0.40, current_strat_mult * 0.88)
            lesson_cat, summary, defensive_rule, sig = self._diagnose_mistake(
                trade_data=trade_data,
                deal_info=deal_info,
                regime=regime,
                confluence=confluence,
                sentiment=sentiment,
                profit=profit,
            )
            # Add to rolling active mistake memory
            sig["strategy"] = strategy
            sig["order_type"] = order_type
            sig["regime"] = regime
            sig["timestamp"] = datetime.now(timezone.utc).isoformat()
            self.mistake_memory.append(sig)
            if len(self.mistake_memory) > 30:
                self.mistake_memory.pop(0)
        else:
            new_strat_mult = current_strat_mult
            lesson_cat = "BREAKEVEN_EXIT"
            summary = f"Trade #{ticket} exited near breakeven (${profit:+.2f}). Capital protected."
            defensive_rule = "Continue strict trailing stop and breakeven protection."
            sig = {}

        self.strategy_multipliers[strategy] = round(new_strat_mult, 3)

        # 2. Adapt Confluence Component Weights
        self._adapt_confluence_weights(outcome=outcome, trade_data=trade_data)

        # 3. Persist Lesson to Database
        try:
            crud.save_trade_lesson(
                ticket=ticket,
                symbol="XAUUSD",
                order_type=order_type,
                strategy=strategy,
                profit=profit,
                outcome=outcome,
                mistake_category=lesson_cat,
                lesson_summary=summary,
                defensive_rule=defensive_rule,
                mistake_signature=json.dumps(sig),
            )

            # Persist updated weights
            crud.save_or_update_adaptive_weight(
                component=f"strat_{strategy}",
                weight=self.strategy_multipliers[strategy],
                multiplier=self.strategy_multipliers[strategy],
                win=(outcome == "WIN"),
                pnl=profit,
            )

            for comp, w in self.component_weights.items():
                crud.save_or_update_adaptive_weight(
                    component=comp,
                    weight=w,
                    multiplier=1.0,
                    win=(outcome == "WIN"),
                    pnl=profit,
                )

        except Exception as e:
            logger.error(f"Failed to persist trade lesson #{ticket}: {e}")

        logger.info(
            f"🎓 Learned from Trade #{ticket} | Outcome: {outcome} (${profit:+.2f}) | "
            f"Category: {lesson_cat} | New {strategy} Multiplier: {self.strategy_multipliers[strategy]:.2f}x"
        )

        return {
            "ticket": ticket,
            "outcome": outcome,
            "profit": profit,
            "category": lesson_cat,
            "summary": summary,
            "defensive_rule": defensive_rule,
            "strategy_multiplier": self.strategy_multipliers[strategy],
            "component_weights": dict(self.component_weights),
        }

    def _diagnose_mistake(
        self,
        trade_data: dict,
        deal_info: Optional[dict],
        regime: str,
        confluence: float,
        sentiment: float,
        profit: float,
    ) -> tuple[str, str, str, dict]:
        """Classify why the trade lost and generate defensive learning takeaway."""
        order_type = trade_data.get("direction") or trade_data.get("order_type") or "BUY"
        strategy = trade_data.get("strategy", "scalping").lower()
        ai_pred = trade_data.get("ai_prediction", "")

        sig = {
            "regime": regime,
            "direction": order_type,
            "confluence_range": "< 75" if confluence < 75 else ">= 75",
        }

        # Category 1: Counter-Regime Trap
        if ("BULL" in regime and order_type == "SELL") or ("BEAR" in regime and order_type == "BUY"):
            cat = "COUNTER_REGIME_FADE"
            summary = f"Attempted {order_type} counter-trend execution during active {regime} regime."
            rule = f"In {regime} markets, prohibit counter-trend {order_type} entries unless confluence exceeds 85."
            sig["trap_type"] = "counter_trend"
            return cat, summary, rule, sig

        # Category 2: Borderline Confluence Failure
        if confluence < 74.0:
            cat = "LOW_CONFLUENCE_EXECUTION"
            summary = f"Entered with marginal conviction (Confluence: {confluence:.1f}/100), lacking multi-signal agreement."
            rule = f"Raise minimum execution threshold for {strategy.upper()} to at least 76.0 in current volatility."
            sig["trap_type"] = "marginal_confluence"
            return cat, summary, rule, sig

        # Category 3: Adverse AI / Sentiment Divergence
        if (order_type == "BUY" and sentiment < -0.15) or (order_type == "SELL" and sentiment > 0.15):
            cat = "MACRO_SENTIMENT_DIVERGENCE"
            summary = f"Trade placed against prevailing macro news sentiment ({sentiment:+.2f})."
            rule = "Require macro sentiment alignment or neutral state before firing directional entries."
            sig["trap_type"] = "sentiment_divergence"
            return cat, summary, rule, sig

        # Category 4: False Breakout / Quick Stop-out
        cat = "VOLATILITY_EXPANSION_WHIPSAW"
        summary = f"Gold price action suffered sudden adverse volatility spike triggering stop-loss."
        rule = "Widen ATR-based stop buffer and verify volume expansion before confirming breakout entries."
        sig["trap_type"] = "volatility_whipsaw"
        return cat, summary, rule, sig

    def _adapt_confluence_weights(self, outcome: str, trade_data: dict):
        """Adapt component weights based on whether their individual signals proved accurate."""
        # If AI prediction was correct in a winning trade, reward AI weight
        ai_pred = str(trade_data.get("ai_prediction", "")).upper()
        direction = str(trade_data.get("direction") or trade_data.get("order_type") or "").upper()
        sentiment_score = float(trade_data.get("sentiment_score", 0.0))

        if outcome == "WIN":
            if (direction == "BUY" and "BULL" in ai_pred) or (direction == "SELL" and "BEAR" in ai_pred):
                self.component_weights["ai_prediction"] = min(35.0, self.component_weights["ai_prediction"] + 0.5)
            if (direction == "BUY" and sentiment_score > 0.1) or (direction == "SELL" and sentiment_score < -0.1):
                self.component_weights["sentiment"] = min(30.0, self.component_weights["sentiment"] + 0.5)
        elif outcome == "LOSS":
            # If AI predicted wrong direction, penalize slightly
            if (direction == "BUY" and "BULL" in ai_pred) or (direction == "SELL" and "BEAR" in ai_pred):
                self.component_weights["ai_prediction"] = max(15.0, self.component_weights["ai_prediction"] - 0.4)
            # Increase regime weight during losses to favor stricter regime filtering
            self.component_weights["regime"] = min(25.0, self.component_weights["regime"] + 0.5)

        # Normalize weights back to exactly 100%
        total = sum(self.component_weights.values())
        if total > 0:
            for k in self.component_weights:
                self.component_weights[k] = round((self.component_weights[k] / total) * 100.0, 1)

    # ── Prospective Signal Screening (Mistake Memory Guard) ───────────────

    def screen_prospective_signal(
        self,
        strategy_name: str,
        direction: str,
        confluence_score: float,
        regime_val: str,
        sentiment_score: float,
    ) -> tuple[bool, str, float]:
        """
        Actively screen incoming signals against recent mistake memory.
        Returns:
            (is_approved: bool, explanation: str, penalty_score: float)
        """
        strat = strategy_name.lower()
        mult = self.strategy_multipliers.get(strat, 1.0)

        # 1. Strategy heavily penalized check
        if mult < 0.65:
            penalty = 6.0
            return (
                False,
                f"Strategy '{strat.upper()}' is currently penalized (confidence: {mult:.2f}x). Requires +{penalty:.0f} higher confluence.",
                penalty,
            )

        # 2. Match against active mistake memories
        for m in reversed(self.mistake_memory[-15:]):
            if m.get("strategy") == strat and m.get("direction") == direction and m.get("regime") == regime_val:
                trap = m.get("trap_type", "similar mistake")
                rule = m.get("rule", "Defensive rule in effect.")
                # Require higher conviction to break past a known mistake
                if confluence_score < 78.0:
                    return (
                        False,
                        f"🛡️ Mistake Guard Veto: Setup matches recent {trap} in {regime_val}. Rule: {rule}",
                        8.0,
                    )

        return (True, "Signal cleared all adaptive learning checks.", 0.0)

    # ── Inspection & Reporting ────────────────────────────────────────────

    def get_strategy_multiplier(self, strategy_name: str) -> float:
        """Get current adaptive multiplier for a given strategy."""
        return self.strategy_multipliers.get(strategy_name.lower(), 1.0)

    def get_confluence_weights(self) -> dict[str, float]:
        """Get current normalized confluence component weights."""
        return dict(self.component_weights)

    def get_learning_metrics(self) -> dict:
        """Expose self-learning metrics for Web Dashboard and Telegram."""
        recent = crud.get_recent_lessons(limit=5)
        return {
            "adaptive_weights": dict(self.component_weights),
            "strategy_multipliers": dict(self.strategy_multipliers),
            "active_mistakes_memorized": len(self.mistake_memory),
            "recent_lessons": [
                {
                    "ticket": l.ticket,
                    "outcome": l.outcome,
                    "profit": l.profit,
                    "category": l.mistake_category,
                    "summary": l.lesson_summary,
                    "rule": l.defensive_rule,
                    "time": l.created_at.isoformat() if l.created_at else None,
                }
                for l in recent
            ],
        }


# Global singleton instance
trade_learner = TradeLearner()
