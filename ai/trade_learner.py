"""
Continuous Self-Learning & Mistake Adaptation Engine (v2 — Oct 2026)

Equips the XAUUSD AI Trading Bot with:
1. Post-Trade Performance Attribution & Mistake Diagnostics.
2. Online Reinforcement Learning (Multi-Armed Bandit / ExpGrad) for Strategy & Confluence Weights.
3. Mistake Memory Guard: An active screening layer preventing repeating known losing setups.
4. Continuous Knowledge Persistence across restarts.
5. Loss Streak Circuit Breaker with exponential cooldowns.
6. Fuzzy Mistake Memory Matching across similar regime/trap types.
7. Rolling Win-Rate Gating — suspends strategies with < 30% win rate.
"""

import json
import asyncio
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from loguru import logger

from database import crud
from database.models import TradeLesson, AdaptiveWeight
from config.settings import get_settings


# ── Fuzzy Regime Similarity Map ──────────────────────────────────────────
# Regimes that are "directionally similar" for mistake matching purposes.
_REGIME_FAMILY = {
    "STRONG_TREND_UP": "TREND_UP",
    "MODERATE_TREND_UP": "TREND_UP",
    "STRONG_TREND_DOWN": "TREND_DOWN",
    "MODERATE_TREND_DOWN": "TREND_DOWN",
    "RANGING": "RANGING",
    "HIGH_VOLATILITY": "HIGH_VOLATILITY",
    "LOW_VOLATILITY": "RANGING",
    "NEWS_EVENT": "NEWS_EVENT",
}


def _regime_family(regime: str) -> str:
    """Map a specific regime to its directional family for fuzzy matching."""
    if not regime:
        return "NEUTRAL"
    r = regime.upper().strip()
    if r in _REGIME_FAMILY:
        return _REGIME_FAMILY[r]
    if "DOWN" in r or "BEAR" in r:
        return "TREND_DOWN"
    if "UP" in r or "BULL" in r:
        return "TREND_UP"
    return r


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

        # Strategy performance multipliers (bounded between 0.30 and 1.60)
        self.strategy_multipliers: dict[str, float] = {
            "scalping": 1.0,
            "day_trading": 1.0,
            "swing_trading": 1.0,
        }

        # Rolling active mistake memory signatures
        self.mistake_memory: list[dict] = []

        # ── Loss Streak Circuit Breaker ──────────────────────────────────
        # Tracks consecutive losses per strategy for exponential cooldown
        self._consecutive_losses: dict[str, int] = {
            "scalping": 0,
            "day_trading": 0,
            "swing_trading": 0,
        }
        # Cooldown expiry timestamps per strategy (UTC)
        self._cooldown_until: dict[str, Optional[datetime]] = {
            "scalping": None,
            "day_trading": None,
            "swing_trading": None,
        }
        # Base cooldown escalation: 15min → 30min → 60min → 120min (session pause)
        self._cooldown_escalation_minutes = [15, 30, 60, 120]

        # ── Rolling Win-Rate Gating ──────────────────────────────────────
        # Last N trade outcomes per strategy for win-rate tracking
        self._rolling_outcomes: dict[str, deque] = {
            "scalping": deque(maxlen=10),
            "day_trading": deque(maxlen=10),
            "swing_trading": deque(maxlen=10),
        }
        self._strategy_suspended: dict[str, bool] = {
            "scalping": False,
            "day_trading": False,
            "swing_trading": False,
        }
        self._suspended_until: dict[str, Optional[datetime]] = {
            "scalping": None,
            "day_trading": None,
            "swing_trading": None,
        }

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
                    s_name = comp.replace("strat_", "").split("|")[0].strip()
                    if s_name in self.strategy_multipliers:
                        val = float(data.get("multiplier", 1.0))
                        # If multiplier was severely degraded and no recent trades in 24h, rehabilitate
                        self.strategy_multipliers[s_name] = max(0.65, val)

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

            # Rebuild rolling outcomes from recent lessons (last 24 hours only) to restore active win-rate state
            all_recent = crud.get_recent_lessons(limit=50)
            now_utc = datetime.now(timezone.utc)
            cutoff_24h = now_utc - timedelta(hours=24)
            for l in reversed(all_recent):  # oldest first so deque keeps most recent
                strat = l.strategy if hasattr(l, "strategy") else ""
                created = l.created_at
                if created is not None:
                    c_dt = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
                    if c_dt < cutoff_24h:
                        continue
                if strat in self._rolling_outcomes:
                    self._rolling_outcomes[strat].append(l.outcome)

            # Evaluate suspension state on startup
            for strat in self._rolling_outcomes:
                self._evaluate_win_rate_gating(strat)

            logger.info(
                f"🧠 Self-Learning Engine v2 initialized | Adaptive Multipliers: {self.strategy_multipliers} "
                f"| Active Mistake Memories: {len(self.mistake_memory)} "
                f"| Suspended Strategies: {[s for s, v in self._strategy_suspended.items() if v]}"
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

        # ── Update Rolling Outcomes for Win-Rate Gating ──────────────────
        if strategy in self._rolling_outcomes:
            self._rolling_outcomes[strategy].append(outcome)

        # ── 1. Adapt Strategy Multipliers ────────────────────────────────
        current_strat_mult = self.strategy_multipliers.get(strategy, 1.0)
        if outcome == "WIN":
            # Reward successful strategy — slow recovery (earned, not given)
            new_strat_mult = min(1.60, current_strat_mult * 1.03)
            lesson_cat = "WINNING_EXECUTION"
            summary = f"Successful {strategy.upper()} {order_type} execution in {regime} market. Captured +${profit:.2f} profit."
            defensive_rule = f"Maintain conviction on {strategy.upper()} when {regime} confluence exceeds {confluence:.0f}."
            sig = {}
            # Reset consecutive loss counter on win
            self._consecutive_losses[strategy] = 0
            self._cooldown_until[strategy] = None
        elif outcome == "LOSS":
            # Penalize and diagnose mistake — FAST decay
            new_strat_mult = max(0.30, current_strat_mult * 0.78)
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
            sig["regime_family"] = _regime_family(regime)
            sig["timestamp"] = datetime.now(timezone.utc).isoformat()
            self.mistake_memory.append(sig)
            if len(self.mistake_memory) > 40:
                self.mistake_memory.pop(0)

            # ── Loss Streak Circuit Breaker ──────────────────────────────
            self._consecutive_losses[strategy] = self._consecutive_losses.get(strategy, 0) + 1
            streak = self._consecutive_losses[strategy]
            if streak >= 3:
                cooldown_idx = min(streak - 3, len(self._cooldown_escalation_minutes) - 1)
                cooldown_mins = self._cooldown_escalation_minutes[cooldown_idx]
                self._cooldown_until[strategy] = datetime.now(timezone.utc) + timedelta(minutes=cooldown_mins)
                logger.warning(
                    f"🚨 LOSS STREAK CIRCUIT BREAKER: {strategy.upper()} has {streak} consecutive losses. "
                    f"Imposing {cooldown_mins}min cooldown until {self._cooldown_until[strategy].strftime('%H:%M:%S UTC')}"
                )
        else:
            new_strat_mult = current_strat_mult
            lesson_cat = "BREAKEVEN_EXIT"
            summary = f"Trade #{ticket} exited near breakeven (${profit:+.2f}). Capital protected."
            defensive_rule = "Continue strict trailing stop and breakeven protection."
            sig = {}

        self.strategy_multipliers[strategy] = round(new_strat_mult, 3)

        # 2. Adapt Confluence Component Weights
        self._adapt_confluence_weights(outcome=outcome, trade_data=trade_data)

        # 3. Evaluate Win-Rate Gating
        if strategy in self._rolling_outcomes:
            self._evaluate_win_rate_gating(strategy)

        # 4. Persist Lesson to Database
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
            f"Category: {lesson_cat} | New {strategy} Multiplier: {self.strategy_multipliers[strategy]:.2f}x | "
            f"Streak: {self._consecutive_losses.get(strategy, 0)} consecutive losses"
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
            "consecutive_losses": self._consecutive_losses.get(strategy, 0),
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

        # Category 4: Loss during high consecutive streak — pattern recognition failure
        streak = self._consecutive_losses.get(strategy, 0)
        if streak >= 2:
            cat = "STREAK_PATTERN_FAILURE"
            summary = f"Loss #{streak + 1} in a consecutive streak. Market conditions hostile to {strategy.upper()} approach."
            rule = f"Strategy {strategy.upper()} requires mandatory cooldown and regime re-evaluation after {streak + 1} losses."
            sig["trap_type"] = "streak_failure"
            return cat, summary, rule, sig

        # Category 5: False Breakout / Quick Stop-out
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

    def _evaluate_win_rate_gating(self, strategy: str):
        """Evaluate rolling win rate and suspend/unsuspend strategy."""
        outcomes = self._rolling_outcomes.get(strategy, deque())
        if len(outcomes) < 5:
            # Not enough data to make a judgment
            return

        wins = sum(1 for o in outcomes if o == "WIN")
        total = len(outcomes)
        win_rate = wins / total

        if win_rate < 0.30 and not self._strategy_suspended.get(strategy, False):
            self._strategy_suspended[strategy] = True
            # Auto-revalidation cooldown: 2-hour suspension cooldown instead of permanent lock
            self._suspended_until[strategy] = datetime.now(timezone.utc) + timedelta(hours=2)
            logger.warning(
                f"⛔ WIN-RATE GATING: {strategy.upper()} suspended for 2h — "
                f"rolling win rate {win_rate:.0%} ({wins}/{total}) below 30% threshold"
            )
        elif win_rate >= 0.40 and self._strategy_suspended.get(strategy, False):
            self._strategy_suspended[strategy] = False
            self._suspended_until[strategy] = None
            logger.info(
                f"✅ WIN-RATE GATING: {strategy.upper()} reinstated — "
                f"rolling win rate recovered to {win_rate:.0%} ({wins}/{total})"
            )

    # ── Prospective Signal Screening (Mistake Memory Guard) ───────────────

    def screen_prospective_signal(
        self,
        strategy_name: str,
        direction: str,
        confluence_score: float,
        regime_val: str,
        sentiment_score: float = 0.0,
    ) -> tuple[bool, str, float]:
        """
        Actively screen incoming signals against recent mistake memory,
        loss streak cooldowns, and win-rate gating.
        Returns:
            (is_approved: bool, explanation: str, penalty_score: float)
        """
        strat = strategy_name.lower()
        mult = self.strategy_multipliers.get(strat, 1.0)
        settings = get_settings()
        strat_params = getattr(settings, f"{strat}_params", {}) or {}
        base_min_confluence = float(strat_params.get("min_confluence_score", 50.0))

        # ── 0. Win-Rate Gating Check ─────────────────────────────────────
        if self._strategy_suspended.get(strat, False):
            # Check if 2h probation cooldown expired -> reinstate strategy
            susp_until = self._suspended_until.get(strat)
            if susp_until and datetime.now(timezone.utc) >= susp_until:
                self._strategy_suspended[strat] = False
                self._suspended_until[strat] = None
                logger.info(f"Probationary reinstatement for {strat.upper()} after suspension cooldown")
            elif mult >= 0.8:
                # If strategy multiplier was explicitly reset/healthy, clear suspension
                self._strategy_suspended[strat] = False
                self._suspended_until[strat] = None
            else:
                return (
                    False,
                    f"⛔ Strategy '{strat.upper()}' is SUSPENDED by win-rate gating (rolling win rate < 30%). "
                    f"Waiting for recovery cooldown before reinstating.",
                    20.0,
                )

        # ── 1. Loss Streak Circuit Breaker Check ─────────────────────────
        cooldown_expiry = self._cooldown_until.get(strat)
        if cooldown_expiry and datetime.now(timezone.utc) < cooldown_expiry:
            remaining = (cooldown_expiry - datetime.now(timezone.utc)).total_seconds()
            streak = self._consecutive_losses.get(strat, 0)
            return (
                False,
                f"🚨 Loss Streak Cooldown: {strat.upper()} has {streak} consecutive losses. "
                f"Cooldown active for {remaining:.0f}s more.",
                15.0,
            )

        # ── 2. Strategy heavily penalized check ──────────────────────────
        # Check time-decay rehabilitation if strategy has been dormant without recent losses (>12h)
        if mult < 0.8:
            strat_losses = [m for m in self.mistake_memory if m.get("strategy") == strat and "timestamp" in m]
            last_ts = None
            if strat_losses:
                raw_ts = strat_losses[-1]["timestamp"]
                try:
                    last_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                except Exception:
                    pass
            hours_dormant = 24.0
            if last_ts:
                c_ts = last_ts.replace(tzinfo=timezone.utc) if last_ts.tzinfo is None else last_ts
                hours_dormant = (datetime.now(timezone.utc) - c_ts).total_seconds() / 3600.0

            if hours_dormant >= 12.0:
                mult = min(1.0, mult + (1.0 - mult) * 0.5)
                self.strategy_multipliers[strat] = round(mult, 3)

        penalty = 0.0
        if mult < 0.55:
            penalty = 10.0
            hurdle = base_min_confluence + penalty
            if confluence_score < hurdle:
                return (
                    False,
                    f"Strategy '{strat.upper()}' is severely penalized ({mult:.2f}x). "
                    f"Confluence {confluence_score:.1f} < required {hurdle:.1f} (+{penalty:.0f} hurdle).",
                    penalty,
                )
        elif mult < 0.65:
            penalty = 6.0
            hurdle = base_min_confluence + penalty
            if confluence_score < hurdle:
                return (
                    False,
                    f"Strategy '{strat.upper()}' is penalized ({mult:.2f}x). "
                    f"Confluence {confluence_score:.1f} < required {hurdle:.1f} (+{penalty:.0f} hurdle).",
                    penalty,
                )

        # ── 3. Fuzzy Mistake Memory Matching ─────────────────────────────
        veto_threshold = base_min_confluence + 8.0
        signal_regime_family = _regime_family(regime_val)

        for m in reversed(self.mistake_memory[-20:]):
            mem_strat = m.get("strategy", "")
            mem_dir = m.get("direction", "")
            mem_regime_family = _regime_family(m.get("regime_family") or m.get("regime", ""))
            mem_trap = m.get("trap_type", "")

            # Exact match: same strategy + direction + regime family
            exact_match = (mem_strat == strat and mem_dir == direction and mem_regime_family == signal_regime_family)

            # Fuzzy match: same direction + same trap type (across any strategy in same regime family)
            fuzzy_match = (mem_dir == direction and mem_regime_family == signal_regime_family
                           and mem_trap in ("counter_trend", "volatility_whipsaw", "streak_failure"))

            if exact_match or fuzzy_match:
                trap = mem_trap or "similar mistake"
                rule = m.get("rule", "Defensive rule in effect.")
                match_type = "EXACT" if exact_match else "FUZZY"
                # Require higher conviction to break past a known mistake
                if confluence_score < veto_threshold:
                    return (
                        False,
                        f"🛡️ Mistake Guard Veto ({match_type}): Setup matches recent '{trap}' in "
                        f"{signal_regime_family} (score {confluence_score:.1f} < required {veto_threshold:.1f}). Rule: {rule}",
                        8.0,
                    )

        if penalty > 0:
            return (True, f"Signal cleared adaptive checks (penalty +{penalty:.0f} applied).", penalty)
        return (True, "Signal cleared all adaptive learning checks.", 0.0)

    # ── Inspection & Reporting ────────────────────────────────────────────

    def get_strategy_multiplier(self, strategy_name: str) -> float:
        """Get current adaptive multiplier for a given strategy."""
        return self.strategy_multipliers.get(strategy_name.lower(), 1.0)

    def get_confluence_weights(self) -> dict[str, float]:
        """Get current normalized confluence component weights."""
        return dict(self.component_weights)

    def is_strategy_suspended(self, strategy_name: str) -> bool:
        """Check if a strategy is currently suspended by win-rate gating."""
        strat = strategy_name.lower()
        if self._strategy_suspended.get(strat, False):
            susp_until = self._suspended_until.get(strat)
            if susp_until and datetime.now(timezone.utc) >= susp_until:
                self._strategy_suspended[strat] = False
                self._suspended_until[strat] = None
                return False
            if self.strategy_multipliers.get(strat, 1.0) >= 0.8:
                self._strategy_suspended[strat] = False
                self._suspended_until[strat] = None
                return False
            return True
        return False

    def reset_adaptive_state(self):
        """Reset all runtime adaptive weights, streaks, outcomes, and suspensions to clean defaults."""
        self.strategy_multipliers = {"scalping": 1.0, "day_trading": 1.0, "swing_trading": 1.0}
        self.component_weights = {
            "technical": 40.0,
            "ai_prediction": 25.0,
            "sentiment": 20.0,
            "regime": 15.0,
        }
        self.mistake_memory.clear()
        for s in list(self._rolling_outcomes.keys()):
            self._consecutive_losses[s] = 0
            self._cooldown_until[s] = None
            self._strategy_suspended[s] = False
            self._suspended_until[s] = None
            self._rolling_outcomes[s].clear()

    def get_consecutive_losses(self, strategy_name: str) -> int:
        """Get consecutive loss count for a strategy."""
        return self._consecutive_losses.get(strategy_name.lower(), 0)

    def get_learning_metrics(self) -> dict:
        """Expose self-learning metrics for Web Dashboard and Telegram."""
        recent = crud.get_recent_lessons(limit=5)

        # Calculate rolling win rates
        rolling_win_rates = {}
        for strat, outcomes in self._rolling_outcomes.items():
            if len(outcomes) > 0:
                wins = sum(1 for o in outcomes if o == "WIN")
                rolling_win_rates[strat] = round(wins / len(outcomes) * 100, 1)
            else:
                rolling_win_rates[strat] = None

        return {
            "adaptive_weights": dict(self.component_weights),
            "strategy_multipliers": dict(self.strategy_multipliers),
            "active_mistakes_memorized": len(self.mistake_memory),
            "consecutive_losses": dict(self._consecutive_losses),
            "strategy_suspended": dict(self._strategy_suspended),
            "rolling_win_rates": rolling_win_rates,
            "cooldowns_active": {
                s: self._cooldown_until[s].isoformat() if self._cooldown_until.get(s) else None
                for s in self._cooldown_until
            },
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
