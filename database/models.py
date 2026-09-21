"""
Database ORM Models

SQLAlchemy models for persisting trades, signals, news events,
and performance snapshots.
"""

from datetime import datetime, timezone

from sqlalchemy import event
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import get_settings


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Trade(Base):
    """Record of every trade executed by the bot."""

    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket = Column(Integer, unique=True, nullable=False, index=True)
    symbol = Column(String(20), default="XAUUSD")
    order_type = Column(String(10), nullable=False)  # BUY or SELL
    strategy = Column(String(30), nullable=False)     # scalping, day_trading, swing
    volume = Column(Float, nullable=False)
    entry_price = Column(Float, nullable=False)
    exit_price = Column(Float, nullable=True)
    stop_loss = Column(Float, nullable=True)
    take_profit = Column(Float, nullable=True)
    profit = Column(Float, default=0.0)
    swap = Column(Float, default=0.0)
    commission = Column(Float, default=0.0)
    confluence_score = Column(Float, default=0.0)
    sentiment_score = Column(Float, default=0.0)
    ai_prediction = Column(String(10), nullable=True)  # BULLISH, BEARISH, NEUTRAL
    ai_confidence = Column(Float, default=0.0)
    regime = Column(String(20), nullable=True)          # trending, ranging, volatile
    comment = Column(Text, default="")
    status = Column(String(15), default="OPEN")         # OPEN, CLOSED, CANCELLED
    opened_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    closed_at = Column(DateTime, nullable=True)
    duration_minutes = Column(Integer, nullable=True)

    def __repr__(self):
        return (
            f"<Trade ticket={self.ticket} {self.order_type} "
            f"{self.volume} lots @ {self.entry_price} "
            f"P&L={self.profit:+.2f}>"
        )


class Signal(Base):
    """Record of every trading signal generated (whether acted on or not)."""

    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(20), default="XAUUSD")
    direction = Column(String(10), nullable=False)     # BUY, SELL, HOLD
    strategy = Column(String(30), nullable=False)
    timeframe = Column(String(5), nullable=False)
    confluence_score = Column(Float, default=0.0)
    technical_score = Column(Float, default=0.0)
    ai_score = Column(Float, default=0.0)
    sentiment_score = Column(Float, default=0.0)
    regime_score = Column(Float, default=0.0)
    was_executed = Column(Boolean, default=False)
    rejection_reason = Column(String(100), nullable=True)
    price_at_signal = Column(Float, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return (
            f"<Signal {self.direction} {self.strategy} "
            f"score={self.confluence_score:.1f} "
            f"executed={self.was_executed}>"
        )


class NewsEvent(Base):
    """Cached news articles and their sentiment scores."""

    __tablename__ = "news_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)        # finnhub, alpha_vantage, etc.
    headline = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    url = Column(String(500), nullable=True)
    category = Column(String(30), nullable=True)       # gold, fed, geopolitical, etc.
    sentiment = Column(String(10), nullable=True)       # BULLISH, BEARISH, NEUTRAL
    sentiment_score = Column(Float, default=0.0)       # -1.0 to 1.0
    finbert_score = Column(Float, default=0.0)
    gemini_score = Column(Float, default=0.0)
    gemini_analysis = Column(Text, nullable=True)
    impact_level = Column(String(10), default="LOW")   # LOW, MEDIUM, HIGH
    published_at = Column(DateTime, nullable=True)
    fetched_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<NewsEvent '{self.headline[:50]}...' sentiment={self.sentiment}>"


class EconomicEvent(Base):
    """Scheduled economic events (FOMC, NFP, CPI, etc.)."""

    __tablename__ = "economic_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    country = Column(String(10), default="US")
    impact = Column(String(10), nullable=False)        # LOW, MEDIUM, HIGH
    actual = Column(String(20), nullable=True)
    forecast = Column(String(20), nullable=True)
    previous = Column(String(20), nullable=True)
    event_time = Column(DateTime, nullable=False)
    is_processed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<EconomicEvent '{self.name}' impact={self.impact} @ {self.event_time}>"



class TradeLesson(Base):
    """Record of lessons and mistake analysis derived from closed trades."""

    __tablename__ = "trade_lessons"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket = Column(Integer, index=True, nullable=False)
    symbol = Column(String(20), default="XAUUSD")
    order_type = Column(String(10), nullable=False)
    strategy = Column(String(30), nullable=False)
    profit = Column(Float, nullable=False)
    outcome = Column(String(10), nullable=False)  # WIN, LOSS, SCRATCH
    mistake_category = Column(String(40), default="NONE")
    lesson_summary = Column(Text, nullable=False)
    defensive_rule = Column(Text, nullable=False)
    mistake_signature = Column(Text, default="{}")  # JSON string of market conditions at entry
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<TradeLesson ticket={self.ticket} outcome={self.outcome} category={self.mistake_category}>"


class AdaptiveWeight(Base):
    """Record of self-learning adaptive weights for strategies and confluence components."""

    __tablename__ = "adaptive_weights"

    id = Column(Integer, primary_key=True, autoincrement=True)
    component = Column(String(40), unique=True, nullable=False, index=True)
    weight = Column(Float, nullable=False)
    multiplier = Column(Float, default=1.0)
    win_count = Column(Integer, default=0)
    loss_count = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<AdaptiveWeight {self.component}={self.weight:.2f} (x{self.multiplier:.2f})>"

class PerformanceSnapshot(Base):
    """Periodic snapshots of bot performance metrics."""

    __tablename__ = "performance_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    balance = Column(Float, nullable=False)
    equity = Column(Float, nullable=False)
    daily_pnl = Column(Float, default=0.0)
    total_pnl = Column(Float, default=0.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    losing_trades = Column(Integer, default=0)
    win_rate = Column(Float, default=0.0)
    profit_factor = Column(Float, default=0.0)
    max_drawdown = Column(Float, default=0.0)
    sharpe_ratio = Column(Float, default=0.0)
    avg_risk_reward = Column(Float, default=0.0)
    active_strategy = Column(String(30), nullable=True)
    market_regime = Column(String(20), nullable=True)
    snapshot_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return (
            f"<PerformanceSnapshot balance={self.balance:.2f} "
            f"pnl={self.daily_pnl:+.2f} wr={self.win_rate:.1f}%>"
        )


# ── Database Engine & Session Factory ────────────────────────────────────

_engine = None
_SessionFactory = None


def get_engine():
    """Get or create the SQLAlchemy engine with WAL concurrency and 30s busy timeout."""
    global _engine
    if _engine is None:
        settings = get_settings()
        is_sqlite = "sqlite" in settings.database.url.lower()
        connect_args = {"timeout": 30.0} if is_sqlite else {}

        _engine = create_engine(
            settings.database.url,
            echo=settings.database.echo,
            pool_pre_ping=True,
            connect_args=connect_args,
        )

        if is_sqlite:
            @event.listens_for(_engine, "connect")
            def set_sqlite_pragma(dbapi_connection, connection_record):
                try:
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA synchronous=NORMAL;")
                    cursor.close()
                except Exception:
                    pass

    return _engine


def get_session() -> Session:
    """Get a new database session."""
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine())
    return _SessionFactory()


def init_database():
    """Create all tables if they don't exist."""
    engine = get_engine()
    Base.metadata.create_all(engine)
    from loguru import logger
    logger.info(f"Database initialized: {engine.url}")
