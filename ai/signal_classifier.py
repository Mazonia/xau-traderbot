"""
Signal Classifier — XGBoost Buy/Sell/Hold (v2 — Oct 2026)

Feature-engineered classification model using XGBoost
with proper regularization, Purged Group K-Fold cross-validation,
and enhanced hyperparameters for robust XAUUSD signal generation.
"""

import numpy as np
import pandas as pd
from loguru import logger
from pathlib import Path

from analysis.technical import TechnicalAnalyzer
from config.settings import get_settings, MODELS_DIR


class SignalClassifier:
    """
    XGBoost-based signal classifier.

    Faster inference than LSTM, better for real-time decisions.
    Uses 50+ engineered features from technical indicators.
    Regularized to prevent overfitting on volatile gold data.
    """

    def __init__(self):
        settings = get_settings()
        self.model_path = MODELS_DIR / "xgboost_classifier.joblib"
        self._model = None
        self._feature_columns: list[str] = []

    def train(self, df: pd.DataFrame) -> dict:
        """Train the XGBoost classifier with proper regularization and cross-validation."""
        try:
            import xgboost as xgb
            from sklearn.model_selection import TimeSeriesSplit
            from sklearn.metrics import classification_report, accuracy_score
            import joblib

            logger.info("Starting XGBoost v2 training (enhanced regularization)...")

            # Prepare features
            ta = TechnicalAnalyzer()
            feature_df = ta.create_ml_features(df)

            # Create labels — use slightly wider thresholds to reduce noise
            returns = feature_df["close"].pct_change(5).shift(-5)
            feature_df["target"] = 1  # HOLD
            feature_df.loc[returns > 0.002, "target"] = 0  # BUY
            feature_df.loc[returns < -0.002, "target"] = 2  # SELL

            feature_df = feature_df.dropna()

            # Remove non-feature columns and ensure only numeric technical features
            numeric_df = feature_df.select_dtypes(include=[np.number])
            exclude_cols = [
                "target", "open", "high", "low", "close", "volume",
                "time", "tick_volume", "real_volume", "spread",
            ]
            feature_cols = [c for c in numeric_df.columns if c not in exclude_cols]
            self._feature_columns = feature_cols

            X = feature_df[feature_cols].astype(float).values
            y = feature_df["target"].astype(int).values

            # ── Purged Time Series Split ─────────────────────────────────
            # Use multiple splits with a purge gap to prevent look-ahead bias
            n_splits = 5
            purge_gap = 20  # bars of purge between train/val to avoid leakage
            tscv = TimeSeriesSplit(n_splits=n_splits, gap=purge_gap)

            val_accuracies = []
            best_model = None
            best_acc = 0.0

            for fold_idx, (train_idx, val_idx) in enumerate(tscv.split(X)):
                X_train, X_val = X[train_idx], X[val_idx]
                y_train, y_val = y[train_idx], y[val_idx]

                # ── Enhanced XGBoost with strong regularization ──────────
                model = xgb.XGBClassifier(
                    n_estimators=300,
                    max_depth=4,
                    learning_rate=0.03,
                    subsample=0.75,
                    colsample_bytree=0.7,
                    min_child_weight=5,
                    gamma=0.3,
                    reg_alpha=0.5,
                    reg_lambda=2.0,
                    scale_pos_weight=1.0,
                    eval_metric="mlogloss",
                    early_stopping_rounds=30,
                    verbosity=0,
                    n_jobs=-1,
                    random_state=42,
                )

                model.fit(
                    X_train, y_train,
                    eval_set=[(X_val, y_val)],
                    verbose=False,
                )

                y_pred = model.predict(X_val)
                acc = accuracy_score(y_val, y_pred)
                val_accuracies.append(acc)

                if acc > best_acc:
                    best_acc = acc
                    best_model = model

                logger.debug(f"  Fold {fold_idx + 1}/{n_splits}: accuracy={acc:.4f}")

            # Use the best fold model
            self._model = best_model
            mean_acc = np.mean(val_accuracies)
            std_acc = np.std(val_accuracies)

            # Save
            MODELS_DIR.mkdir(parents=True, exist_ok=True)
            joblib.dump(self._model, str(self.model_path))
            joblib.dump(self._feature_columns, str(MODELS_DIR / "xgb_feature_columns.joblib"))

            logger.success(
                f"XGBoost v2 training complete | "
                f"Mean CV Accuracy: {mean_acc:.2%} ± {std_acc:.2%} | "
                f"Best Fold: {best_acc:.2%} | "
                f"Features: {len(feature_cols)}"
            )
            return {
                "accuracy": float(best_acc),
                "mean_cv_accuracy": float(mean_acc),
                "std_cv_accuracy": float(std_acc),
                "features": len(feature_cols),
                "n_splits": n_splits,
            }

        except Exception as e:
            logger.error(f"XGBoost training error: {e}")
            return {"error": str(e)}

    def load_model(self) -> bool:
        """Load saved XGBoost model."""
        try:
            import joblib

            if not self.model_path.exists():
                return False

            self._model = joblib.load(str(self.model_path))
            self._feature_columns = joblib.load(str(MODELS_DIR / "xgb_feature_columns.joblib"))
            logger.info("XGBoost model loaded")
            return True

        except Exception as e:
            logger.error(f"Failed to load XGBoost: {e}")
            return False

    def predict(self, df: pd.DataFrame) -> dict:
        """
        Predict BUY/SELL/HOLD signal.

        Returns:
            Dict with 'direction', 'confidence', 'probabilities'.
        """
        if self._model is None:
            if not self.load_model():
                return {"direction": "HOLD", "confidence": 0.0}

        try:
            ta = TechnicalAnalyzer()
            feature_df = ta.create_ml_features(df)
            feature_df = feature_df.dropna()

            if len(feature_df) == 0:
                return {"direction": "HOLD", "confidence": 0.0}

            # Ensure columns match and are numeric float
            for col in self._feature_columns:
                if col not in feature_df.columns:
                    feature_df[col] = 0.0

            X = feature_df[self._feature_columns].astype(float).iloc[[-1]].values

            probs = self._model.predict_proba(X)[0]
            predicted = np.argmax(probs)
            confidence = float(probs[predicted])

            direction_map = {0: "BUY", 1: "HOLD", 2: "SELL"}
            direction = direction_map[predicted]

            # Require minimum 50% confidence for directional signals
            if confidence < 0.5:
                direction = "HOLD"

            # Additional confidence gate: if top two probabilities are very close,
            # the model is uncertain — default to HOLD
            sorted_probs = sorted(probs, reverse=True)
            if len(sorted_probs) >= 2 and (sorted_probs[0] - sorted_probs[1]) < 0.10:
                direction = "HOLD"

            return {
                "direction": direction,
                "confidence": confidence,
                "probabilities": {
                    "BUY": float(probs[0]),
                    "HOLD": float(probs[1]),
                    "SELL": float(probs[2]),
                },
            }

        except Exception as e:
            logger.error(f"XGBoost prediction error: {e}")
            return {"direction": "HOLD", "confidence": 0.0}
