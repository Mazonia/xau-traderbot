# ⚡ XAUUSD AI Trading Bot

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![MetaTrader 5](https://img.shields.io/badge/Broker-Exness%20%2F%20MT5-green.svg)](https://www.metatrader5.com/)
[![AI Powered](https://img.shields.io/badge/AI-Gemini%203.6%20Flash%20%2B%20XGBoost-orange.svg)](https://deepmind.google/technologies/gemini/)
[![Tests](https://img.shields.io/badge/Tests-18%2F18%20Passing-brightgreen.svg)](https://pytest.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

An institutional-grade, fully autonomous algorithmic trading robot designed for **Gold (XAUUSD)** via **MetaTrader 5 (Exness)**. It fuses classical quantitative technical strategies with modern machine learning (XGBoost) and deep macroeconomic intelligence powered by **Gemini 3.6 Flash**.

---

## 🌟 Key Highlights & Features

### 1. Multi-Strategy Confluence Engine
- **Scalping Strategy (M5 / M1):** High-frequency momentum scalping using EMA 30/60/200 crossovers, RSI bounds, and MACD divergence.
- **Day Trading Strategy (H1 / M15):** Trend-following channel breakouts using Bollinger Bands and ATR expansion.
- **Swing Trading Strategy (H4 / D1):** Multi-day macroeconomic trend capture with dynamic support/resistance zones.
- **Confluence Aggregator:** Weights technical indicators (40%), XGBoost classification (25%), Gemini sentiment (20%), and market regime (15%) into a 0–100 score. Only signals exceeding threshold (default: 65–75) execute.

### 2. Deep Macro News & Sentiment Intelligence
- **Dual-Stream Aggregation:** Live continuous news polling from both **Finnhub** and **Alpha Vantage** (monetary policy, inflation, and fiscal topics).
- **Gemini 3.6 Flash Macro Reasoning:** Generates structured macroeconomic analysis evaluating impact on gold price, USD yields, and risk-off sentiment.
- **High-Impact Event Cooldowns:** Detects imminent or breaking macroeconomic events (FOMC rate decisions, Non-Farm Payrolls, CPI, GDP) and automatically pauses entries during extreme volatility spikes.

### 3. Machine Learning Signal Classifier
- **XGBoost Classifier:** Trained on multi-timeframe engineered indicators (RSI, MACD, Bollinger position, ATR ratios, momentum, and returns lags).
- **Directional Probability:** Generates real-time probabilistic output for `BUY`, `SELL`, and `HOLD` with confidence scoring.

### 5. Interactive 2-Way Telegram Command Center
- **Zero-Latency Real-Time Polling:** Runs on continuous long-polling (`poll_interval=0.0s`) for instantaneous response times (< 100ms).
- **Native Telegram Menu:** Registered server-side via `setMyCommands` (accessible via the `[Menu]` button in Telegram).
- **Interactive Inline Buttons:**
  - 📊 **Status & Balance:** Instant account balance, equity, margin level, and bot health.
  - 📈 **Open Positions:** Live positions with floating P&L and individual ticket close buttons.
  - 💰 **P&L Summary:** Realized daily and 30-day performance.
  - 📜 **Recent Trades:** Full trade history with exact broker exit metrics.
  - 📰 **News & AI Sentiment:** Latest Gemini macroeconomic notes and composite 6-hour sentiment score.
  - 🧠 **Market Regime:** Current ADX trend strength, volatility label, and active strategy matrix.
  - 🎓 **Self-Learning & Adaptation:** Current adaptive strategy multipliers, dynamic confluence weights, active mistake signatures, and latest formulated defensive rules.
  - 🏷️ **Gold Price & Spread:** Real-time bid, ask, and spread points.
  - ⏸️ **Pause / Resume:** Remote emergency kill-switch to pause new order generation.
  - 🛑 **EMERGENCY CLOSE ALL:** Instant market order execution to flatten all open trades with confirmation guard.

### 6. Institutional Risk & Execution Management
- **Dynamic Lot Sizing:** Position size dynamically calculated based on account balance, stop-loss distance, and broker pip values. Default configuration tailored to 0.01 – 0.05 lots.
- **Dynamic ATR Trailing Stops:** Tightens stop-loss as trades advance in profit, with automated breakeven lock at 1:1 Risk-Reward ratio.
- **Broker Filling Mode Auto-Detection:** Automatically negotiates `ORDER_FILLING_FOK`, `ORDER_FILLING_IOC`, or `ORDER_FILLING_RETURN` for Exness Standard accounts.
- **Deal History Synchronization:** Fetches exact exit prices, swaps, and commissions from MT5 historical deal logs on position close.

### 7. Glassmorphic Web Dashboard (FastAPI & Chart.js)
- Real-time dark-mode command terminal on `http://localhost:8080`.
- Fast non-blocking endpoints for account overview, positions, equity curve, and news stream.

---

## 🏗️ Architecture Overview

```
                           ┌────────────────────────┐
                           │   Telegram Remote UI   │
                           │  (Mobile Command Ctr)  │
                           └───────────▲────────────┘
                                       │ 50-100ms
┌──────────────────────┐   ┌───────────▼────────────┐   ┌──────────────────────┐
│  Market Data Feed    │──▶│      TradingBot        │◀──│  News APIs (Finnhub  │
│ (MetaTrader 5 / M5-D1)│   │   Orchestrator Loop    │   │   & Alpha Vantage)   │
└──────────────────────┘   └───────────┬────────────┘   └──────────┬───────────┘
                                       │                           │
                   ┌───────────────────┼───────────────────┐       ▼
                   ▼                   ▼                   ▼ ┌───────────────┐
         ┌───────────────────┐┌──────────────────┐┌─────────▼┐│ Gemini 3.6    │
         │ Technical Analysis││ Regime Detector  ││ XGBoost  ││ Flash Engine │
         │ (RSI, MACD, BB)   ││ (ADX & Volatility││Classifier│└───────┬───────┘
         └─────────┬─────────┘└────────┬─────────┘└────┬─────┘        │
                   │                   │               │              │
                   └───────────────────┼───────────────┴──────────────┘
                                       ▼
                         ┌───────────────────────────┐
                         │   Confluence Aggregator   │
                         │   (Score 0 - 100 Points)  │
                         └─────────────┬─────────────┘
                                       ▼
                         ┌───────────────────────────┐
                         │   Risk Manager & Safety   │
                         │ (Daily Loss, Margin, Lot) │
                         └─────────────┬─────────────┘
                                       │ ~2ms IPC
                                       ▼
                         ┌───────────────────────────┐
                         │    MetaTrader 5 Terminal  │
                         │ (Exness Trade Execution)  │
                         └───────────────────────────┘
```

---

## 🚀 Quick Start Guide (Windows)

### 1. Prerequisites
- **Windows 10 / 11**
- **Python 3.11+** installed and added to your `PATH`
- **MetaTrader 5 Terminal** (installed with your Exness Demo or Live login)
- Valid API Keys:
  - **Google Gemini API Key** (for news reasoning)
  - **Finnhub API Key** (for market news stream)
  - **Alpha Vantage API Key** (for monetary & economic news)
  - **Telegram Bot Token & Chat ID** (from [@BotFather](https://t.me/botfather))

### 2. Installation
Clone the repository:
```bash
git clone https://github.com/Mazonia/xau-traderbot.git
cd xau-traderbot
```

Install dependencies:
```powershell
python -m pip install -r requirements.txt
```

### 3. Configuration
Configure your environment variables in `.env`:
```env
# MetaTrader 5 / Exness
MT5_LOGIN=your_mt5_account_number
MT5_PASSWORD=your_mt5_password
MT5_SERVER=Exness-MT5Trial10  # or your broker server name

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token_from_botfather
TELEGRAM_CHAT_ID=your_telegram_chat_id

# AI & News APIs
GEMINI_API_KEY=your_gemini_api_key
FINNHUB_API_KEY=your_finnhub_api_key
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_api_key

# Bot Operational Settings
DEMO_MODE=true
SYMBOL=XAUUSD
LOG_LEVEL=INFO
```

### 4. Running the Components

We provide dedicated one-click Windows batch launchers:

| Batch Script | PowerShell Command | Description |
| :--- | :--- | :--- |
| **`run_bot.bat`** | `.\run_bot.bat` | Starts the autonomous live trading bot engine |
| **`run_telegram.bat`** | `.\run_telegram.bat` | Starts the standalone interactive Telegram Command Center |
| **`run_dashboard.bat`** | `.\run_dashboard.bat` | Launches the web dashboard on `http://localhost:8080` |
| **`run_backtest.bat`** | `.\run_backtest.bat` | Runs historical backtest simulation with full metrics |
| **`run.bat`** | `.\run.bat --help` | Universal CLI launcher with UTF-8 support |

---

## 📱 Telegram Command Reference

| Command | Action |
| :--- | :--- |
| `/start` or `/menu` | Open the interactive Command Center button dashboard |
| `/status` | View account balance, floating profit, margin level, and bot state |
| `/positions` | List open trades with floating P&L and individual close buttons |
| `/pnl` | View today's realized profit/loss and 30-day performance |
| `/trades` | View last 5 closed trades with exact exit price and net profit |
| `/news` | View current macro sentiment score and Gemini market analysis |
| `/regime` | View current market regime (trending/ranging) and active strategies |
| `/price` | Real-time XAUUSD bid, ask, and spread points |
| `/pause` | Temporarily pause automated trade execution |
| `/resume` | Resume automated trade execution |
| `/closeall` | Trigger immediate confirmation to close all open trades |
| `/setlot <size>` | Set default lot size (e.g. `/setlot 0.02`) |
| `/setrisk <pct>` | Set max risk percent per trade (e.g. `/setrisk 1.5`) |
| `/help` | Show command cheatsheet and usage tips |

---

## 🧪 Testing & Verification

Run the automated test suite:
```powershell
python -m pytest -v
```
All **18 unit tests** validate:
- Backtesting performance calculation (Sharpe ratio, max drawdown, win rate)
- Risk manager margin constraints, spread boundaries, and lot sizing
- Strategy generation and regime detection
- Confluence aggregation and opposing sentiment filters
- Technical indicator calculations (RSI, MACD, Bollinger Bands, ATR)

---

## 📁 Repository Structure

```
XAUUSD-AI-Trading-Bot/
├── ai/                     # Machine Learning & AI Models
│   ├── models/             # Trained XGBoost & Scaler artifacts
│   ├── price_predictor.py  # Deep learning price sequence predictor
│   └── signal_classifier.py# XGBoost classifier for directional prediction
├── analysis/               # Quantitative & Technical Analysis
│   ├── sentiment.py        # Sentiment score aggregation & decay
│   └── technical.py        # 40+ technical indicator pipelines
├── backtesting/            # Historical Simulation Engine
│   ├── backtester.py       # Event-driven backtesting engine
│   └── performance.py      # Sharpe, Sortino, Drawdown, Profit Factor
├── config/                 # Settings & Configuration
│   ├── settings.py         # Pydantic settings with validation
│   └── trading_params.yaml # Tunable strategy and risk parameters
├── core/                   # Core Engine Orchestration
│   ├── bot.py              # Main trading loop & lifecycle
│   ├── mt5_connector.py    # MetaTrader 5 IPC connector & deal history
│   └── scheduler.py        # Background task scheduler
├── dashboard/              # Web Dashboard
│   ├── app.py              # FastAPI application server
│   └── static/             # HTML5, CSS3, and JavaScript front-end
├── database/               # Persistence Layer
│   ├── crud.py             # Database query operations
│   └── models.py           # SQLAlchemy database schemas
├── execution/              # Order Execution & Safety
│   ├── risk_manager.py     # Position sizing & risk rules
│   ├── trade_executor.py   # MT5 market order execution & position sync
│   └── trailing_stop.py    # Dynamic ATR trailing stop & breakeven
├── news/                   # Macro Intelligence
│   ├── economic_events.py  # High-impact calendar & cooldown logic
│   ├── news_analyzer.py    # Gemini 3.6 Flash reasoning & FinBERT
│   └── news_fetcher.py     # Finnhub & Alpha Vantage news aggregator
├── notifications/          # Alerts & Remote Control
│   ├── alert_manager.py    # Priority throttling & notification delivery
│   └── telegram_bot.py     # 2-way interactive Telegram Command Center
├── tests/                  # Automated Test Suite (Pytest)
├── requirements.txt        # Python package dependencies
├── run.bat                 # Universal launcher script (UTF-8)
├── run_bot.bat             # Start trading bot launcher
├── run_dashboard.bat       # Start web dashboard launcher
├── run_telegram.bat        # Start Telegram Command Center launcher
└── run_backtest.bat        # Start backtesting launcher
```

---

## ⚠️ Risk Disclaimer

Trading Foreign Exchange and Commodities (including Gold / XAUUSD) on margin carries a high level of risk and may not be suitable for all investors. The high degree of leverage can work against you as well as for you. Before deciding to trade, carefully consider your investment objectives, level of experience, and risk appetite. 

This software is developed for educational and research purposes. Always thoroughly test strategies on a **demo account** before deploying real capital.

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.
