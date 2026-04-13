"""
ml/features/technical_features.py
===================================
Extracts ALL technical indicators from OHLCV price data.

Technical analysis indicators help identify:
  - Trends: Is price going up, down, or sideways?
  - Momentum: How strong is the current move?
  - Volatility: How much is price fluctuating?
  - Volume: Is there strong buying/selling conviction?

These features feed into:
  1. TechnicalAgent scoring (agents/analysis_agents/technical_agent.py)
  2. ML models (LSTM + XGBoost feature vectors)

Library: pandas-ta (pure Python, no TA-Lib compilation needed)

Output: DataFrame with 40+ technical indicator columns, all NaN-cleaned.

Usage:
    from ml.features.technical_features import TechnicalFeatureExtractor
    extractor = TechnicalFeatureExtractor()
    df_with_features = extractor.extract(ohlcv_df)
"""

from __future__ import annotations

from typing import Optional, Tuple
import pandas as pd
import numpy as np
import ta

from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# TECHNICAL FEATURE EXTRACTOR
# ═══════════════════════════════════════════════════════════════

class TechnicalFeatureExtractor:
    """
    Computes all technical indicators for a price DataFrame.
    
    Input: OHLCV DataFrame with columns [Open, High, Low, Close, Volume]
    Output: Same DataFrame with 40+ additional indicator columns
    
    All NaN values are forward-filled then zero-filled to ensure
    no missing data in the output (critical for ML models).
    """
    
    # ── Indicator Parameters ───────────────────────────────────────────────
    # These match the constants in config/constants.py thresholds
    
    SMA_PERIODS = [20, 50, 200]
    EMA_PERIODS = [12, 26]
    RSI_PERIOD = 14
    MACD_FAST = 12
    MACD_SLOW = 26
    MACD_SIGNAL = 9
    STOCH_K = 14
    STOCH_D = 3
    BB_PERIOD = 20
    BB_STD = 2
    ATR_PERIOD = 14
    VOLUME_SMA_PERIOD = 20
    
    # Lookback windows for derived features
    RETURN_WINDOWS = [1, 5, 20]  # 1-day, 5-day, 20-day returns
    SUPPORT_RESISTANCE_WINDOW = 60  # Last 60 days for S/R detection
    
    def __init__(self):
        """Initialises the extractor."""
        pass
    
    # ── Main Extraction Method ─────────────────────────────────────────────
    
    def extract(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Computes all technical indicators on an OHLCV DataFrame.
        
        Args:
            df: DataFrame with DatetimeIndex and columns [Open, High, Low, Close, Volume]
        
        Returns:
            DataFrame with all original columns plus 40+ technical indicator columns.
            All NaN values are cleaned (forward-fill then zero-fill).
        
        Raises:
            ValueError: If required columns are missing or df is empty.
        """
        if df is None or len(df) == 0:
            raise ValueError("Input DataFrame is empty")
        
        required_cols = ["Open", "High", "Low", "Close", "Volume"]
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Make a copy to avoid modifying the original
        df = df.copy()
        
        logger.debug(f"Extracting technical features from {len(df)} rows")
        
        # ── Trend Indicators ───────────────────────────────────────────────
        df = self._add_moving_averages(df)
        df = self._add_trend_signals(df)
        
        # ── Momentum Indicators ────────────────────────────────────────────
        df = self._add_rsi(df)
        df = self._add_macd(df)
        df = self._add_stochastic(df)
        
        # ── Volatility Indicators ──────────────────────────────────────────
        df = self._add_bollinger_bands(df)
        df = self._add_atr(df)
        
        # ── Volume Indicators ──────────────────────────────────────────────
        df = self._add_volume_indicators(df)
        
        # ── Derived Features ───────────────────────────────────────────────
        df = self._add_returns(df)
        df = self._add_support_resistance(df)
        df = self._add_price_momentum(df)
        
        # ── Clean NaN values ───────────────────────────────────────────────
        df = self._clean_nan(df)
        
        logger.debug(f"Technical feature extraction complete: {len(df.columns)} columns")
        return df
    
    # ── Trend Indicators ───────────────────────────────────────────────────
    
    def _add_moving_averages(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds Simple Moving Averages (SMA) and Exponential Moving Averages (EMA).
        
        SMA is the simple average of the last N closing prices.
        EMA gives more weight to recent prices (reacts faster to changes).
        """
        close = df["Close"]
        
        # Simple Moving Averages
        for period in self.SMA_PERIODS:
            df[f"SMA_{period}"] = ta.sma(close, length=period)
        
        # Exponential Moving Averages
        for period in self.EMA_PERIODS:
            df[f"EMA_{period}"] = ta.ema(close, length=period)
        
        return df
    
    def _add_trend_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds derived trend signals:
          - price_vs_sma200: % distance from 200-day SMA
          - golden_cross: SMA50 crossed above SMA200 recently (bullish)
          - death_cross: SMA50 crossed below SMA200 recently (bearish)
        """
        close = df["Close"]
        
        # Price position relative to SMA200
        if "SMA_200" in df.columns:
            df["price_vs_sma200"] = (
                (close - df["SMA_200"]) / df["SMA_200"] * 100
            )
        else:
            df["price_vs_sma200"] = 0.0
        
        # Golden Cross / Death Cross detection
        if "SMA_50" in df.columns and "SMA_200" in df.columns:
            # Shift to get previous day's values
            sma50_prev = df["SMA_50"].shift(1)
            sma200_prev = df["SMA_200"].shift(1)
            
            # Golden cross: SMA50 was below SMA200 yesterday, now above
            df["golden_cross"] = (
                (sma50_prev < sma200_prev) & (df["SMA_50"] > df["SMA_200"])
            ).astype(int)
            
            # Death cross: SMA50 was above SMA200 yesterday, now below
            df["death_cross"] = (
                (sma50_prev > sma200_prev) & (df["SMA_50"] < df["SMA_200"])
            ).astype(int)
        else:
            df["golden_cross"] = 0
            df["death_cross"] = 0
        
        return df
    
    # ── Momentum Indicators ────────────────────────────────────────────────
    
    def _add_rsi(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds Relative Strength Index (RSI).
        
        RSI measures momentum on a 0-100 scale:
          - RSI > 70: Overbought (potential reversal down)
          - RSI < 30: Oversold (potential reversal up)
          - RSI 45-55: Neutral zone
        """
        close = df["Close"]
        df["RSI_14"] = ta.rsi(close, length=self.RSI_PERIOD)
        
        # RSI signal categorization
        rsi = df["RSI_14"]
        df["RSI_signal"] = np.where(
            rsi < 30, 2,  # Oversold → Bullish signal
            np.where(rsi > 70, 0,  # Overbought → Bearish signal
                     1)  # Neutral
        )
        
        return df
    
    def _add_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds MACD (Moving Average Convergence Divergence).
        
        MACD components:
          - MACD line: EMA(12) - EMA(26)
          - Signal line: EMA(9) of MACD line
          - Histogram: MACD - Signal
        
        Trading signals:
          - MACD crosses above Signal: Bullish
          - MACD crosses below Signal: Bearish
        """
        close = df["Close"]
        macd_result = ta.macd(
            close,
            fast=self.MACD_FAST,
            slow=self.MACD_SLOW,
            signal=self.MACD_SIGNAL,
        )
        
        if macd_result is not None and not macd_result.empty:
            df["MACD"] = macd_result.iloc[:, 0]          # MACD line
            df["MACD_signal"] = macd_result.iloc[:, 2]   # Signal line
            df["MACD_hist"] = macd_result.iloc[:, 1]     # Histogram
            
            # Crossover detection
            macd_prev = df["MACD"].shift(1)
            signal_prev = df["MACD_signal"].shift(1)
            
            # Bullish crossover: MACD crosses above signal
            df["MACD_crossover"] = (
                (macd_prev < signal_prev) & (df["MACD"] > df["MACD_signal"])
            ).astype(int)
        else:
            df["MACD"] = 0.0
            df["MACD_signal"] = 0.0
            df["MACD_hist"] = 0.0
            df["MACD_crossover"] = 0
        
        return df
    
    def _add_stochastic(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds Stochastic Oscillator (%K and %D).
        
        Stochastic measures where the current close is relative to
        the high-low range over the last N periods.
        
        Values 0-100:
          - > 80: Overbought
          - < 20: Oversold
        """
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        
        stoch_result = ta.stoch(
            high, low, close,
            k=self.STOCH_K,
            d=self.STOCH_D,
        )
        
        if stoch_result is not None and not stoch_result.empty:
            df["stoch_k"] = stoch_result.iloc[:, 0]  # %K line
            df["stoch_d"] = stoch_result.iloc[:, 1]  # %D line (signal)
        else:
            df["stoch_k"] = 50.0
            df["stoch_d"] = 50.0
        
        return df
    
    # ── Volatility Indicators ──────────────────────────────────────────────
    
    def _add_bollinger_bands(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds Bollinger Bands.
        
        Bollinger Bands consist of:
          - Middle: SMA(20)
          - Upper: SMA(20) + 2 * StdDev
          - Lower: SMA(20) - 2 * StdDev
        
        Derived metrics:
          - BB_width: (Upper - Lower) / Middle → Measure of volatility
          - BB_position: Where price sits within the bands (0 = lower, 1 = upper)
        """
        close = df["Close"]
        bb_result = ta.bbands(
            close,
            length=self.BB_PERIOD,
            std=self.BB_STD,
        )
        
        if bb_result is not None and not bb_result.empty:
            df["BB_lower"] = bb_result.iloc[:, 0]
            df["BB_middle"] = bb_result.iloc[:, 1]
            df["BB_upper"] = bb_result.iloc[:, 2]
            
            # Band width (normalized volatility measure)
            df["BB_width"] = (
                (df["BB_upper"] - df["BB_lower"]) / df["BB_middle"]
            )
            
            # Price position within bands (0 = at lower, 1 = at upper)
            band_range = df["BB_upper"] - df["BB_lower"]
            df["BB_position"] = np.where(
                band_range > 0,
                (close - df["BB_lower"]) / band_range,
                0.5  # Default to middle if bands are flat
            )
            # Clip to 0-1 range (price can briefly go outside bands)
            df["BB_position"] = df["BB_position"].clip(0, 1)
        else:
            df["BB_lower"] = close
            df["BB_middle"] = close
            df["BB_upper"] = close
            df["BB_width"] = 0.0
            df["BB_position"] = 0.5
        
        return df
    
    def _add_atr(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds Average True Range (ATR).
        
        ATR measures volatility — the average range between high and low
        over the last N periods. Used for:
          - Stop loss calculation: entry - (2 * ATR)
          - Take profit calculation: entry + (3 * ATR)
        """
        high = df["High"]
        low = df["Low"]
        close = df["Close"]
        
        df["ATR_14"] = ta.atr(high, low, close, length=self.ATR_PERIOD)
        
        return df
    
    # ── Volume Indicators ──────────────────────────────────────────────────
    
    def _add_volume_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds volume-based indicators:
          - volume_sma_20: 20-day average volume
          - volume_ratio: today's volume / 20-day average
          - OBV: On-Balance Volume (cumulative volume with direction)
          - VWAP: Volume Weighted Average Price
        """
        volume = df["Volume"]
        close = df["Close"]
        
        # Volume moving average
        df["volume_sma_20"] = ta.sma(volume, length=self.VOLUME_SMA_PERIOD)
        
        # Volume ratio (today vs average)
        df["volume_ratio"] = np.where(
            df["volume_sma_20"] > 0,
            volume / df["volume_sma_20"],
            1.0
        )
        
        # On-Balance Volume
        obv = ta.obv(close, volume)
        df["OBV"] = obv if obv is not None else 0
        
        # VWAP (Volume Weighted Average Price)
        # VWAP is typically calculated intraday, but we compute a rolling VWAP
        try:
            vwap = ta.vwap(df["High"], df["Low"], df["Close"], df["Volume"])
            df["VWAP"] = vwap if vwap is not None else close
        except Exception:
            df["VWAP"] = close
        
        return df
    
    # ── Derived Features ───────────────────────────────────────────────────
    
    def _add_returns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds price return features for various lookback windows.
        
        Returns:
          - daily_return: % change from previous close
          - 5day_return: % change over last 5 days
          - 20day_return: % change over last 20 days
        """
        close = df["Close"]
        
        for window in self.RETURN_WINDOWS:
            col_name = f"return_{window}d" if window > 1 else "daily_return"
            df[col_name] = close.pct_change(periods=window) * 100
        
        return df
    
    def _add_support_resistance(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Identifies support and resistance levels.
        
        Support: Recent significant low (price tends to bounce here)
        Resistance: Recent significant high (price tends to reverse here)
        
        Algorithm: Use rolling min/max over last 60 days
        """
        close = df["Close"]
        window = min(self.SUPPORT_RESISTANCE_WINDOW, len(df) - 1)
        
        if window > 0:
            df["support_level"] = close.rolling(window=window, min_periods=1).min()
            df["resistance_level"] = close.rolling(window=window, min_periods=1).max()
            
            # Binary flags: Is price near support/resistance? (within 2%)
            df["near_support"] = (
                (close - df["support_level"]) / close <= 0.02
            ).astype(int)
            df["near_resistance"] = (
                (df["resistance_level"] - close) / close <= 0.02
            ).astype(int)
        else:
            df["support_level"] = close
            df["resistance_level"] = close
            df["near_support"] = 0
            df["near_resistance"] = 0
        
        return df
    
    def _add_price_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds a composite price momentum score (0-10).
        
        Combines:
          - Short-term momentum (5-day return)
          - Medium-term momentum (20-day return)
          - RSI position
        """
        if "return_5d" not in df.columns or "return_20d" not in df.columns:
            df["price_momentum"] = 5.0
            return df
        
        # Normalize returns to 0-10 scale
        # Assume typical 5-day return is ±5%, 20-day is ±15%
        return_5d_norm = (df["return_5d"] / 5.0).clip(-1, 1)
        return_20d_norm = (df["return_20d"] / 15.0).clip(-1, 1)
        
        # RSI normalized to -1 to +1 (50 = 0, 70 = +1, 30 = -1)
        rsi_norm = (df["RSI_14"] - 50) / 20
        rsi_norm = rsi_norm.clip(-1, 1)
        
        # Weighted combination
        momentum_raw = (
            0.4 * return_5d_norm +
            0.3 * return_20d_norm +
            0.3 * rsi_norm
        )
        
        # Convert from -1..+1 to 0..10
        df["price_momentum"] = (momentum_raw + 1) * 5
        
        return df
    
    # ── NaN Cleaning ───────────────────────────────────────────────────────
    
    def _clean_nan(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Cleans all NaN values from the DataFrame.
        
        Strategy:
          1. Forward-fill (use last valid value)
          2. Backward-fill (for leading NaNs at start)
          3. Zero-fill (if still any NaNs remain)
        
        This ensures ML models never encounter NaN input.
        """
        # Get all numeric columns (skip DatetimeIndex)
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        # Forward fill
        df[numeric_cols] = df[numeric_cols].fillna(method="ffill")
        
        # Backward fill (for leading NaNs)
        df[numeric_cols] = df[numeric_cols].fillna(method="bfill")
        
        # Zero fill any remaining NaNs
        df[numeric_cols] = df[numeric_cols].fillna(0)
        
        # Verify no NaNs remain
        nan_count = df[numeric_cols].isna().sum().sum()
        if nan_count > 0:
            logger.warning(f"Failed to clean all NaNs: {nan_count} remaining")
        
        return df
    
    # ── Public: Feature List ───────────────────────────────────────────────
    
    def get_feature_names(self) -> list[str]:
        """
        Returns the list of all technical feature column names that
        will be added by the extract() method.
        
        Useful for:
          - ML model feature selection
          - Verification that all expected features are present
        """
        features = []
        
        # Moving averages
        features.extend([f"SMA_{p}" for p in self.SMA_PERIODS])
        features.extend([f"EMA_{p}" for p in self.EMA_PERIODS])
        
        # Trend signals
        features.extend([
            "price_vs_sma200", "golden_cross", "death_cross"
        ])
        
        # Momentum
        features.extend([
            "RSI_14", "RSI_signal",
            "MACD", "MACD_signal", "MACD_hist", "MACD_crossover",
            "stoch_k", "stoch_d"
        ])
        
        # Volatility
        features.extend([
            "BB_lower", "BB_middle", "BB_upper", "BB_width", "BB_position",
            "ATR_14"
        ])
        
        # Volume
        features.extend([
            "volume_sma_20", "volume_ratio", "OBV", "VWAP"
        ])
        
        # Returns
        features.extend(["daily_return", "return_5d", "return_20d"])
        
        # Support/Resistance
        features.extend([
            "support_level", "resistance_level",
            "near_support", "near_resistance"
        ])
        
        # Momentum composite
        features.append("price_momentum")
        
        return features
    
    # ── Public: Extract for ML ─────────────────────────────────────────────
    
    def extract_for_ml(
        self,
        df: pd.DataFrame,
        feature_subset: Optional[list[str]] = None,
    ) -> pd.DataFrame:
        """
        Extracts features and returns only the feature columns
        (excludes OHLCV) for ML model input.
        
        Args:
            df: OHLCV DataFrame
            feature_subset: Optional list of specific features to return.
                           If None, returns all technical features.
        
        Returns:
            DataFrame with only feature columns, ready for ML input.
        """
        df_with_features = self.extract(df)
        
        if feature_subset:
            # Return only specified features
            available = [f for f in feature_subset if f in df_with_features.columns]
            if len(available) < len(feature_subset):
                missing = set(feature_subset) - set(available)
                logger.warning(f"Some requested features not available: {missing}")
            return df_with_features[available]
        else:
            # Return all feature columns (exclude original OHLCV)
            feature_cols = self.get_feature_names()
            available = [f for f in feature_cols if f in df_with_features.columns]
            return df_with_features[available]
