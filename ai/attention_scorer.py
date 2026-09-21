"""
Attention Market Scorer — Temporal Self-Attention Mechanism for XAUUSD Market Structure

Inspired by "Neural Networks for Algorithmic Trading with MQL5" (MetaQuotes Ltd, Chapter 5).
Applies scaled dot-product self-attention across recent candlestick sequences to identify
structural liquidity anchor bars, measure attention concentration (entropy reduction),
and confirm signal alignment with historical swing pivots.
"""

from typing import Dict, Any, Optional
import numpy as np
import pandas as pd
from loguru import logger


def _softmax(x: np.ndarray) -> np.ndarray:
    """Numerically stable softmax."""
    e_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
    return e_x / np.sum(e_x, axis=-1, keepdims=True)


class AttentionMarketScorer:
    """
    Computes Scaled Dot-Product Self-Attention over price-action sequences.
    
    Identifies whether the current price bar is structurally anchored to
    recent key inflection points (liquidity sweeps, swing highs/lows) or floating in noise.
    """

    def __init__(self, window: int = 25):
        self.window = window

    def compute_attention(self, df: pd.DataFrame) -> Dict[str, Any]:
        """
        Compute self-attention weights and concentration over recent bars.
        
        Args:
            df: DataFrame containing OHLCV + technical features.
            
        Returns:
            Dict with attention weights, concentration %, peak anchor candle, and entropy.
        """
        if df is None or len(df) < self.window:
            return {
                "concentration": 0.0,
                "anchor_index": 0,
                "anchor_weight": 0.0,
                "anchor_type": "INSUFFICIENT_DATA",
                "entropy": 1.0,
                "weights": [],
            }

        sub = df.iloc[-self.window:].copy()

        # Build feature matrix X (T x d)
        # 1. Normalized candle conviction (-1 to +1)
        conviction = sub["candle_conviction"].values if "candle_conviction" in sub.columns else (
            (sub["close"] - sub["open"]) / (sub["high"] - sub["low"]).replace(0, 1e-6)
        ).values
        # 2. Upper wick ratio (0 to 1)
        upper_wick = sub["upper_wick_ratio"].values if "upper_wick_ratio" in sub.columns else (
            (sub["high"] - np.maximum(sub["open"], sub["close"])) / (sub["high"] - sub["low"]).replace(0, 1e-6)
        ).values
        # 3. Lower wick ratio (0 to 1)
        lower_wick = sub["lower_wick_ratio"].values if "lower_wick_ratio" in sub.columns else (
            (np.minimum(sub["open"], sub["close"]) - sub["low"]) / (sub["high"] - sub["low"]).replace(0, 1e-6)
        ).values
        # 4. Normalized relative return
        ret = sub["close"].pct_change().fillna(0).values * 100.0
        # 5. Normalized RSI (-1 to +1)
        rsi = ((sub["rsi"].values - 50.0) / 50.0) if "rsi" in sub.columns else np.zeros(len(sub))

        # Stack features
        X = np.column_stack([conviction, upper_wick, lower_wick, ret, rsi])
        T, d = X.shape

        # Scaled dot-product attention
        # Query = current candle (latest bar), Key = all bars in the window
        Q = X[-1:]          # (1, d)
        K = X               # (T, d)
        raw_scores = np.dot(Q, K.T) / np.sqrt(d)  # (1, T)
        weights = _softmax(raw_scores)[0]          # (T,)

        # Compute Shannon entropy
        eps = 1e-9
        entropy = -float(np.sum(weights * np.log(weights + eps)))
        max_entropy = float(np.log(T))
        # Concentration index: 0% = perfectly uniform (flat noise), 100% = delta spike (extreme focus)
        concentration = float(np.clip((1.0 - (entropy / max_entropy)) * 100.0, 0.0, 100.0))

        # Peak attention anchor (excluding current bar itself at index -1)
        past_weights = weights[:-1]
        if len(past_weights) > 0:
            peak_local_idx = int(np.argmax(past_weights))
            peak_weight = float(past_weights[peak_local_idx])
        else:
            peak_local_idx = T - 1
            peak_weight = float(weights[-1])

        # Characterize anchor candle type
        anchor_row = sub.iloc[peak_local_idx]
        anchor_high = float(anchor_row["high"])
        anchor_low = float(anchor_row["low"])
        window_high = float(sub["high"].max())
        window_low = float(sub["low"].min())

        # Determine structural archetype
        if abs(anchor_high - window_high) < 1.0 or upper_wick[peak_local_idx] > 0.45:
            anchor_type = "SWING_HIGH_RESISTANCE"
        elif abs(anchor_low - window_low) < 1.0 or lower_wick[peak_local_idx] > 0.45:
            anchor_type = "SWING_LOW_SUPPORT"
        elif abs(conviction[peak_local_idx]) > 0.7:
            anchor_type = "MOMENTUM_EXPANSION"
        else:
            anchor_type = "CONSOLIDATION_PIVOT"

        return {
            "concentration": concentration,
            "anchor_index": peak_local_idx - (T - 1),  # relative bars ago (e.g. -12)
            "anchor_weight": peak_weight,
            "anchor_type": anchor_type,
            "entropy": entropy,
            "weights": weights.tolist(),
        }

    def analyze_alignment(self, df: pd.DataFrame, signal_direction: str) -> Dict[str, Any]:
        """
        Evaluate whether the self-attention structural anchor supports or opposes
        a proposed trade direction.
        
        Args:
            df: Historical rates DataFrame
            signal_direction: "BUY" or "SELL"
            
        Returns:
            Dict with 'concentration', 'alignment' (-1 to +1), 'bonus_pts', and 'summary'.
        """
        att = self.compute_attention(df)
        conc = att["concentration"]
        anchor_type = att["anchor_type"]
        bars_ago = abs(att["anchor_index"])

        alignment = 0.0
        if signal_direction == "BUY":
            if anchor_type == "SWING_LOW_SUPPORT":
                alignment = 1.0    # Buying near a high-attention support anchor
            elif anchor_type == "MOMENTUM_EXPANSION":
                alignment = 0.5    # Following institutional expansion
            elif anchor_type == "SWING_HIGH_RESISTANCE":
                alignment = -1.0   # Buying directly into high-attention resistance overhead!
        elif signal_direction == "SELL":
            if anchor_type == "SWING_HIGH_RESISTANCE":
                alignment = 1.0    # Selling near a high-attention resistance anchor
            elif anchor_type == "MOMENTUM_EXPANSION":
                alignment = 0.5    # Following downward expansion
            elif anchor_type == "SWING_LOW_SUPPORT":
                alignment = -1.0   # Selling directly into high-attention support below!

        # Score modifier: only high-concentration attention (>18%) produces significant impact
        bonus_pts = 0.0
        if conc >= 18.0:
            bonus_pts = (conc / 100.0) * alignment * 6.0  # Range: -6.0 to +6.0 pts

        summary = (
            f"Attention {conc:.0f}% focused on {anchor_type} ({bars_ago} bars ago) | "
            f"Directional Alignment: {alignment:+.1f} (Modifier: {bonus_pts:+.1f} pts)"
        )

        return {
            "concentration": conc,
            "anchor_type": anchor_type,
            "bars_ago": bars_ago,
            "anchor_weight": att["anchor_weight"],
            "alignment": alignment,
            "bonus_pts": bonus_pts,
            "summary": summary,
        }
