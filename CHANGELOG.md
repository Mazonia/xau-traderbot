# 📜 Changelog & Release Notes

All notable changes to the **XAUUSD AI Trading Bot** will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [v3.1.0] - 2026-10-27 - Institutional Capital Protection & Resilience Engine

### 🚨 Critical Resilience Upgrades & Anti-Drawdown Protections
This release directly tackles real-world trading drawdowns on gold (XAUUSD) by shifting from a high-frequency entry bias to an **institutional capital preservation architecture**. The bot now treats capital defense as the #1 priority, preventing repetitive counter-trend traps, dead-market chop entries, and catastrophic drawdown spirals.

### 🛡️ New Features & Enhancements

#### 1. Multi-Timeframe (MTF) Trend Confirmation Gates
- **M5 Scalping**: Now requires strict H1 higher-timeframe trend alignment (H1 EMA 20 vs EMA 50) and blocks all low-volume entries during the dead Asian market window (21:00–07:00 UTC with `volume_intensity < 1.0`).
- **H1 Day Trading**: Now requires strict H4 macro trend alignment before entering any direction. Counter-trend pullbacks are cleanly vetoed.
- **H4 Swing Trading**: Now requires D1 macro trend alignment (D1 EMA 20 vs EMA 50) to prevent buying into multi-week institutional selloffs.

#### 2. Account Drawdown Dynamic Scaling & Hard Freeze
- **Tier 1 (5% Drawdown)**: If account equity drops 5% below its peak balance, risk per trade is immediately cut in half (0.5x), and maximum lot size is capped at 50% (`effective_max_lot`).
- **Tier 2 (10% Drawdown)**: If account equity drops 10% below peak balance, a hard trading freeze is engaged. All new entries are suspended until manual review or equity recovery.

#### 3. Loss-Streak Circuit Breakers & Cooldowns
- **Exponential Cooldown**: 3 consecutive losses on any individual strategy automatically triggers a timed cooldown (`15m -> 30m -> 60m -> 120m`).
- **Asymmetric Confidence Decay**: Strategy multiplier decays aggressively on loss (0.78x) and rebuilds cautiously on wins (1.03x).
- **Time-Bounded DB Loading**: Trade learner now only evaluates outcomes from the past 24 hours on boot, preventing old historic losses from permanently locking the bot.
- **Auto-Probation Timeout**: Strategies suspended due to low win-rate receive an automatic 2-hour probation window to re-qualify once market conditions rotate.

#### 4. Broker Rollover & Spread Shield
- Automatically pauses all new entries during the high-spread daily rollover window (21:00–22:00 UTC) when broker spreads on XAUUSD widen 5–10x.

#### 5. Machine Learning (XGBoost v2) Regularization & Leakage Elimination
- **Regularization Hyperparameters**: Upgraded to 300 estimators with `gamma=0.3`, `reg_alpha=0.5`, `reg_lambda=2.0`, and `min_child_weight=5` to prevent overfitting noisy financial series.
- **Purged Cross-Validation**: Implemented 5-fold `TimeSeriesSplit` with a 20-bar purge gap to completely eliminate look-ahead information leakage between train and validation sets.
- **Uncertainty Margin Gate**: Directional signals require a minimum 10% probability margin between top predictions, otherwise defaulting safely to `HOLD`.
- **Pure Indicator Features**: Explicitly stripped non-feature columns (`time`, timestamps, raw volumes) to ensure numerical stability and zero runtime type-casting crashes.

#### 6. Scaled Confluence & Volume Confirmation
- **ADX-Scaled Regime Scoring**: Regime contribution scales continuously with trend strength (ADX 40+ awards full 100% conviction, ADX < 25 discounts score).
- **Volume Confirmation Factor**: Signals backed by >1.5x average volume receive a +3.0 point boost, while signals occurring on <0.5x dry volume receive a -2.0 point penalty.
- **Offline Backtest Normalization**: Automatically scales target confluence thresholds when live news sentiment is inactive.

#### 7. Backtester Engine v2
- Added look-ahead-free multi-timeframe candle slicing (`higher_tf_df`) across backtests.
- Direct integration with trained ML classifiers and realistic spread/slippage modeling.

---

## [v3.0.0] - 2026-10-15 - Temporal Self-Attention & LLM Self-Learning

### Added
- Temporal Self-Attention Market Scorer (Scaled dot-product attention across M1, M5, M15, H1).
- Google Gemini LLM trade post-mortem analysis and ChromaDB vector memory.
- Fast, asynchronous FastAPI web dashboard with TradingView charts.
- Telegram remote control interface with interactive inline buttons.
- SHA-256 headline deduplication and economic news impact filtering.
