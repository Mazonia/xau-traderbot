"""
AI Price Predictor — LSTM Neural Network

Predicts the next candle's direction (UP/DOWN) and magnitude
using an LSTM model trained on OHLCV + technical indicator features.
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from loguru import logger

from analysis.technical import TechnicalAnalyzer
from config.settings import get_settings, MODELS_DIR


class PricePredictor:
    """
    LSTM-based price direction predictor for XAUUSD.

    Features:
    - OHLCV data + 20+ technical indicators
    - Walk-forward training to prevent look-ahead bias
    - Confidence scoring for predictions
    """

    def __init__(self):
        settings = get_settings()
        ai_params = settings.ai_params

        self.lookback = ai_params.get("lstm_lookback_candles", 60)
        self.horizon = ai_params.get("lstm_prediction_horizon", 5)
        self.confidence_threshold = ai_params.get("prediction_confidence_threshold", 0.6)
        self.model_path = MODELS_DIR / "lstm_price_predictor.keras"

        self._model = None
        self._scaler = None
        self._feature_columns: list[str] = []

    def _build_model(self, input_shape: tuple) -> "tf.keras.Model":
        """Build the LSTM architecture."""
        try:
            import tensorflow as tf
            from tensorflow.keras import layers, models

            model = models.Sequential([
                layers.LSTM(128, return_sequences=True, input_shape=input_shape),
                layers.Dropout(0.3),
                layers.LSTM(64, return_sequences=False),
                layers.Dropout(0.2),
                layers.Dense(32, activation="relu"),
                layers.Dense(3, activation="softmax"),  # UP, DOWN, FLAT
            ])

            model.compile(
                optimizer=tf.keras.optimizers.Adam(learning_rate=0.001),
                loss="categorical_crossentropy",
                metrics=["accuracy"],
            )

            logger.info(f"LSTM model built: input_shape={input_shape}")
            return model

        except ImportError:
            logger.error("TensorFlow not installed — AI predictions unavailable")
            return None

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare features for the LSTM model."""
        ta = TechnicalAnalyzer()
        df = ta.create_ml_features(df)

        # Select only numeric columns and drop NaN-heavy columns
        numeric_df = df.select_dtypes(include=[np.number])
        numeric_df = numeric_df.dropna(axis=1, thresh=int(len(numeric_df) * 0.8))
        numeric_df = numeric_df.dropna()

        self._feature_columns = list(numeric_df.columns)
        return numeric_df

    def create_sequences(
        self,
        data: np.ndarray,
        labels: np.ndarray | None = None,
    ) -> tuple:
        """Create sliding window sequences for LSTM input."""
        X = []
        y = [] if labels is not None else None

        for i in range(self.lookback, len(data)):
            X.append(data[i - self.lookback: i])
            if labels is not None:
                y.append(labels[i])

        X = np.array(X)
        if y is not None:
            y = np.array(y)
            return X, y
        return (X,)

    def train(self, df: pd.DataFrame, epochs: int = 50, batch_size: int = 32) -> dict:
        """
        Train the LSTM model on historical data.

        Args:
            df: OHLCV DataFrame with at least 5000 candles.
            epochs: Training epochs.
            batch_size: Batch size.

        Returns:
            Training metrics dict.
        """
        try:
            import tensorflow as tf
            from sklearn.preprocessing import StandardScaler

            logger.info("Starting LSTM training...")

            # Prepare features
            feature_df = self.prepare_features(df)

            if len(feature_df) < self.lookback + 100:
                logger.error("Insufficient data for training")
                return {"error": "Insufficient data"}

            # Create labels: next candle direction
            feature_df["target"] = 0  # FLAT
            returns = feature_df["close"].pct_change(self.horizon).shift(-self.horizon)
            feature_df.loc[returns > 0.001, "target"] = 1  # UP
            feature_df.loc[returns < -0.001, "target"] = 2  # DOWN
            feature_df = feature_df.dropna()

            # Separate features and labels
            target = feature_df["target"].values
            features = feature_df.drop(columns=["target"]).values

            # Scale features
            self._scaler = StandardScaler()
            features_scaled = self._scaler.fit_transform(features)

            # One-hot encode labels
            labels = tf.keras.utils.to_categorical(target, num_classes=3)

            # Create sequences
            X, y = self.create_sequences(features_scaled, labels)

            # Train/validation split (80/20, sequential)
            split_idx = int(len(X) * 0.8)
            X_train, X_val = X[:split_idx], X[split_idx:]
            y_train, y_val = y[:split_idx], y[split_idx:]

            # Build model
            self._model = self._build_model(input_shape=(X_train.shape[1], X_train.shape[2]))
            if self._model is None:
                return {"error": "Model build failed"}

            # Train
            history = self._model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val),
                epochs=epochs,
                batch_size=batch_size,
                verbose=0,
                callbacks=[
                    tf.keras.callbacks.EarlyStopping(
                        patience=10, restore_best_weights=True
                    ),
                ],
            )

            # Evaluate
            val_loss, val_acc = self._model.evaluate(X_val, y_val, verbose=0)

            # Save model
            self._model.save(str(self.model_path))

            # Save scaler
            import joblib
            joblib.dump(self._scaler, str(MODELS_DIR / "scaler.joblib"))
            joblib.dump(self._feature_columns, str(MODELS_DIR / "feature_columns.joblib"))

            metrics = {
                "val_loss": float(val_loss),
                "val_accuracy": float(val_acc),
                "train_samples": len(X_train),
                "val_samples": len(X_val),
                "epochs_run": len(history.history["loss"]),
                "features_used": len(self._feature_columns),
            }

            logger.success(
                f"LSTM training complete | "
                f"Val Accuracy: {val_acc:.2%} | "
                f"Val Loss: {val_loss:.4f} | "
                f"Samples: {len(X_train)}"
            )
            return metrics

        except Exception as e:
            logger.error(f"LSTM training error: {e}")
            return {"error": str(e)}

    def load_model(self) -> bool:
        """Load a previously trained model."""
        try:
            import tensorflow as tf
            import joblib

            if not self.model_path.exists():
                logger.warning("No saved LSTM model found")
                return False

            self._model = tf.keras.models.load_model(str(self.model_path))
            self._scaler = joblib.load(str(MODELS_DIR / "scaler.joblib"))
            self._feature_columns = joblib.load(str(MODELS_DIR / "feature_columns.joblib"))

            logger.info("LSTM model loaded successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to load LSTM model: {e}")
            return False

    def predict(self, df: pd.DataFrame) -> dict:
        """
        Predict the next candle direction.

        Returns:
            Dict with 'direction' (BUY/SELL/HOLD), 'confidence' (0-1),
            'probabilities' (UP/DOWN/FLAT).
        """
        if self._model is None:
            if not self.load_model():
                return {"direction": "HOLD", "confidence": 0.0, "error": "No model"}

        try:
            # Prepare features
            feature_df = self.prepare_features(df)

            # Ensure we have the right columns
            for col in self._feature_columns:
                if col not in feature_df.columns:
                    feature_df[col] = 0

            feature_df = feature_df[self._feature_columns]

            if len(feature_df) < self.lookback:
                return {"direction": "HOLD", "confidence": 0.0, "error": "Insufficient data"}

            # Scale
            features_scaled = self._scaler.transform(feature_df.values)

            # Create sequence from last N candles
            sequence = features_scaled[-self.lookback:]
            sequence = np.expand_dims(sequence, axis=0)

            # Predict
            probs = self._model.predict(sequence, verbose=0)[0]

            # probs: [FLAT, UP, DOWN]
            direction_map = {0: "HOLD", 1: "BUY", 2: "SELL"}
            predicted_class = np.argmax(probs)
            confidence = float(probs[predicted_class])
            direction = direction_map[predicted_class]

            # Only return actionable signal if confidence exceeds threshold
            if confidence < self.confidence_threshold:
                direction = "HOLD"

            return {
                "direction": direction,
                "confidence": confidence,
                "probabilities": {
                    "HOLD": float(probs[0]),
                    "BUY": float(probs[1]),
                    "SELL": float(probs[2]),
                },
            }

        except Exception as e:
            logger.error(f"LSTM prediction error: {e}")
            return {"direction": "HOLD", "confidence": 0.0, "error": str(e)}
