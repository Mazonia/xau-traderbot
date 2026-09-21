# ⚡ XAUUSD AI Trading Bot

An AI-powered, fully automated trading bot for **Gold (XAUUSD)** via **Exness / MetaTrader 5**.

## 🎯 Features

- **Multi-Strategy Engine** — Scalping (M5), Day Trading (H1), Swing Trading (H4/D1)
- **AI/ML Predictions** — LSTM neural network + XGBoost for price direction forecasting
- **News Intelligence** — Real-time financial news with FinBERT + Gemini sentiment analysis
- **Market Regime Detection** — ADX-based classification (trending/ranging/volatile)
- **Confluence Scoring** — Weighted signal aggregation (technical + AI + sentiment + regime)
- **Risk Management** — Position sizing, daily loss limits, spread filters, trailing stops
- **Web Dashboard** — Real-time monitoring with TradingView charts (dark premium UI)
- **Telegram Alerts** — Trade notifications, daily summaries, news alerts, remote control
- **Automatic Execution** — Full lifecycle: signal → validation → execution → management

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.11+
- MetaTrader 5 terminal (with Exness account connected)
- API keys: Gemini, Finnhub, Alpha Vantage, Telegram

### 2. Install Dependencies
```bash
cd XAUUSD-AI-Trading-Bot
pip install -r requirements.txt
```

### 3. Configure
```bash
# Copy the env template and fill in your credentials
cp config/.env.example config/.env
# Edit config/.env with your API keys
```

### 4. Train AI Models (First Time)
```bash
python main.py --train
```

### 5. Run the Bot
```bash
# Start in demo mode (default)
python main.py

# Start with dashboard
python main.py --dashboard

# Backtest strategies
python main.py --backtest
```

## 📊 Architecture

```
Data Layer (MT5 + News APIs)
    ↓
Analysis (Technical Indicators + Sentiment)
    ↓
AI Engine (LSTM + XGBoost Predictions)
    ↓
Strategy Engine (Scalping / Day / Swing)
    ↓
Signal Aggregator (Confluence Score 0-100)
    ↓
Risk Manager (Position Sizing + Safety Checks)
    ↓
Trade Executor (MT5 Orders)
    ↓
Monitoring (Dashboard + Telegram)
```

## ⚠️ Disclaimer

**Trading involves significant risk of loss.** This bot is for educational purposes. Always test on a demo account first. Never risk money you cannot afford to lose.

## 📄 License

MIT
