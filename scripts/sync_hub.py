"""
XAUUSD AI Trading Bot — Central Multi-Tenant Sync Hub (v1 - Nov 2026)

Lightweight FastAPI service for hosting on free cloud platforms (Render, Koyeb, Fly.io, Oracle Cloud).
Aggregates telemetry and federated learning across all distributed bot instances:
- Ingests anonymized trade lessons with risk-normalized metrics (R-multiples).
- Prevents reckless trader distortion via sanity-weight discount factors.
- Serves consensus strategy multipliers and global mistake memory guardrails to all connected bots.
"""

import os
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel, Field
import uvicorn

app = FastAPI(
    title="XAUUSD AI Bot — Federated Collective Intelligence Hub",
    description="Multi-tenant learning aggregation service for distributed trading bot nodes.",
    version="1.0.0",
)

DATA_STORE = Path(os.environ.get("SYNC_HUB_DATA", "data/hub_telemetry_store.json"))
DATA_STORE.parent.mkdir(parents=True, exist_ok=True)
API_SECRET = os.environ.get("FEDERATED_SYNC_SECRET", "")


class LessonTelemetry(BaseModel):
    client_id: str
    ticket_hash: str
    symbol: str = "XAUUSD"
    strategy: str
    order_type: str
    profit: float
    outcome: str
    mistake_category: str
    lesson_summary: str
    defensive_rule: str
    mistake_signature: dict = Field(default_factory=dict)
    r_multiple: float
    risk_pct: float
    lot_to_balance_ratio: float
    recklessness_tier: str
    sanity_weight: float
    confluence_score: float
    sentiment_score: float
    regime: str
    user_mode: str
    created_at: str


def verify_secret(authorization: Optional[str] = Header(None)):
    if API_SECRET:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing or invalid authorization header")
        token = authorization.split("Bearer ")[1].strip()
        if token != API_SECRET:
            raise HTTPException(status_code=403, detail="Forbidden: invalid secret key")
    return True


def load_all_lessons() -> list[dict]:
    if not DATA_STORE.exists():
        return []
    try:
        with open(DATA_STORE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_all_lessons(lessons: list[dict]):
    temp = DATA_STORE.with_suffix(".tmp")
    with open(temp, "w", encoding="utf-8") as f:
        json.dump(lessons, f, indent=2)
    temp.replace(DATA_STORE)


@app.get("/health")
def health_check():
    """Health check for Render / Koyeb / Uptime monitoring."""
    return {
        "status": "healthy",
        "service": "xauusd-federated-hub",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.post("/api/telemetry/lesson")
def submit_lesson(payload: LessonTelemetry, authorized: bool = Depends(verify_secret)):
    """Ingest an anonymized trade lesson from an active bot node."""
    lessons = load_all_lessons()
    lessons.append(payload.model_dump())
    if len(lessons) > 1000:
        lessons = lessons[-1000:]
    save_all_lessons(lessons)
    return {"status": "accepted", "stored_total": len(lessons)}


@app.get("/api/telemetry/global_state")
def get_global_state(authorized: bool = Depends(verify_secret)):
    """
    Compute and return consensus strategy multipliers, component weights,
    and the global mistake memory pool.
    """
    lessons = load_all_lessons()

    strat_scores = {"scalping": 1.0, "day_trading": 1.0, "swing_trading": 1.0}
    comp_scores = {"technical": 40.0, "ai_prediction": 25.0, "sentiment": 20.0, "regime": 15.0}
    global_mistakes = []
    total_effective_weight = 0.0

    for item in lessons:
        strat = item.get("strategy", "scalping").lower()
        outcome = item.get("outcome", "SCRATCH")
        sanity_wt = float(item.get("sanity_weight", 1.0))
        r_mult = float(item.get("r_multiple", 0.0))
        confluence = float(item.get("confluence_score", 70.0))
        regime = item.get("regime", "RANGING")

        fidelity = max(0.5, min(1.3, confluence / 70.0))
        effective_wt = sanity_wt * fidelity
        total_effective_weight += effective_wt

        if strat in strat_scores:
            if outcome == "WIN" and r_mult > 0:
                gain = min(0.04, 0.02 * min(r_mult, 3.0)) * effective_wt
                strat_scores[strat] = min(1.60, strat_scores[strat] * (1.0 + gain))
            elif outcome == "LOSS":
                loss_decay = min(0.25, 0.15 * max(1.0, min(abs(r_mult), 2.5))) * effective_wt
                strat_scores[strat] = max(0.30, strat_scores[strat] * (1.0 - loss_decay))

        if outcome == "LOSS":
            sig = item.get("mistake_signature") or {}
            cat = item.get("mistake_category", "MISTAKE")
            if cat != "OVERSIZED_LOT_BLOWOUT" and sig:
                sig["strategy"] = strat
                sig["regime"] = regime
                sig["rule"] = item.get("defensive_rule", "")
                sig["category"] = cat
                global_mistakes.append(sig)

    unique_mistakes = []
    seen = set()
    for m in reversed(global_mistakes):
        key = f"{m.get('strategy')}_{m.get('direction')}_{m.get('regime')}_{m.get('category')}"
        if key not in seen:
            seen.add(key)
            unique_mistakes.append(m)
        if len(unique_mistakes) >= 40:
            break

    comp_sum = sum(comp_scores.values())
    norm_comps = {k: round((v / comp_sum) * 100.0, 1) for k, v in comp_scores.items()}

    return {
        "strategy_multipliers": {k: round(v, 3) for k, v in strat_scores.items()},
        "component_weights": norm_comps,
        "global_mistakes": unique_mistakes,
        "total_lessons": len(lessons),
        "total_effective_weight": round(total_effective_weight, 2),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/telemetry/stats")
def get_hub_statistics():
    """Summary statistics for multi-tenant learning analytics."""
    lessons = load_all_lessons()
    if not lessons:
        return {"total_lessons": 0, "active_nodes": 0}

    nodes = {l.get("client_id") for l in lessons if l.get("client_id")}
    wins = sum(1 for l in lessons if l.get("outcome") == "WIN")
    losses = sum(1 for l in lessons if l.get("outcome") == "LOSS")
    tiers = {}
    for l in lessons:
        t = l.get("recklessness_tier", "NORMAL")
        tiers[t] = tiers.get(t, 0) + 1

    avg_r = sum(l.get("r_multiple", 0.0) for l in lessons) / len(lessons)

    return {
        "total_lessons": len(lessons),
        "active_nodes": len(nodes),
        "win_rate_pct": round((wins / len(lessons)) * 100, 1),
        "wins": wins,
        "losses": losses,
        "average_r_multiple": round(avg_r, 2),
        "recklessness_distribution": tiers,
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("scripts.sync_hub:app", host="0.0.0.0", port=port, reload=False)
