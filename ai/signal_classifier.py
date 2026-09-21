"""
Signal Classifier — XGBoost Buy/Sell/Hold

Feature-engineered classification model using XGBoost
for faster, more interpretable signal generation.
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
    """

    def __init__(self):
        settings = get_settings()
        self.model_path = MODELS_DIR / "xgboost_classifier.joblib"
        self._model = None
        self._feature_columns: list[str] = []

    def train(self, df: pd.DataFrame) -> dict:
        """Train the XGBoost classifier."""
        try:
            import xgboost as xgb
            from sklearn.model_selection import TimeSeriesSplit
            from sklearn.metrics import classification_report
            import joblib

            logger.info("Starting XGBoost training...")

            # Prepare features
            ta = TechnicalAnalyzer()
            feature_df = ta.create_ml_features(df)

            # Create labels
            returns = feature_df["close"].pct_change(5).shift(-5)
            feature_df["target"] = 1  # HOLD
            feature_df.loc[returns > 0.002, "target"] = 0  # BUY
            feature_df.loc[returns < -0.002, "target"] = 2  # SELL

            feature_df = feature_df.dropna()

            # Remove non-feature columns and ensure only numeric features
            import numpy as np
            numeric_df = feature_df.select_dtypes(include=[np.number])
            exclude_cols = ["target", "open", "high", "low", "close", "volume"]
            feature_cols = [c for c in numeric_df.columns if c not in exclude_cols]
            self._feature_columns = feature_cols

            X = feature_df[feature_cols].astype(float).values
            y = feature_df["target"].astype(int).values

            # Time series split
            tscv = TimeSeriesSplit(n_splits=5)
            last_train_idx, last_val_idx = list(tscv.split(X))[-1]

            X_train, X_val = X[last_train_idx], X[last_val_idx]
            y_train, y_val = y[last_train_idx], y[last_val_idx]

            # Train XGBoost
            self._model = xgb.XGBClassifier(
                n_estimators=100,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.8,
                colsample_bytree=0.8,
                eval_metric="mlogloss",
                verbosity=0,
                n_jobs=1,
            )

            self._model.fit(
                X_train, y_train,
                eval_set=[(X_val, y_val)],
                verbose=False,
            )

            # Evaluate
            y_pred = self._model.predict(X_val)
            accuracy = (y_pred == y_val).mean()

            # Save
            joblib.dump(self._model, str(self.model_path))
            joblib.dump(self._feature_columns, str(MODELS_DIR / "xgb_feature_columns.joblib"))

            logger.success(f"XGBoost training complete | Accuracy: {accuracy:.2%}")
            return {"accuracy": float(accuracy), "features": len(feature_cols)}

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

            # Ensure columns match
            for col in self._feature_columns:
                if col not in feature_df.columns:
                    feature_df[col] = 0

            X = feature_df[self._feature_columns].iloc[[-1]].values

            probs = self._model.predict_proba(X)[0]
            predicted = np.argmax(probs)
            confidence = float(probs[predicted])

            direction_map = {0: "BUY", 1: "HOLD", 2: "SELL"}
            direction = direction_map[predicted]

            if confidence < 0.5:
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
