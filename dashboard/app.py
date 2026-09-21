"""
Web Dashboard — FastAPI Application

Real-time trading dashboard with WebSocket support.
Serves the monitoring UI and provides REST/WS API endpoints.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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
    """Get current account info."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect():
            info = mt5.get_account_info()
            mt5.disconnect()
            return JSONResponse(info or {"error": "No account info"})
    except Exception as e:
        return JSONResponse({"error": str(e)})


@app.get("/api/positions")
async def get_positions():
    """Get open positions."""
    try:
        from core.mt5_connector import MT5Connector
        mt5 = MT5Connector()
        if mt5.connect():
            positions = mt5.get_open_positions()
            mt5.disconnect()
            # Convert datetime objects for JSON serialization
            for p in positions:
                if "time" in p:
                    p["time"] = p["time"].isoformat()
            return JSONResponse(positions)
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
