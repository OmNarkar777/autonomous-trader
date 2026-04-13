"""
ml/features/feature_pipeline.py
=================================
Orchestrates the complete feature extraction pipeline.

This is the main entry point for getting features ready for ML models.
It combines:
  1. Technical features (from OHLCV data)
  2. Fundamental features (from yfinance info)
  3. Data validation and cleaning

Output: A complete, ML-ready feature set with no NaN values.

Usage:
    from ml.features.feature_pipeline import FeaturePipeline
    pipeline = FeaturePipeline()
    
    # For a single stock
    features = pipeline.extract_features(
        symbol="RELIANCE.NS",
        historical_df=ohlcv_data,
    )
    
    # For ML model training (technical features only, from historical data)
    X, y = pipeline.prepare_ml_dataset(historical_df, target_column="future_return")
"""

from __future__ import annotations

from typing import Optional, Tuple, List, Dict, Any
import pandas as pd
import numpy as np

from ml.features.technical_features import TechnicalFeatureExtractor
from ml.features.fundamental_features import (
    FundamentalFeatureExtractor,
    FundamentalFeatures,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# FEATURE PIPELINE
# ═══════════════════════════════════════════════════════════════

class FeaturePipeline:
    """
    Central feature engineering pipeline.
    
    Orchestrates technical and fundamental feature extraction,
    handles missing data, and provides a unified interface for
    both agents and ML models.
    """
    
    def __init__(self):
        """Initialises the pipeline with both extractors."""
        self.technical_extractor = TechnicalFeatureExtractor()
        self.fundamental_extractor = FundamentalFeatureExtractor()
    
    # ── Complete Feature Extraction ────────────────────────────────────────
    
    def extract_features(
        self,
        symbol: str,
        historical_df: pd.DataFrame,
        include_fundamentals: bool = True,
    ) -> Tuple[pd.DataFrame, Optional[FundamentalFeatures]]:
        """
        Extracts complete feature set for a symbol.
        
        This is the main method used by agents during analysis cycles.
        
        Args:
            symbol: Stock symbol
            historical_df: OHLCV DataFrame
            include_fundamentals: Whether to fetch fundamental data
                                 (set False for speed if only using technicals)
        
        Returns:
            Tuple of (technical_features_df, fundamental_features_obj)
            - technical_features_df: DataFrame with all OHLCV + technical features
            - fundamental_features_obj: FundamentalFeatures dataclass or None
        """
        logger.debug(f"[{symbol}] Starting feature extraction pipeline")
        
        # ── Extract technical features ─────────────────────────────────────
        try:
            technical_df = self.technical_extractor.extract(historical_df)
            logger.debug(
                f"[{symbol}] Technical features: {len(technical_df.columns)} columns, "
                f"{len(technical_df)} rows"
            )
        except Exception as e:
            logger.error(f"[{symbol}] Technical feature extraction failed: {e}")
            raise
        
        # ── Extract fundamental features ───────────────────────────────────
        fundamental_features = None
        if include_fundamentals:
            try:
                fundamental_features = self.fundamental_extractor.extract(symbol)
                logger.debug(
                    f"[{symbol}] Fundamental score: {fundamental_features.fundamental_score:.1f}/10"
                )
            except Exception as e:
                logger.warning(f"[{symbol}] Fundamental extraction failed: {e}")
                # Non-critical — continue with technical features only
        
        return technical_df, fundamental_features
    
    # ── ML-Specific Methods ────────────────────────────────────────────────
    
    def prepare_ml_dataset(
        self,
        historical_df: pd.DataFrame,
        target_column: str,
        feature_subset: Optional[List[str]] = None,
        dropna: bool = True,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepares a dataset for ML model training.
        
        Args:
            historical_df: OHLCV DataFrame with target column already computed
            target_column: Name of the target/label column (e.g., "future_return_5d")
            feature_subset: Optional list of specific features to use.
                           If None, uses all technical features.
            dropna: Whether to drop rows with NaN in target (recommended)
        
        Returns:
            Tuple of (X: features DataFrame, y: target Series)
        
        Example:
            # First, compute target (e.g., 5-day future return)
            df["future_return_5d"] = df["Close"].pct_change(5).shift(-5) * 100
            
            # Then prepare dataset
            X, y = pipeline.prepare_ml_dataset(df, "future_return_5d")
        """
        # Extract technical features
        df_with_features = self.technical_extractor.extract(historical_df)
        
        # Separate features from target
        if target_column not in df_with_features.columns:
            raise ValueError(
                f"Target column '{target_column}' not found in DataFrame. "
                f"Available columns: {list(df_with_features.columns)}"
            )
        
        y = df_with_features[target_column]
        
        # Get feature columns
        if feature_subset:
            feature_cols = feature_subset
        else:
            # Use all technical features (exclude OHLCV and target)
            exclude = ["Open", "High", "Low", "Close", "Volume", "Adj_Close", target_column]
            feature_cols = [c for c in df_with_features.columns if c not in exclude]
        
        X = df_with_features[feature_cols]
        
        # Drop NaN in target (future returns at end of dataset)
        if dropna:
            valid_mask = ~y.isna()
            X = X[valid_mask]
            y = y[valid_mask]
        
        logger.info(
            f"ML dataset prepared: X shape={X.shape}, y shape={y.shape}, "
            f"features={len(feature_cols)}"
        )
        
        return X, y
    
    def create_lstm_sequences(
        self,
        historical_df: pd.DataFrame,
        sequence_length: int = 60,
        feature_columns: Optional[List[str]] = None,
        target_column: Optional[str] = None,
    ) -> Tuple[np.ndarray, Optional[np.ndarray]]:
        """
        Creates sequences for LSTM model training/inference.
        
        LSTM models need input shaped as (samples, timesteps, features).
        This method converts a time series DataFrame into that format.
        
        Args:
            historical_df: OHLCV DataFrame
            sequence_length: Number of timesteps per sequence (e.g., 60 days)
            feature_columns: Which features to include. If None, uses a standard set.
            target_column: If provided, also returns target labels
        
        Returns:
            Tuple of (X_sequences, y_targets)
            - X_sequences: numpy array of shape (samples, sequence_length, n_features)
            - y_targets: numpy array of shape (samples,) or None if no target_column
        
        Example:
            # For training
            X, y = pipeline.create_lstm_sequences(
                df,
                sequence_length=60,
                target_column="future_return_5d"
            )
            
            # For inference (prediction on latest data)
            X, _ = pipeline.create_lstm_sequences(
                df.tail(60),
                sequence_length=60
            )
        """
        # Extract features
        df_with_features = self.technical_extractor.extract(historical_df)
        
        # Default LSTM feature set (features that work well for time series)
        if feature_columns is None:
            feature_columns = [
                "Close", "Volume",
                "RSI_14", "MACD", "BB_position", "ATR_14",
                "daily_return", "volume_ratio",
                "price_momentum"
            ]
        
        # Filter to available columns
        available_features = [f for f in feature_columns if f in df_with_features.columns]
        if len(available_features) < len(feature_columns):
            missing = set(feature_columns) - set(available_features)
            logger.warning(f"Some LSTM features not available: {missing}")
        
        # Extract feature values
        feature_data = df_with_features[available_features].values
        
        # Create sequences
        sequences = []
        targets = [] if target_column else None
        
        for i in range(len(feature_data) - sequence_length):
            seq = feature_data[i : i + sequence_length]
            sequences.append(seq)
            
            if target_column:
                target_val = df_with_features[target_column].iloc[i + sequence_length]
                targets.append(target_val)
        
        X = np.array(sequences)
        y = np.array(targets) if targets is not None else None
        
        # Remove NaN targets
        if y is not None:
            valid_mask = ~np.isnan(y)
            X = X[valid_mask]
            y = y[valid_mask]
        
        logger.debug(
            f"LSTM sequences created: X shape={X.shape}, "
            f"features={len(available_features)}"
        )
        
        return X, y
    
    # ── Feature Importance & Selection ─────────────────────────────────────
    
    def get_all_feature_names(
        self,
        include_ohlcv: bool = False,
    ) -> List[str]:
        """
        Returns the complete list of all possible feature names.
        
        Args:
            include_ohlcv: Whether to include OHLCV columns in the list
        
        Returns:
            List of feature column names
        """
        features = self.technical_extractor.get_feature_names()
        
        if include_ohlcv:
            features = ["Open", "High", "Low", "Close", "Volume"] + features
        
        return features
    
    def get_default_ml_features(self) -> List[str]:
        """
        Returns a curated subset of features that work well for ML models.
        
        This is based on empirical testing — not all 40+ technical features
        are equally useful. This subset balances information content with
        avoiding redundancy and multicollinearity.
        """
        return [
            # Core price features
            "Close", "Volume", "daily_return",
            
            # Trend
            "SMA_20", "SMA_50", "SMA_200",
            "price_vs_sma200",
            "golden_cross", "death_cross",
            
            # Momentum
            "RSI_14", "RSI_signal",
            "MACD", "MACD_hist", "MACD_crossover",
            "stoch_k",
            
            # Volatility
            "BB_position", "BB_width",
            "ATR_14",
            
            # Volume
            "volume_ratio", "OBV",
            
            # Returns
            "return_5d", "return_20d",
            
            # Support/Resistance
            "near_support", "near_resistance",
            
            # Composite
            "price_momentum",
        ]
    
    def select_top_features(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        n_features: int = 20,
        method: str = "mutual_info",
    ) -> List[str]:
        """
        Selects the top N most informative features using statistical methods.
        
        Args:
            X: Features DataFrame
            y: Target Series
            n_features: Number of features to select
            method: "mutual_info" | "correlation" | "variance"
        
        Returns:
            List of top N feature names
        """
        from sklearn.feature_selection import mutual_info_regression
        
        if method == "mutual_info":
            # Mutual information — measures dependency between feature and target
            mi_scores = mutual_info_regression(X, y, random_state=42)
            feature_scores = pd.Series(mi_scores, index=X.columns)
            top_features = feature_scores.nlargest(n_features).index.tolist()
        
        elif method == "correlation":
            # Absolute correlation with target
            correlations = X.corrwith(y).abs()
            top_features = correlations.nlargest(n_features).index.tolist()
        
        elif method == "variance":
            # High variance features (more information)
            variances = X.var()
            top_features = variances.nlargest(n_features).index.tolist()
        
        else:
            raise ValueError(f"Unknown feature selection method: {method}")
        
        logger.info(f"Selected top {n_features} features using {method}")
        return top_features
    
    # ── Data Quality Checks ────────────────────────────────────────────────
    
    def validate_features(
        self,
        df: pd.DataFrame,
        check_inf: bool = True,
        check_constant: bool = True,
    ) -> Tuple[bool, List[str]]:
        """
        Validates that feature DataFrame is clean and ML-ready.
        
        Args:
            df: Features DataFrame
            check_inf: Check for infinite values
            check_constant: Check for constant columns (zero variance)
        
        Returns:
            Tuple of (is_valid: bool, issues: List[str])
        """
        issues = []
        
        # Check for NaN
        nan_cols = df.columns[df.isna().any()].tolist()
        if nan_cols:
            issues.append(f"NaN values found in columns: {nan_cols}")
        
        # Check for infinite values
        if check_inf:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            inf_cols = [c for c in numeric_cols if np.isinf(df[c]).any()]
            if inf_cols:
                issues.append(f"Infinite values found in columns: {inf_cols}")
        
        # Check for constant columns (zero variance)
        if check_constant:
            numeric_cols = df.select_dtypes(include=[np.number]).columns
            constant_cols = [c for c in numeric_cols if df[c].nunique() <= 1]
            if constant_cols:
                issues.append(f"Constant columns (zero variance): {constant_cols}")
        
        is_valid = len(issues) == 0
        
        if not is_valid:
            logger.warning(f"Feature validation failed: {issues}")
        else:
            logger.debug("Feature validation passed")
        
        return is_valid, issues
    
    def get_feature_statistics(
        self,
        df: pd.DataFrame,
    ) -> pd.DataFrame:
        """
        Returns descriptive statistics for all features.
        
        Useful for understanding feature distributions and detecting outliers.
        
        Returns:
            DataFrame with count, mean, std, min, max, etc. for each feature.
        """
        return df.describe()
    
    # ── Normalization & Scaling ────────────────────────────────────────────
    
    def normalize_features(
        self,
        df: pd.DataFrame,
        method: str = "minmax",
        feature_range: Tuple[float, float] = (0, 1),
    ) -> Tuple[pd.DataFrame, Any]:
        """
        Normalizes/scales features for ML model input.
        
        Args:
            df: Features DataFrame
            method: "minmax" | "standard" | "robust"
            feature_range: Range for minmax scaling (default 0-1)
        
        Returns:
            Tuple of (normalized_df, scaler_object)
            Keep the scaler for inverse_transform on predictions.
        """
        from sklearn.preprocessing import MinMaxScaler, StandardScaler, RobustScaler
        
        if method == "minmax":
            scaler = MinMaxScaler(feature_range=feature_range)
        elif method == "standard":
            scaler = StandardScaler()
        elif method == "robust":
            scaler = RobustScaler()
        else:
            raise ValueError(f"Unknown normalization method: {method}")
        
        # Fit and transform
        normalized_values = scaler.fit_transform(df)
        normalized_df = pd.DataFrame(
            normalized_values,
            index=df.index,
            columns=df.columns,
        )
        
        logger.debug(f"Features normalized using {method} scaling")
        return normalized_df, scaler
    
    # ── Cache Management ───────────────────────────────────────────────────
    
    def clear_fundamental_cache(self) -> None:
        """Clears the fundamental features cache."""
        self.fundamental_extractor.clear_cache()
        logger.debug("Fundamental feature cache cleared")
    
    def get_cached_fundamental_symbols(self) -> List[str]:
        """Returns symbols with cached fundamental data."""
        return self.fundamental_extractor.get_cached_symbols()
    
    # ── Utility Methods ────────────────────────────────────────────────────
    
    def combine_features_with_fundamentals(
        self,
        technical_df: pd.DataFrame,
        fundamental_features: FundamentalFeatures,
    ) -> pd.DataFrame:
        """
        Adds fundamental features as constant columns to technical DataFrame.
        
        This is useful when you want both technical time series and
        static fundamental metrics in the same DataFrame.
        
        Args:
            technical_df: DataFrame with technical features (time series)
            fundamental_features: FundamentalFeatures object
        
        Returns:
            DataFrame with both technical and fundamental columns
        """
        df = technical_df.copy()
        
        # Add fundamental metrics as constant columns
        # (same value repeated for all rows since fundamentals don't change daily)
        fundamental_dict = fundamental_features.to_feature_vector()
        
        for key, value in fundamental_dict.items():
            df[f"fundamental_{key}"] = value
        
        return df
    
    def extract_latest_features(
        self,
        symbol: str,
        historical_df: pd.DataFrame,
        include_fundamentals: bool = True,
    ) -> Dict[str, Any]:
        """
        Extracts features for the most recent data point only.
        
        This is used for real-time prediction (current market conditions).
        
        Args:
            symbol: Stock symbol
            historical_df: OHLCV DataFrame (at least 200 days for proper indicators)
            include_fundamentals: Whether to include fundamental features
        
        Returns:
            Dict of feature_name → value for the most recent timestamp
        """
        # Extract all features
        technical_df, fundamental_features = self.extract_features(
            symbol, historical_df, include_fundamentals
        )
        
        # Get latest row (most recent data point)
        latest_technical = technical_df.iloc[-1].to_dict()
        
        # Combine with fundamentals if available
        if fundamental_features:
            latest_fundamental = fundamental_features.to_feature_vector()
            latest_features = {**latest_technical, **latest_fundamental}
        else:
            latest_features = latest_technical
        
        return latest_features
