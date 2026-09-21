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
    """Get current account info (fast non-blocking with credential masking and today's P&L)."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            info = mt5.get_account_info(auto_reconnect=False)
            if info:
                sanitized_info = dict(info)
                login_str = str(sanitized_info.get("login", ""))
                sanitized_info["login"] = f"***{login_str[-4:]}" if len(login_str) >= 4 else "***"
                sanitized_info["connected"] = True

                # Realized & Net P&L metrics
                stats = crud.get_trade_stats(days=30)
                realized_today = stats.get("today_realized_profit", 0.0)
                floating = float(sanitized_info.get("profit", 0.0))
                sanitized_info["realized_today"] = round(realized_today, 2)
                sanitized_info["floating_profit"] = round(floating, 2)
                sanitized_info["net_pnl_today"] = round(realized_today + floating, 2)

                return JSONResponse(sanitized_info)
        return JSONResponse({"connected": False, "status": "MT5 Terminal Offline"})
    except Exception as e:
        return JSONResponse({"connected": False, "error": str(e)})


@app.get("/api/positions")
async def get_positions():
    """Get open positions (fast non-blocking)."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
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
    """Get recent trade history, auto-syncing latest broker deals from MT5."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            deals = mt5.get_historical_trades(days=30)
            if deals:
                crud.sync_mt5_deals(deals)
    except Exception as e:
        logger.debug(f"Error during /api/trades MT5 sync: {e}")

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
            "comment": t.comment,
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
        from news.news_utils import normalize_headline
        events = (
            session.query(NewsEvent)
            .order_by(desc(NewsEvent.fetched_at))
            .limit(40)
            .all()
        )
        unique_events = []
        seen = set()
        for e in events:
            norm = normalize_headline(e.headline)
            if norm not in seen:
                seen.add(norm)
                unique_events.append(e)
            if len(unique_events) >= 20:
                break

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
            for e in unique_events
        ])
    finally:
        session.close()


# ── WebSocket ────────────────────────────────────────────────────────────


class OrderRequest(BaseModel):
    action: str
    volume: float
    target_price: Optional[float] = None
    sl_pips: Optional[float] = None
    tp_pips: Optional[float] = None


@app.get("/api/chart")
async def get_chart_data(timeframe: str = "H1", count: int = 150):
    """Get real OHLCV candlestick data from MT5 for TradingView Lightweight Charts."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
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
        from core.mt5_connector import get_mt5_connector
        from strategies.regime_detector import RegimeDetector
        from analysis.technical import TechnicalAnalyzer

        mt5 = get_mt5_connector()
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
    """Close a specific open position and sync deals immediately."""
    try:
        from core.mt5_connector import get_mt5_connector
        import asyncio
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            success = mt5.close_position(ticket)
            if success:
                await asyncio.sleep(0.4)
                deals = mt5.get_historical_trades(days=7)
                if deals:
                    crud.sync_mt5_deals(deals)
            return JSONResponse({"success": success, "ticket": ticket})
        return JSONResponse({"success": False, "error": "MT5 offline"}, status_code=500)
    except Exception as e:
        logger.error(f"Error closing position {ticket}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/close-all")
async def close_all_positions():
    """Emergency close all open positions and sync deals immediately."""
    try:
        from core.mt5_connector import get_mt5_connector
        import asyncio
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            closed_count = mt5.close_all_positions()
            if closed_count > 0:
                await asyncio.sleep(0.5)
                deals = mt5.get_historical_trades(days=7)
                if deals:
                    crud.sync_mt5_deals(deals)
            return JSONResponse({"success": True, "closed_count": closed_count})
        return JSONResponse({"success": False, "error": "MT5 offline"}, status_code=500)
    except Exception as e:
        logger.error(f"Error closing all positions: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/pending")
async def get_pending_orders():
    """Get active scheduled pending orders from MT5."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            pending = mt5.get_pending_orders(auto_reconnect=False)
            for p in pending:
                if "time" in p and hasattr(p["time"], "isoformat"):
                    p["time"] = p["time"].isoformat()
            return JSONResponse(pending)
        return JSONResponse([])
    except Exception as e:
        logger.error(f"Error fetching pending orders: {e}")
        return JSONResponse([])


@app.post("/api/cancel-order/{ticket}")
async def cancel_pending_order(ticket: int):
    """Cancel a scheduled pending order by ticket."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            success = mt5.cancel_order(ticket)
            return JSONResponse({"success": success, "ticket": ticket})
        return JSONResponse({"success": False, "error": "MT5 offline"}, status_code=500)
    except Exception as e:
        logger.error(f"Error canceling order {ticket}: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/order")
async def place_manual_order(req: OrderRequest):
    """Place a manual market or scheduled pending order from the dashboard."""
    try:
        from core.mt5_connector import get_mt5_connector
        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            symbol = "XAUUSD"
            tick = mt5.get_current_tick(symbol)
            if not tick:
                return JSONResponse({"success": False, "error": "Could not fetch live XAUUSD tick"}, status_code=400)

            act = req.action.upper()
            vol = max(0.01, round(req.volume, 2))
            pip = 0.10

            if act in ["BUY", "SELL"]:
                price = tick["ask"] if act == "BUY" else tick["bid"]
                sl = (price - req.sl_pips * pip) if (req.sl_pips and act == "BUY") else ((price + req.sl_pips * pip) if req.sl_pips else 0.0)
                tp = (price + req.tp_pips * pip) if (req.tp_pips and act == "BUY") else ((price - req.tp_pips * pip) if req.tp_pips else 0.0)
                res = mt5.send_market_order(
                    order_type=act,
                    symbol=symbol,
                    volume=vol,
                    sl=sl,
                    tp=tp,
                    comment="DASHBOARD_MANUAL"
                )
                if res and (res.get("deal", 0) > 0 or res.get("order", 0) > 0):
                    return JSONResponse({"success": True, "ticket": res.get("order"), "deal": res.get("deal"), "price": res.get("price", price)})
                err = res.get("comment", "Order rejected by broker") if res else "Order dispatch failed"
                return JSONResponse({"success": False, "error": err}, status_code=400)

            elif act in ["BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"]:
                target_p = req.target_price if (req.target_price and req.target_price > 0) else (tick["bid"] if "BUY" in act else tick["ask"])
                sl = (target_p - req.sl_pips * pip) if (req.sl_pips and "BUY" in act) else ((target_p + req.sl_pips * pip) if req.sl_pips else 0.0)
                tp = (target_p + req.tp_pips * pip) if (req.tp_pips and "BUY" in act) else ((target_p - req.tp_pips * pip) if req.tp_pips else 0.0)
                res = mt5.send_pending_order(
                    order_type=act,
                    price=target_p,
                    symbol=symbol,
                    volume=vol,
                    sl=sl,
                    tp=tp,
                    comment="DASHBOARD_PENDING"
                )
                if res and res.get("order", 0) > 0:
                    return JSONResponse({"success": True, "ticket": res.get("order"), "price": target_p})
                err = res.get("comment", "Pending order rejected by broker") if res else "Pending order failed"
                return JSONResponse({"success": False, "error": err}, status_code=400)

            return JSONResponse({"success": False, "error": f"Unsupported action {act}"}, status_code=400)

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
            headline = article.get("headline", "")
            url = article.get("url", "")
            if crud.is_news_already_saved(headline, url):
                continue
            analysis = await analyzer.analyze_article(article)
            saved = crud.save_news_event(
                source=article.get("source", ""),
                headline=headline,
                summary=article.get("summary", ""),
                url=url,
                sentiment=analysis["sentiment"],
                sentiment_score=analysis["combined_score"],
                finbert_score=analysis["finbert"]["score"],
                gemini_score=analysis.get("gemini", {}).get("score", 0),
                gemini_analysis=analysis.get("gemini", {}).get("analysis", ""),
                impact_level=analysis["impact_level"],
                published_at=article.get("published_at"),
            )
            if saved:
                count += 1
        return JSONResponse({"success": True, "articles_processed": count})
    except Exception as e:
        logger.error(f"News refresh error: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.get("/api/barometer")
async def get_market_barometer():
    """Get live institutional technical barometer metrics (24h high/low, spread, ATR, RSI)."""
    try:
        from core.mt5_connector import get_mt5_connector
        from analysis.technical import TechnicalAnalyzer

        mt5 = get_mt5_connector()
        if mt5.connect(max_retries=1, retry_delay=0.1):
            tick = mt5.get_current_tick()
            df_d1 = mt5.get_rates(timeframe="D1", count=2)
            df_h1 = mt5.get_rates(timeframe="H1", count=30)

            high_24h = float(df_d1["high"].iloc[-1]) if df_d1 is not None and not df_d1.empty else 0.0
            low_24h = float(df_d1["low"].iloc[-1]) if df_d1 is not None and not df_d1.empty else 0.0

            atr_val = 2.5
            rsi_val = 50.0
            if df_h1 is not None and len(df_h1) >= 15:
                ta = TechnicalAnalyzer()
                df_ta = ta.add_atr(df_h1.copy(), period=14)
                df_ta = ta.add_rsi(df_ta, period=14)
                if "atr" in df_ta.columns and not df_ta["atr"].isna().iloc[-1]:
                    atr_val = round(float(df_ta["atr"].iloc[-1]), 2)
                if "rsi" in df_ta.columns and not df_ta["rsi"].isna().iloc[-1]:
                    rsi_val = round(float(df_ta["rsi"].iloc[-1]), 1)

            current_price = tick.get("bid", 0.0) if tick else 0.0
            spread_pts = tick.get("spread", 0.0) if tick else 0.0

            # Calculate 24h range percent
            range_span = high_24h - low_24h
            pct_in_range = 50.0
            if range_span > 0:
                pct_in_range = max(0.0, min(100.0, ((current_price - low_24h) / range_span) * 100.0))

            # Temporal Self-Attention and Candle Physics (MetaQuotes Neural Net Book)
            attention_conc = 0.0
            anchor_type = "PIVOT"
            if df_h1 is not None and len(df_h1) >= 20:
                try:
                    from ai.attention_scorer import AttentionMarketScorer
                    scorer = AttentionMarketScorer(window=20)
                    att_res = scorer.compute_attention(df_h1)
                    attention_conc = round(att_res.get("concentration", 0.0), 1)
                    anchor_type = att_res.get("anchor_type", "PIVOT")
                except Exception:
                    pass

            return JSONResponse({
                "success": True,
                "current_price": current_price,
                "ask": tick.get("ask", current_price) if tick else current_price,
                "spread": spread_pts,
                "high_24h": high_24h,
                "low_24h": low_24h,
                "pct_in_range": round(pct_in_range, 1),
                "atr": atr_val,
                "rsi": rsi_val,
                "attention_concentration": attention_conc,
                "anchor_type": anchor_type,
            })
        return JSONResponse({"success": False, "error": "MT5 offline"})
    except Exception as e:
        logger.error(f"Barometer error: {e}")
        return JSONResponse({"success": False, "error": str(e)})


@app.on_event("startup")
async def start_realtime_streamer():
    """Background task to broadcast real-time price updates to WebSocket subscribers."""
    import asyncio
    async def stream_loop():
        from core.mt5_connector import get_mt5_connector
        logger.info("📡 Starting real-time WebSocket market streamer")
        mt5 = get_mt5_connector()
        while True:
            try:
                clients = globals().get("connected_clients", set())
                if clients:
                    if mt5.connect(max_retries=1, retry_delay=0.1):
                        tick = mt5.get_current_tick()
                        if tick and "bid" in tick:
                            await broadcast({
                                "type": "price_update",
                                "price": tick.get("bid", 0.0),
                                "ask": tick.get("ask", 0.0),
                                "spread": tick.get("spread", 0.0),
                                "timestamp": int(datetime.now(timezone.utc).timestamp()),
                            })
            except Exception as e:
                logger.debug(f"Streamer tick exception: {e}")
            await asyncio.sleep(2.0)

    asyncio.create_task(stream_loop())


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

    except (WebSocketDisconnect, Exception):
        connected_clients.discard(websocket)
        logger.info(f"WebSocket client disconnected ({len(connected_clients)} total)")


async def broadcast(data: dict):
    """Broadcast data to all connected WebSocket clients."""
    global connected_clients
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
