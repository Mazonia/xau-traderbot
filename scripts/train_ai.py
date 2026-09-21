"""
Institutional AI Model Training Pipeline for XAUUSD
Trains the XGBoost Signal Classifier using 10,000+ historical MT5 market data candles,
multi-timeframe engineered Smart Money Concepts (FVG, sweeps, EMA stack, ATR expansion),
and TimeSeriesSplit chronological cross-validation.
"""

import os
import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')
import time
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from loguru import logger
import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.mt5_connector import MT5Connector
from analysis.technical import TechnicalAnalyzer
from config.settings import get_settings, MODELS_DIR


def fetch_training_data(timeframe: str = "M15", count: int = 10000) -> pd.DataFrame:
    """Fetch high-quality historical candle data directly from MT5."""
    logger.info(f"Connecting to MT5 to fetch {count} candles on {timeframe}...")
    connector = MT5Connector()
    if not connector.connect():
        raise RuntimeError("Failed to connect to MT5. Ensure MT5 is running and logged in.")

    df = connector.get_rates(timeframe=timeframe, count=count)
    connector.disconnect()

    if df is None or df.empty:
        raise RuntimeError(f"Failed to fetch {timeframe} rates from MT5.")

    logger.success(f"Fetched {len(df)} historical candles from MT5 ({df.index[0]} -> {df.index[-1]})")
    return df


def engineer_and_label(df: pd.DataFrame, horizon: int = 5, threshold_pct: float = 0.0018) -> tuple[np.ndarray, np.ndarray, list[str], pd.DataFrame]:
    """
    Generate 50+ institutional quantitative features and future return target labels.
    
    Target:
      0: BUY  (Forward return > +threshold_pct)
      1: HOLD (Forward return within [-threshold_pct, +threshold_pct])
      2: SELL (Forward return < -threshold_pct)
    """
    logger.info("Computing multi-indicator technical feature matrix with Smart Money Concepts...")
    ta = TechnicalAnalyzer()
    feature_df = ta.create_ml_features(df)

    # Future return labeling
    future_returns = feature_df["close"].pct_change(horizon).shift(-horizon)
    feature_df["target"] = 1  # Default HOLD
    feature_df.loc[future_returns > threshold_pct, "target"] = 0  # BUY
    feature_df.loc[future_returns < -threshold_pct, "target"] = 2  # SELL

    # Drop NaNs created by rolling indicators & future shift
    clean_df = feature_df.dropna()

    numeric_df = clean_df.select_dtypes(include=[np.number])
    exclude_cols = ["target", "open", "high", "low", "close", "volume", "spread", "real_volume"]
    feature_cols = [c for c in numeric_df.columns if c not in exclude_cols]

    X = clean_df[feature_cols].astype(float).values
    y = clean_df["target"].astype(int).values

    counts = pd.Series(y).value_counts().to_dict()
    logger.info(f"Feature matrix engineered: {X.shape[0]} samples, {len(feature_cols)} features")
    logger.info(f"Label distribution: BUY (0)={counts.get(0, 0)}, HOLD (1)={counts.get(1, 0)}, SELL (2)={counts.get(2, 0)}")

    return X, y, feature_cols, clean_df


def train_model(X: np.ndarray, y: np.ndarray, feature_cols: list[str]) -> tuple[xgb.XGBClassifier, dict]:
    """
    Train XGBoost model with TimeSeriesSplit to prevent lookahead bias.
    """
    logger.info("Splitting data chronologically via TimeSeriesSplit (5 folds)...")
    tscv = TimeSeriesSplit(n_splits=5)
    last_train_idx, last_val_idx = list(tscv.split(X))[-1]

    X_train, X_val = X[last_train_idx], X[last_val_idx]
    y_train, y_val = y[last_train_idx], y[last_val_idx]

    logger.info(f"Training set: {len(X_train)} samples | Validation set: {len(X_val)} samples")

    # Balanced class weights
    classes = np.unique(y_train)
    weights = len(y_train) / (len(classes) * np.bincount(y_train))
    sample_weight = np.array([weights[yi] for yi in y_train])

    classifier = xgb.XGBClassifier(
        n_estimators=250,
        max_depth=5,
        learning_rate=0.035,
        subsample=0.85,
        colsample_bytree=0.85,
        gamma=0.3,
        reg_alpha=0.2,
        reg_lambda=1.5,
        eval_metric="mlogloss",
        random_state=42,
        verbosity=0,
        n_jobs=1,
    )

    logger.info("Fitting XGBoost Classifier with institutional regularization...")
    classifier.fit(
        X_train,
        y_train,
        sample_weight=sample_weight,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )

    y_pred = classifier.predict(X_val)
    accuracy = accuracy_score(y_val, y_pred)
    prec, rec, f1, _ = precision_recall_fscore_support(y_val, y_pred, average="weighted", zero_division=0)

    # Feature importances
    importances = classifier.feature_importances_
    top_indices = np.argsort(importances)[::-1][:10]
    top_features = [(feature_cols[i], float(importances[i])) for i in top_indices]

    metrics = {
        "accuracy": float(accuracy),
        "precision": float(prec),
        "recall": float(rec),
        "f1_score": float(f1),
        "train_samples": len(X_train),
        "val_samples": len(X_val),
        "top_features": top_features,
    }

    logger.success(f"XGBoost Training Complete! Accuracy: {accuracy:.2%} | F1-Score: {f1:.2%}")
    return classifier, metrics


def save_artifacts(model: xgb.XGBClassifier, feature_cols: list[str]) -> Path:
    """Save model and feature columns."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / "xgboost_classifier.joblib"
    feat_path = MODELS_DIR / "xgb_feature_columns.joblib"

    joblib.dump(model, str(model_path))
    joblib.dump(feature_cols, str(feat_path))
    logger.success(f"Production artifacts saved to:\n  • {model_path}\n  • {feat_path}")
    return model_path


def run_training_pipeline(timeframe: str = "M15", count: int = 10000) -> dict:
    """Execute complete end-to-end model training on expanded datasets."""
    start_time = time.time()
    print("=" * 60)
    print("  🚀 XAUUSD AI TRADING BOT — 10,000-CANDLE TRAINING PIPELINE")
    print("=" * 60)

    # 1. Fetch data
    df = fetch_training_data(timeframe=timeframe, count=count)

    # 2. Featurize & label
    X, y, feature_cols, clean_df = engineer_and_label(df)

    # 3. Train & evaluate
    model, metrics = train_model(X, y, feature_cols)

    # 4. Save
    save_artifacts(model, feature_cols)

    # 5. Live inference test
    test_sample = X[-1:].astype(float)
    t0 = time.perf_counter()
    probs = model.predict_proba(test_sample)[0]
    pred_class = int(model.predict(test_sample)[0])
    inference_ms = (time.perf_counter() - t0) * 1000

    class_names = {0: "BUY", 1: "HOLD", 2: "SELL"}
    print("\n" + "─" * 60)
    print("  📊 PRODUCTION MODEL REPORT (10,000 CANDLES + SMC)")
    print("─" * 60)
    print(f"  • Timeframe:           {timeframe}")
    print(f"  • Total Candles:       {len(df)}")
    print(f"  • Features Engineered: {len(feature_cols)}")
    print(f"  • Validation Accuracy: {metrics['accuracy']:.2%}")
    print(f"  • Weighted F1-Score:   {metrics['f1_score']:.2%}")
    print(f"  • Inference Latency:   {inference_ms:.2f} ms")
    print(f"  • Live Test Direction: {class_names[pred_class]}")
    print(f"    - BUY Probability:   {probs[0]:.2%}")
    print(f"    - HOLD Probability:  {probs[1]:.2%}")
    print(f"    - SELL Probability:  {probs[2]:.2%}")
    print("\n  🔝 Top 5 Feature Drivers:")
    for rank, (feat, imp) in enumerate(metrics["top_features"][:5], 1):
        print(f"    {rank}. {feat:25s} ({imp*100:.1f}%)")
    print("─" * 60)
    print(f"  ✨ Training pipeline finished in {time.time() - start_time:.2f}s\n")

    return metrics


if __name__ == "__main__":
    count = 10000
    tf = "M15"
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        count = int(sys.argv[1])
    if len(sys.argv) > 2:
        tf = sys.argv[2]
    run_training_pipeline(timeframe=tf, count=count)
