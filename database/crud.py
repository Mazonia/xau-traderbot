"""
Database CRUD Operations

Helper functions for creating, reading, updating, and querying
trade records, signals, news events, and performance data.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import desc, func
from loguru import logger

from database.models import (
    TradeLesson,
    AdaptiveWeight,
    EconomicEvent,
    NewsEvent,
    PerformanceSnapshot,
    Signal,
    Trade,
    get_session,
)


# ── Trade Operations ─────────────────────────────────────────────────────


def create_trade(
    ticket: int,
    order_type: str,
    strategy: str,
    volume: float,
    entry_price: float,
    stop_loss: float = 0.0,
    take_profit: float = 0.0,
    confluence_score: float = 0.0,
    sentiment_score: float = 0.0,
    ai_prediction: str = "",
    ai_confidence: float = 0.0,
    regime: str = "",
    comment: str = "",
) -> Trade:
    """Record a new trade in the database."""
    session = get_session()
    try:
        trade = Trade(
            ticket=ticket,
            order_type=order_type,
            strategy=strategy,
            volume=volume,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            confluence_score=confluence_score,
            sentiment_score=sentiment_score,
            ai_prediction=ai_prediction,
            ai_confidence=ai_confidence,
            regime=regime,
            comment=comment,
            status="OPEN",
        )
        session.add(trade)
        session.commit()
        logger.debug(f"Trade recorded: {trade}")
        return trade
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create trade record: {e}")
        raise
    finally:
        session.close()


def close_trade(
    ticket: int,
    exit_price: float,
    profit: float,
    swap: float = 0.0,
    commission: float = 0.0,
) -> Optional[Trade]:
    """Update a trade record when it's closed."""
    session = get_session()
    try:
        trade = session.query(Trade).filter_by(ticket=ticket, status="OPEN").first()
        if not trade:
            logger.warning(f"No open trade found with ticket {ticket}")
            return None

        now = datetime.now(timezone.utc)
        trade.exit_price = exit_price
        trade.profit = profit
        trade.swap = swap
        trade.commission = commission
        trade.status = "CLOSED"
        trade.closed_at = now

        if trade.opened_at:
            delta = now - trade.opened_at
            trade.duration_minutes = int(delta.total_seconds() / 60)

        session.commit()
        logger.debug(f"Trade closed: {trade}")
        return trade
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to close trade record: {e}")
        raise
    finally:
        session.close()


def get_open_trades() -> list[Trade]:
    """Get all open trades."""
    session = get_session()
    try:
        return session.query(Trade).filter_by(status="OPEN").all()
    finally:
        session.close()


def get_recent_trades(limit: int = 50) -> list[Trade]:
    """Get recent trades ordered by opened_at descending."""
    session = get_session()
    try:
        return (
            session.query(Trade)
            .order_by(desc(Trade.opened_at))
            .limit(limit)
            .all()
        )
    finally:
        session.close()


def get_daily_trades(date: datetime | None = None) -> list[Trade]:
    """Get all trades for a specific date (defaults to today)."""
    if date is None:
        date = datetime.now(timezone.utc)

    start_of_day = date.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    session = get_session()
    try:
        return (
            session.query(Trade)
            .filter(Trade.opened_at >= start_of_day, Trade.opened_at < end_of_day)
            .order_by(desc(Trade.opened_at))
            .all()
        )
    finally:
        session.close()


def get_daily_pnl(date: datetime | None = None) -> float:
    """Calculate total P&L for a specific day."""
    trades = get_daily_trades(date)
    return sum(t.profit for t in trades if t.profit is not None)


def get_trade_stats(days: int = 30) -> dict:
    """Calculate trading statistics for the last N days."""
    session = get_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        trades = (
            session.query(Trade)
            .filter(Trade.status == "CLOSED", Trade.closed_at >= cutoff)
            .all()
        )

        now_utc = datetime.now(timezone.utc)
        today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
        
        def is_today(closed_dt):
            if not closed_dt:
                return False
            # Normalize to offset-aware UTC
            if closed_dt.tzinfo is None:
                closed_dt = closed_dt.replace(tzinfo=timezone.utc)
            return closed_dt >= today_start

        today_trades = [t for t in trades if is_today(t.closed_at)]
        today_realized_profit = sum(t.profit for t in today_trades if t.profit is not None)

        if not trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0.0,
                "total_profit": 0.0,
                "today_realized_profit": 0.0,
                "avg_profit": 0.0,
                "avg_loss": 0.0,
                "profit_factor": 0.0,
                "largest_win": 0.0,
                "largest_loss": 0.0,
            }

        winners = [t for t in trades if t.profit and t.profit > 0]
        losers = [t for t in trades if t.profit and t.profit < 0]

        total_wins = sum(t.profit for t in winners) if winners else 0.0
        total_losses = abs(sum(t.profit for t in losers)) if losers else 0.0
        total_profit = sum(t.profit for t in trades if t.profit is not None)

        # Ensure profit_factor is JSON serializable (never inf)
        if total_losses > 0:
            pf = round(total_wins / total_losses, 2)
        elif total_wins > 0:
            pf = round(min(99.9, total_wins), 2)
        else:
            pf = 0.0

        return {
            "total_trades": len(trades),
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "win_rate": round((len(winners) / len(trades) * 100), 1) if trades else 0.0,
            "total_profit": round(total_profit, 2),
            "today_realized_profit": round(today_realized_profit, 2),
            "avg_profit": round(total_wins / len(winners), 2) if winners else 0.0,
            "avg_loss": round(total_losses / len(losers), 2) if losers else 0.0,
            "profit_factor": pf,
            "largest_win": round(max((t.profit for t in winners), default=0.0), 2),
            "largest_loss": round(min((t.profit for t in losers), default=0.0), 2),
        }
    finally:
        session.close()


def sync_mt5_deals(deals_list: list[dict]) -> int:
    """
    Sync closed deals from MT5 history into the SQLite database.
    Ensures every closed trade from the broker exists and is marked CLOSED with correct profit.
    """
    if not deals_list:
        return 0
    session = get_session()
    synced_count = 0
    try:
        for t in deals_list:
            ticket = t.get("ticket")
            if not ticket:
                continue
            existing = session.query(Trade).filter(Trade.ticket == ticket).first()
            if existing:
                existing.exit_price = t.get("exit_price", existing.exit_price)
                existing.profit = t.get("profit", existing.profit)
                existing.swap = t.get("swap", existing.swap)
                existing.commission = t.get("commission", existing.commission)
                existing.status = "CLOSED"
                if t.get("closed_at"):
                    existing.closed_at = t.get("closed_at")
            else:
                trade = Trade(
                    ticket=ticket,
                    order_type=t.get("type", "BUY"),
                    strategy=t.get("strategy", "MT5_SYNC"),
                    volume=t.get("volume", 0.01),
                    entry_price=t.get("entry_price", 0.0),
                    exit_price=t.get("exit_price", 0.0),
                    profit=t.get("profit", 0.0),
                    swap=t.get("swap", 0.0),
                    commission=t.get("commission", 0.0),
                    status="CLOSED",
                    opened_at=t.get("opened_at"),
                    closed_at=t.get("closed_at"),
                    comment=t.get("comment", ""),
                )
                session.add(trade)
            synced_count += 1
        session.commit()
        return synced_count
    except Exception as e:
        session.rollback()
        logger.error(f"Error syncing MT5 deals into SQLite: {e}")
        return 0
    finally:
        session.close()


# ── Signal Operations ────────────────────────────────────────────────────


def create_signal(
    direction: str,
    strategy: str,
    timeframe: str,
    confluence_score: float,
    technical_score: float = 0.0,
    ai_score: float = 0.0,
    sentiment_score: float = 0.0,
    regime_score: float = 0.0,
    was_executed: bool = False,
    rejection_reason: str = "",
    price_at_signal: float = 0.0,
) -> Signal:
    """Record a trading signal."""
    session = get_session()
    try:
        signal = Signal(
            direction=direction,
            strategy=strategy,
            timeframe=timeframe,
            confluence_score=confluence_score,
            technical_score=technical_score,
            ai_score=ai_score,
            sentiment_score=sentiment_score,
            regime_score=regime_score,
            was_executed=was_executed,
            rejection_reason=rejection_reason,
            price_at_signal=price_at_signal,
        )
        session.add(signal)
        session.commit()
        return signal
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to create signal record: {e}")
        raise
    finally:
        session.close()


# ── News Operations ──────────────────────────────────────────────────────


def save_news_event(
    source: str,
    headline: str,
    summary: str = "",
    url: str = "",
    category: str = "",
    sentiment: str = "NEUTRAL",
    sentiment_score: float = 0.0,
    finbert_score: float = 0.0,
    gemini_score: float = 0.0,
    gemini_analysis: str = "",
    impact_level: str = "LOW",
    published_at: datetime | None = None,
) -> NewsEvent:
    """Save a news event with sentiment analysis."""
    session = get_session()
    try:
        event = NewsEvent(
            source=source,
            headline=headline,
            summary=summary,
            url=url,
            category=category,
            sentiment=sentiment,
            sentiment_score=sentiment_score,
            finbert_score=finbert_score,
            gemini_score=gemini_score,
            gemini_analysis=gemini_analysis,
            impact_level=impact_level,
            published_at=published_at,
        )
        session.add(event)
        session.commit()
        return event
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save news event: {e}")
        raise
    finally:
        session.close()


def get_recent_sentiment(hours: int = 6) -> float:
    """Get average sentiment score from the last N hours."""
    session = get_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        result = (
            session.query(func.avg(NewsEvent.sentiment_score))
            .filter(NewsEvent.fetched_at >= cutoff)
            .scalar()
        )
        return result or 0.0
    finally:
        session.close()


# ── Performance Operations ───────────────────────────────────────────────


def save_performance_snapshot(
    balance: float,
    equity: float,
    daily_pnl: float = 0.0,
    total_pnl: float = 0.0,
    total_trades: int = 0,
    winning_trades: int = 0,
    losing_trades: int = 0,
    win_rate: float = 0.0,
    profit_factor: float = 0.0,
    max_drawdown: float = 0.0,
    sharpe_ratio: float = 0.0,
    avg_risk_reward: float = 0.0,
    active_strategy: str = "",
    market_regime: str = "",
) -> PerformanceSnapshot:
    """Save a performance snapshot."""
    session = get_session()
    try:
        snapshot = PerformanceSnapshot(
            balance=balance,
            equity=equity,
            daily_pnl=daily_pnl,
            total_pnl=total_pnl,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=win_rate,
            profit_factor=profit_factor,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe_ratio,
            avg_risk_reward=avg_risk_reward,
            active_strategy=active_strategy,
            market_regime=market_regime,
        )
        session.add(snapshot)
        session.commit()
        return snapshot
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save performance snapshot: {e}")
        raise
    finally:
        session.close()


def get_equity_curve(days: int = 30) -> list[dict]:
    """Get equity curve data for charting."""
    session = get_session()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        snapshots = (
            session.query(PerformanceSnapshot)
            .filter(PerformanceSnapshot.snapshot_at >= cutoff)
            .order_by(PerformanceSnapshot.snapshot_at)
            .all()
        )
        return [
            {
                "time": s.snapshot_at.isoformat(),
                "balance": s.balance,
                "equity": s.equity,
                "pnl": s.daily_pnl,
            }
            for s in snapshots
        ]
    finally:
        session.close()


# ── Self-Learning & Adaptive Weight CRUD ─────────────────────────────────

def save_trade_lesson(
    ticket: int,
    symbol: str,
    order_type: str,
    strategy: str,
    profit: float,
    outcome: str,
    mistake_category: str,
    lesson_summary: str,
    defensive_rule: str,
    mistake_signature: str = "{}",
) -> TradeLesson:
    """Save an analyzed trade lesson into the database."""
    session = get_session()
    try:
        lesson = TradeLesson(
            ticket=ticket,
            symbol=symbol,
            order_type=order_type,
            strategy=strategy,
            profit=profit,
            outcome=outcome,
            mistake_category=mistake_category,
            lesson_summary=lesson_summary,
            defensive_rule=defensive_rule,
            mistake_signature=mistake_signature,
        )
        session.add(lesson)
        session.commit()
        session.refresh(lesson)
        return lesson
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to save trade lesson for #{ticket}: {e}")
        raise
    finally:
        session.close()


def get_recent_lessons(limit: int = 15) -> list[TradeLesson]:
    """Retrieve recent trade lessons and mistake analyses."""
    session = get_session()
    try:
        return (
            session.query(TradeLesson)
            .order_by(desc(TradeLesson.created_at))
            .limit(limit)
            .all()
        )
    finally:
        session.close()


def save_or_update_adaptive_weight(
    component: str,
    weight: float,
    multiplier: float,
    win: bool,
    pnl: float,
) -> AdaptiveWeight:
    """Update or insert adaptive weight metrics for a component/strategy."""
    session = get_session()
    try:
        record = session.query(AdaptiveWeight).filter(AdaptiveWeight.component == component).first()
        if not record:
            record = AdaptiveWeight(
                component=component,
                weight=weight,
                multiplier=multiplier,
                win_count=1 if win else 0,
                loss_count=0 if win else 1,
                total_pnl=pnl,
            )
            session.add(record)
        else:
            record.weight = weight
            record.multiplier = multiplier
            if win:
                record.win_count += 1
            else:
                record.loss_count += 1
            record.total_pnl += pnl
            record.updated_at = datetime.now(timezone.utc)

        session.commit()
        session.refresh(record)
        return record
    except Exception as e:
        session.rollback()
        logger.error(f"Failed to update adaptive weight for {component}: {e}")
        raise
    finally:
        session.close()


def get_all_adaptive_weights() -> dict[str, dict]:
    """Get dictionary of all adaptive weights and multipliers."""
    session = get_session()
    try:
        records = session.query(AdaptiveWeight).all()
        return {
            r.component: {
                "weight": r.weight,
                "multiplier": r.multiplier,
                "win_count": r.win_count,
                "loss_count": r.loss_count,
                "total_pnl": r.total_pnl,
            }
            for r in records
        }
    finally:
        session.close()
