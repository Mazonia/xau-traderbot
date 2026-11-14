"""
Federated Learning & Multi-Tenant Cross-User Synchronization Engine (v3 - Nov 2026)

Connects distributed instances of the XAUUSD AI Trading Bot into a collective intelligence network:
1. Normalizes trade outcomes across diverse user account sizes, leverage, and risk profiles (R-Multiples).
2. Detects reckless sizing (huge lot sizes on small accounts) and discounts their weight to prevent model corruption.
3. Synchronizes anonymized trade lessons, strategy multipliers, and global mistake memories.
4. Seamlessly blends global collective knowledge with local broker execution calibration.
5. Supports local peer file pool sync or cloud REST sync hub (FastAPI / Supabase / Render / Koyeb).
"""

import json
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Any
from loguru import logger

from config.settings import get_settings


class FederatedSync:
    """
    Decentralized multi-tenant sync coordinator.
    Aggregates learning data across multiple users with risk-weighted normalization.
    """

    def __init__(self, settings: Optional[Any] = None):
        self.settings = settings or get_settings()
        self.config = self.settings.federated_sync

        # Generate or load persistent anonymous client ID
        self.client_id = self._init_client_id()

        # Local peer sync pool path (shared storage or local multi-bot instances)
        self.pool_path = Path(self.config.pool_file)
        self.pool_path.parent.mkdir(parents=True, exist_ok=True)

        self.global_blend_ratio = float(self.config.global_blend_ratio)
        self.enabled = bool(self.config.enabled)
        self.sync_url = str(self.config.sync_url or "").strip().rstrip("/")
        self.api_key = str(self.config.api_key or "").strip()

    def _init_client_id(self) -> str:
        """Generate a deterministic, anonymous identifier for this bot installation."""
        if self.config.client_id:
            return self.config.client_id

        # Use anonymous machine signature hash
        seed = f"{os.name}_{os.environ.get('COMPUTERNAME', '')}_{os.environ.get('USERNAME', '')}"
        hashed = hashlib.sha256(seed.encode()).hexdigest()[:16]
        return f"node_{hashed}"

    def build_telemetry_payload(
        self,
        ticket: int,
        strategy: str,
        order_type: str,
        profit: float,
        outcome: str,
        mistake_category: str,
        lesson_summary: str,
        defensive_rule: str,
        mistake_signature: dict,
        r_multiple: float,
        risk_pct: float,
        lot_to_balance_ratio: float,
        recklessness_tier: str,
        sanity_weight: float,
        confluence_score: float,
        sentiment_score: float,
        regime: str,
        user_mode: str,
    ) -> dict:
        """
        Build an anonymized, risk-normalized telemetry payload.
        NEVER transmits account numbers, passwords, or personal balances.
        """
        ticket_hash = hashlib.sha256(f"{self.client_id}_{ticket}".encode()).hexdigest()[:12]

        return {
            "client_id": self.client_id,
            "ticket_hash": ticket_hash,
            "symbol": "XAUUSD",
            "strategy": strategy.lower(),
            "order_type": order_type.upper(),
            "profit": round(profit, 2),
            "outcome": outcome,
            "mistake_category": mistake_category,
            "lesson_summary": lesson_summary,
            "defensive_rule": defensive_rule,
            "mistake_signature": mistake_signature,
            "r_multiple": round(r_multiple, 3),
            "risk_pct": round(risk_pct, 2),
            "lot_to_balance_ratio": round(lot_to_balance_ratio, 4),
            "recklessness_tier": recklessness_tier,
            "sanity_weight": round(sanity_weight, 3),
            "confluence_score": round(confluence_score, 1),
            "sentiment_score": round(sentiment_score, 2),
            "regime": regime,
            "user_mode": user_mode,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def push_lesson(self, payload: dict) -> bool:
        """
        Save the lesson payload to the local peer sync pool and submit to cloud if configured.
        """
        if not self.enabled:
            return False

        try:
            # 1. Append to local peer sync pool
            self._append_to_pool_file(payload)

            # 2. Asynchronously upload to cloud hub if sync_url is set
            if self.sync_url:
                self._dispatch_cloud_upload(payload)

            return True
        except Exception as e:
            logger.warning(f"FederatedSync push_lesson failed: {e}")
            return False

    def _append_to_pool_file(self, payload: dict):
        """Append to shared pool JSON file with rotation (retains up to 250 recent lessons)."""
        pool_data = self._read_pool_file()
        pool_data.append(payload)
        if len(pool_data) > 250:
            pool_data = pool_data[-250:]

        temp_file = self.pool_path.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(pool_data, f, indent=2)
        temp_file.replace(self.pool_path)

    def _read_pool_file(self) -> list[dict]:
        """Safely read lessons from the local sync pool file."""
        if not self.pool_path.exists():
            return []
        try:
            with open(self.pool_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []

    def _dispatch_cloud_upload(self, payload: dict):
        """Fire-and-forget HTTP POST to cloud sync endpoint."""
        import threading
        def _upload():
            try:
                import httpx
                headers = {"Content-Type": "application/json"}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                url = f"{self.sync_url}/api/telemetry/lesson"
                with httpx.Client(timeout=8.0) as client:
                    client.post(url, json=payload, headers=headers)
            except Exception as e:
                logger.debug(f"Cloud sync telemetry upload note: {e}")

        threading.Thread(target=_upload, daemon=True).start()

    # ── Federated Aggregation Engine ──────────────────────────────────────

    def aggregate_lessons(self, lessons: list[dict]) -> dict:
        """
        Compute risk-weighted federated consensus across all user lessons.

        Reckless trades (e.g. 1 lot on $200 account) have sanity_weight <= 0.20,
        which limits their influence on strategy multipliers while preserving
        their trap signatures in the global mistake memory.
        """
        if not lessons:
            return {
                "strategy_multipliers": {"scalping": 1.0, "day_trading": 1.0, "swing_trading": 1.0},
                "component_weights": {"technical": 40.0, "ai_prediction": 25.0, "sentiment": 20.0, "regime": 15.0},
                "global_mistakes": [],
                "total_lessons": 0,
            }

        # Multiplier trackers: baseline 1.0
        strat_scores = {"scalping": 1.0, "day_trading": 1.0, "swing_trading": 1.0}
        comp_scores = {"technical": 40.0, "ai_prediction": 25.0, "sentiment": 20.0, "regime": 15.0}

        global_mistakes = []
        total_weight = 0.0

        for item in lessons:
            strat = item.get("strategy", "scalping").lower()
            outcome = item.get("outcome", "SCRATCH")
            sanity_wt = float(item.get("sanity_weight", 1.0))
            r_mult = float(item.get("r_multiple", 0.0))
            confluence = float(item.get("confluence_score", 70.0))
            regime = item.get("regime", "RANGING")

            # Confluence fidelity factor
            conf_fidelity = max(0.5, min(1.3, confluence / 70.0))
            effective_weight = sanity_wt * conf_fidelity
            total_weight += effective_weight

            # Strategy multiplier adjustment based on R-Multiple and sanity
            if strat in strat_scores:
                if outcome == "WIN" and r_mult > 0:
                    # Reward scaled by R-Multiple and sanity
                    gain = min(0.04, 0.02 * min(r_mult, 3.0)) * effective_weight
                    strat_scores[strat] = min(1.60, strat_scores[strat] * (1.0 + gain))
                elif outcome == "LOSS":
                    # Penalize scaled by sanity — reckless users only inflict small decay
                    loss_factor = min(0.25, 0.15 * max(1.0, min(abs(r_mult), 2.5))) * effective_weight
                    strat_scores[strat] = max(0.30, strat_scores[strat] * (1.0 - loss_factor))

            # Collect genuine market trap signatures
            if outcome == "LOSS":
                sig = item.get("mistake_signature") or {}
                cat = item.get("mistake_category", "MISTAKE")
                # Filter out pure sizing blowouts from strategy market traps
                if cat != "OVERSIZED_LOT_BLOWOUT" and sig:
                    sig["strategy"] = strat
                    sig["regime"] = regime
                    sig["rule"] = item.get("defensive_rule", "")
                    sig["category"] = cat
                    global_mistakes.append(sig)

        # Deduplicate and retain the most recent 30 unique trap signatures
        unique_mistakes = []
        seen = set()
        for m in reversed(global_mistakes):
            key = f"{m.get('strategy')}_{m.get('direction')}_{m.get('regime')}_{m.get('category')}"
            if key not in seen:
                seen.add(key)
                unique_mistakes.append(m)
            if len(unique_mistakes) >= 30:
                break

        # Normalize component weights back to 100%
        comp_sum = sum(comp_scores.values())
        norm_comps = {k: round((v / comp_sum) * 100.0, 1) for k, v in comp_scores.items()}

        return {
            "strategy_multipliers": {k: round(v, 3) for k, v in strat_scores.items()},
            "component_weights": norm_comps,
            "global_mistakes": unique_mistakes,
            "total_lessons": len(lessons),
            "effective_weight_sum": round(total_weight, 2),
        }

    def fetch_global_state(self) -> dict:
        """
        Fetch aggregated global intelligence from cloud hub or local peer pool.
        """
        # If cloud hub is configured, try querying remote API
        if self.sync_url:
            try:
                import httpx
                headers = {}
                if self.api_key:
                    headers["Authorization"] = f"Bearer {self.api_key}"
                url = f"{self.sync_url}/api/telemetry/global_state"
                with httpx.Client(timeout=6.0) as client:
                    resp = client.get(url, headers=headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        logger.info(f"🌐 Successfully synced global learning state from cloud hub ({self.sync_url})")
                        return data
            except Exception as e:
                logger.warning(f"Could not reach cloud sync hub, falling back to local pool: {e}")

        # Fallback to local pool file
        lessons = self._read_pool_file()
        return self.aggregate_lessons(lessons)

    def blend_multipliers(
        self,
        local_multipliers: dict[str, float],
        global_multipliers: dict[str, float],
    ) -> dict[str, float]:
        """
        Blend local strategy multipliers with global federated consensus.
        W_blended = ratio * W_global + (1 - ratio) * W_local
        """
        ratio = self.global_blend_ratio
        blended = {}
        for strat in ("scalping", "day_trading", "swing_trading"):
            local_val = float(local_multipliers.get(strat, 1.0))
            global_val = float(global_multipliers.get(strat, 1.0))
            blended_val = (ratio * global_val) + ((1.0 - ratio) * local_val)
            blended[strat] = round(blended_val, 3)
        return blended
