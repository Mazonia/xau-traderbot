from pydantic import BaseModel
from typing import Optional
"""
Web Dashboard — FastAPI Application

Real-time trading dashboard with WebSocket support.
Serves the monitoring UI and provides REST/WS API endpoints.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger

from config.settings import get_settings
from database import crud

# ── App Setup ────────────────────────────────────────────────────────────
app = FastAPI(
    title="XAUUSD AI Trading Bot",
    description="Real-time trading dashboard",
    version="1.0.0",
)

# Protect against Cross-Origin Request Forgery (CORS restriction)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8080",
        "http://127.0.0.1:8080",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Connected WebSocket clients
connected_clients: set[WebSocket] = set()


# ── Routes ───────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    """Serve the dashboard HTML."""
    return FileResponse(str(STATIC_DIR / "index.html"))


@app.get("/api/account")
async def get_account():
    """Get current account info (fast non-blocking with credential masking)."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            info = mt5.get_account_info(auto_reconnect=False)
            if info:
                sanitized_info = dict(info)
                login_str = str(sanitized_info.get("login", ""))
                sanitized_info["login"] = f"***{login_str[-4:]}" if len(login_str) >= 4 else "***"
                sanitized_info["connected"] = True
                return JSONResponse(sanitized_info)
        return JSONResponse({"connected": False, "status": "MT5 Terminal Offline"})
    except Exception as e:
        return JSONResponse({"connected": False, "error": str(e)})


@app.get("/api/positions")
async def get_positions():
    """Get open positions (fast non-blocking)."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            positions = mt5.get_open_positions(auto_reconnect=False)
            for p in positions:
                if "time" in p and hasattr(p["time"], "isoformat"):
                    p["time"] = p["time"].isoformat()
            return JSONResponse(positions)
        return JSONResponse([])
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/trades")
async def get_trades():
    """Get recent trade history."""
    trades = crud.get_recent_trades(limit=50)
    return JSONResponse([
        {
            "ticket": t.ticket,
            "type": t.order_type,
            "strategy": t.strategy,
            "volume": t.volume,
            "entry": t.entry_price,
            "exit": t.exit_price,
            "sl": t.stop_loss,
            "tp": t.take_profit,
            "profit": t.profit,
            "status": t.status,
            "confluence": t.confluence_score,
            "opened_at": t.opened_at.isoformat() if t.opened_at else None,
            "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        }
        for t in trades
    ])


@app.get("/api/stats")
async def get_stats():
    """Get trading statistics."""
    stats = crud.get_trade_stats(days=30)
    return JSONResponse(stats)


@app.get("/api/equity")
async def get_equity_curve():
    """Get equity curve data."""
    data = crud.get_equity_curve(days=30)
    return JSONResponse(data)



@app.get("/api/learning")
async def get_self_learning_metrics():
    """Get autonomous self-learning metrics, adaptive weights, and lessons."""
    try:
        from ai.trade_learner import trade_learner
        metrics = trade_learner.get_learning_metrics()
        return JSONResponse(metrics)
    except Exception as e:
        logger.error(f"Error fetching learning metrics: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.get("/api/news")
async def get_recent_news():
    """Get recent news with sentiment."""
    from database.models import NewsEvent, get_session
    from sqlalchemy import desc

    session = get_session()
    try:
        events = (
            session.query(NewsEvent)
            .order_by(desc(NewsEvent.fetched_at))
            .limit(20)
            .all()
        )
        return JSONResponse([
            {
                "headline": e.headline,
                "source": e.source,
                "sentiment": e.sentiment,
                "score": e.sentiment_score,
                "impact": e.impact_level,
                "analysis": e.gemini_analysis,
                "time": e.fetched_at.isoformat() if e.fetched_at else None,
            }
            for e in events
        ])
    finally:
        session.close()


# ── WebSocket ────────────────────────────────────────────────────────────


class OrderRequest(BaseModel):
    action: str
    volume: float
    sl_pips: Optional[float] = None
    tp_pips: Optional[float] = None


@app.get("/api/chart")
async def get_chart_data(timeframe: str = "H1", count: int = 150):
    """Get real OHLCV candlestick data from MT5 for TradingView Lightweight Charts."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            tf = timeframe.upper()
            df = mt5.get_rates(timeframe=tf, count=min(count, 500), auto_reconnect=False)
            if df is not None and not df.empty:
                candles = []
                for idx, row in df.iterrows():
                    ts = int(idx.timestamp()) if hasattr(idx, "timestamp") else int(idx)
                    candles.append({
                        "time": ts,
                        "open": round(float(row["open"]), 2),
                        "high": round(float(row["high"]), 2),
                        "low": round(float(row["low"]), 2),
                        "close": round(float(row["close"]), 2),
                        "volume": float(row.get("volume", 0)),
                    })
                return JSONResponse(candles)
        return JSONResponse([])
    except Exception as e:
        logger.error(f"Error fetching chart candles: {e}")
        return JSONResponse([])


@app.get("/api/regime")
async def get_regime():
    """Get live market regime, ADX, and recommended strategies."""
    try:
        from core.mt5_connector import MT5Connector
        from strategies.regime_detector import RegimeDetector
        from analysis.technical import TechnicalAnalyzer

        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            df_h4 = mt5.get_rates(timeframe="H4", count=200, auto_reconnect=False)
            if df_h4 is not None and not df_h4.empty:
                ta = TechnicalAnalyzer()
                df_analyzed = ta.add_all_indicators(df_h4.copy())
                rd = RegimeDetector()
                regime = rd.analyze(df_analyzed)
                return JSONResponse({
                    "regime": regime.regime.value,
                    "adx": round(float(regime.adx_value), 1),
                    "volatility_percentile": round(float(regime.volatility_percentile), 1),
                    "volatility_label": regime.volatility_label,
                    "position_size_modifier": round(float(regime.position_size_modifier), 2),
                    "should_trade": bool(regime.should_trade),
                    "recommended_strategies": regime.recommended_strategies,
                })
        return JSONResponse({"regime": "UNKNOWN", "error": "MT5 Offline"})
    except Exception as e:
        logger.error(f"Error computing market regime: {e}")
        return JSONResponse({"regime": "UNKNOWN", "error": str(e)})


@app.get("/api/sentiment")
async def get_sentiment_overview():
    """Get 24H composite sentiment score and status."""
    score = crud.get_recent_sentiment(hours=24)
    label = "BULLISH" if score > 0.15 else ("BEARISH" if score < -0.15 else "NEUTRAL")
    return JSONResponse({
        "score": round(score, 2),
        "label": label,
        "direction": "UP" if score > 0.15 else ("DOWN" if score < -0.15 else "FLAT")
    })


@app.post("/api/close-position/{ticket}")
async def close_position(ticket: int):
    """Close a specific open position."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            success = mt5.close_position(ticket)
            return JSONResponse({"success": success, "ticket": ticket})
        return JSONResponse({"success": False, "error": "MT5 offline"}, status_code=500)
    except Exception as e:
        logger.error(f"Error closing position {ticket}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/close-all")
async def close_all_positions():
    """Emergency close all open positions."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            closed_count = mt5.close_all_positions()
            return JSONResponse({"success": True, "closed_count": closed_count})
        return JSONResponse({"success": False, "error": "MT5 offline"}, status_code=500)
    except Exception as e:
        logger.error(f"Error closing all positions: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/order")
async def place_manual_order(req: OrderRequest):
    """Place a manual market order from the dashboard."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            symbol = "XAUUSD"
            tick = mt5.get_current_price(symbol)
            if not tick:
                return JSONResponse({"success": False, "error": "Could not fetch XAUUSD price"}, status_code=400)

            price = tick["ask"] if req.action.upper() == "BUY" else tick["bid"]
            pip = 0.10
            sl = None
            tp = None
            if req.sl_pips:
                sl = price - (req.sl_pips * pip) if req.action.upper() == "BUY" else price + (req.sl_pips * pip)
            if req.tp_pips:
                tp = price + (req.tp_pips * pip) if req.action.upper() == "BUY" else price - (req.tp_pips * pip)

            order_type = "BUY" if req.action.upper() == "BUY" else "SELL"
            res = mt5.open_position(
                symbol=symbol,
                order_type=order_type,
                volume=max(0.01, round(req.volume, 2)),
                sl=sl,
                tp=tp,
                comment="Dashboard Order"
            )
            if res:
                return JSONResponse({"success": True, "ticket": res.get("ticket"), "price": price})
            return JSONResponse({"success": False, "error": "MT5 order execution failed"}, status_code=400)
        return JSONResponse({"success": False, "error": "MT5 offline"}, status_code=500)
    except Exception as e:
        logger.error(f"Manual order placement error: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/news/refresh")
async def refresh_news_feed():
    """Trigger background news refresh."""
    try:
        from news.news_fetcher import NewsFetcher
        from news.news_analyzer import NewsAnalyzer

        fetcher = NewsFetcher()
        analyzer = NewsAnalyzer()
        articles = await fetcher.fetch_all_news()

        count = 0
        for article in articles[:5]:
            analysis = await analyzer.analyze_article(article)
            crud.save_news_event(
                source=article.get("source", ""),
                headline=article.get("headline", ""),
                summary=article.get("summary", ""),
                url=article.get("url", ""),
                sentiment=analysis["sentiment"],
                sentiment_score=analysis["combined_score"],
                finbert_score=analysis["finbert"]["score"],
                gemini_score=analysis.get("gemini", {}).get("score", 0),
                gemini_analysis=analysis.get("gemini", {}).get("analysis", ""),
                impact_level=analysis["impact_level"],
                published_at=article.get("published_at"),
            )
            count += 1
        return JSONResponse({"success": True, "articles_processed": count})
    except Exception as e:
        logger.error(f"News refresh error: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time data streaming."""
    await websocket.accept()
    connected_clients.add(websocket)
    logger.info(f"WebSocket client connected ({len(connected_clients)} total)")

    try:
        while True:
            # Keep connection alive — receive messages from client
            data = await websocket.receive_text()
            # Handle client commands if needed
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        connected_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected ({len(connected_clients)} total)")


async def broadcast(data: dict):
    """Broadcast data to all connected WebSocket clients."""
    if not connected_clients:
        return

    message = json.dumps(data, default=str)
    disconnected = set()

    for client in connected_clients:
        try:
            await client.send_text(message)
        except Exception:
            disconnected.add(client)

    connected_clients -= disconnected
