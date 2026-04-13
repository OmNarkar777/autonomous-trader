"""
agents/analysis_agents/technical_agent.py
===========================================
Technical Analysis Agent - scores a stock based on technical indicators.

Scoring methodology (0-10 scale):
  - Trend signals (3 points): Price vs SMA, golden/death cross
  - Momentum signals (3 points): RSI, MACD, Stochastic
  - Volume confirmation (2 points): Volume ratio, OBV trend
  - Support/Resistance (2 points): Position relative to levels

Total: Sum of component scores, normalized to 0-10

Technical score interpretation:
  - 8-10: Strong buy signal (strong uptrend + momentum)
  - 6-8: Moderate buy signal
  - 4-6: Neutral (mixed signals)
  - 2-4: Moderate sell signal
  - 0-2: Strong sell signal

Usage:
    from agents.analysis_agents.technical_agent import TechnicalAgent
    agent = TechnicalAgent()
    result = agent.run(symbol="RELIANCE.NS", historical_df=df)
    
    if result.success:
        score = result.data.technical_score
        print(f"Technical score: {score}/10")
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd
import numpy as np

from agents.base_agent import BaseAgent, AgentResult
from ml.features.technical_features import TechnicalFeatureExtractor
from data.storage.cache import cache
from config.constants import (
    RSI_OVERSOLD,
    RSI_OVERBOUGHT,
    BB_LOWER_THRESHOLD,
    BB_UPPER_THRESHOLD,
    VOLUME_SURGE_MULTIPLIER,
)
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class TechnicalAgentOutput:
    """Structured output from TechnicalAgent."""
    symbol: str
    technical_score: float  # 0-10
    trend_score: float      # 0-3
    momentum_score: float   # 0-3
    volume_score: float     # 0-2
    support_resistance_score: float  # 0-2
    
    # Individual indicator values (for explainability)
    rsi: float
    macd_signal: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    price_vs_sma200: float
    volume_ratio: float
    bb_position: float
    
    # Detailed breakdown
    scoring_breakdown: Dict[str, Any]
    recommendation: str  # "STRONG_BUY" | "BUY" | "HOLD" | "SELL" | "STRONG_SELL"


# ═══════════════════════════════════════════════════════════════
# TECHNICAL AGENT
# ═══════════════════════════════════════════════════════════════

class TechnicalAgent(BaseAgent):
    """
    Agent that scores stocks based on technical analysis.
    
    Analyzes price patterns, momentum, volume, and support/resistance
    to produce a 0-10 technical score.
    """
    
    def __init__(self):
        super().__init__(agent_name="TechnicalAgent")
        self.feature_extractor = TechnicalFeatureExtractor()
    
    def execute(
        self,
        symbol: str,
        historical_df: pd.DataFrame,
        **kwargs
    ) -> AgentResult:
        """
        Analyzes technical indicators and produces a score.
        
        Args:
            symbol: Stock symbol
            historical_df: DataFrame with OHLCV data (at least 200 days)
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with TechnicalAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Running technical analysis")
        
        # ── Check cache ────────────────────────────────────────────────────
        cached_output = cache.get_cached_agent_output("TechnicalAgent", symbol)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached technical analysis")
            return self.success_result(
                data=TechnicalAgentOutput(**cached_output),
                metadata={"source": "cache"}
            )
        
        # ── Extract features ───────────────────────────────────────────────
        try:
            df = self.feature_extractor.extract(historical_df)
            self.logger.debug(f"[{symbol}] Extracted {len(df.columns)} technical features")
        except Exception as e:
            self.logger.error(f"[{symbol}] Feature extraction failed: {e}")
            return self.failure_result(
                error=f"Technical feature extraction failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # Get latest values (most recent day)
        latest = df.iloc[-1]
        
        # ── Score: Trend Signals (0-3 points) ─────────────────────────────
        trend_score, trend_breakdown = self._score_trend(latest, df)
        
        # ── Score: Momentum Signals (0-3 points) ──────────────────────────
        momentum_score, momentum_breakdown = self._score_momentum(latest)
        
        # ── Score: Volume Confirmation (0-2 points) ───────────────────────
        volume_score, volume_breakdown = self._score_volume(latest)
        
        # ── Score: Support/Resistance (0-2 points) ────────────────────────
        sr_score, sr_breakdown = self._score_support_resistance(latest)
        
        # ── Calculate total score ──────────────────────────────────────────
        technical_score = trend_score + momentum_score + volume_score + sr_score
        
        # ── Determine recommendation ───────────────────────────────────────
        if technical_score >= 8:
            recommendation = "STRONG_BUY"
        elif technical_score >= 6:
            recommendation = "BUY"
        elif technical_score >= 4:
            recommendation = "HOLD"
        elif technical_score >= 2:
            recommendation = "SELL"
        else:
            recommendation = "STRONG_SELL"
        
        # ── Build output ───────────────────────────────────────────────────
        output = TechnicalAgentOutput(
            symbol=symbol,
            technical_score=round(technical_score, 2),
            trend_score=round(trend_score, 2),
            momentum_score=round(momentum_score, 2),
            volume_score=round(volume_score, 2),
            support_resistance_score=round(sr_score, 2),
            rsi=float(latest.get("RSI_14", 50)),
            macd_signal=self._get_macd_signal(latest),
            price_vs_sma200=float(latest.get("price_vs_sma200", 0)),
            volume_ratio=float(latest.get("volume_ratio", 1.0)),
            bb_position=float(latest.get("BB_position", 0.5)),
            scoring_breakdown={
                "trend": trend_breakdown,
                "momentum": momentum_breakdown,
                "volume": volume_breakdown,
                "support_resistance": sr_breakdown,
            },
            recommendation=recommendation,
        )
        
        self.logger.info(
            f"[{symbol}] Technical score: {technical_score:.1f}/10 | "
            f"Recommendation: {recommendation} | "
            f"RSI: {output.rsi:.1f}, MACD: {output.macd_signal}"
        )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache.cache_agent_output(
            "TechnicalAgent",
            symbol,
            output.__dict__,
            ttl=300  # 5 minutes
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "score": technical_score,
                "recommendation": recommendation,
            }
        )
    
    # ── Scoring: Trend ─────────────────────────────────────────────────────
    
    def _score_trend(
        self,
        latest: pd.Series,
        df: pd.DataFrame,
    ) -> tuple[float, Dict[str, Any]]:
        """
        Scores trend strength (0-3 points).
        
        Components:
          - Price vs SMA200 (1 point): Above = bullish, Below = bearish
          - Golden/Death Cross (1 point): Recent crossover signals
          - EMA crossover (1 point): EMA12 vs EMA26
        """
        score = 0.0
        breakdown = {}
        
        # ── Price vs SMA200 ────────────────────────────────────────────────
        price_vs_sma200 = latest.get("price_vs_sma200", 0)
        
        if price_vs_sma200 > 5:
            # Strongly above SMA200 (>5%)
            score += 1.0
            breakdown["price_vs_sma200"] = f"✓ {price_vs_sma200:+.1f}% above SMA200 (+1.0)"
        elif price_vs_sma200 > 0:
            # Above SMA200 but not strongly
            score += 0.5
            breakdown["price_vs_sma200"] = f"~ {price_vs_sma200:+.1f}% above SMA200 (+0.5)"
        elif price_vs_sma200 > -5:
            # Slightly below SMA200
            score += 0.0
            breakdown["price_vs_sma200"] = f"~ {price_vs_sma200:+.1f}% below SMA200 (0.0)"
        else:
            # Strongly below SMA200
            score += 0.0
            breakdown["price_vs_sma200"] = f"✗ {price_vs_sma200:+.1f}% below SMA200 (0.0)"
        
        # ── Golden/Death Cross ─────────────────────────────────────────────
        golden_cross = latest.get("golden_cross", 0)
        death_cross = latest.get("death_cross", 0)
        
        if golden_cross:
            score += 1.0
            breakdown["crossover"] = "✓ Golden cross detected (SMA50 > SMA200) (+1.0)"
        elif death_cross:
            score += 0.0
            breakdown["crossover"] = "✗ Death cross detected (SMA50 < SMA200) (0.0)"
        else:
            # Check if SMA50 > SMA200 (bullish alignment even without recent cross)
            sma50 = latest.get("SMA_50", 0)
            sma200 = latest.get("SMA_200", 0)
            if sma50 > sma200 and sma50 > 0 and sma200 > 0:
                score += 0.5
                breakdown["crossover"] = "~ SMA50 above SMA200 (bullish alignment) (+0.5)"
            else:
                breakdown["crossover"] = "No recent crossover (0.0)"
        
        # ── EMA Crossover ──────────────────────────────────────────────────
        ema12 = latest.get("EMA_12", 0)
        ema26 = latest.get("EMA_26", 0)
        
        if ema12 > ema26 and ema12 > 0 and ema26 > 0:
            score += 1.0
            breakdown["ema_crossover"] = "✓ EMA12 > EMA26 (bullish) (+1.0)"
        elif ema12 < ema26:
            score += 0.0
            breakdown["ema_crossover"] = "✗ EMA12 < EMA26 (bearish) (0.0)"
        else:
            score += 0.5
            breakdown["ema_crossover"] = "~ EMA12 ≈ EMA26 (neutral) (+0.5)"
        
        return min(score, 3.0), breakdown
    
    # ── Scoring: Momentum ──────────────────────────────────────────────────
    
    def _score_momentum(self, latest: pd.Series) -> tuple[float, Dict[str, Any]]:
        """
        Scores momentum strength (0-3 points).
        
        Components:
          - RSI (1 point): Oversold/overbought levels
          - MACD (1 point): MACD vs signal line
          - Stochastic (1 point): %K vs %D
        """
        score = 0.0
        breakdown = {}
        
        # ── RSI ────────────────────────────────────────────────────────────
        rsi = latest.get("RSI_14", 50)
        
        if rsi < RSI_OVERSOLD:
            # Oversold → potential bounce
            score += 1.0
            breakdown["rsi"] = f"✓ RSI={rsi:.1f} (oversold, potential bounce) (+1.0)"
        elif rsi > RSI_OVERBOUGHT:
            # Overbought → potential reversal down
            score += 0.0
            breakdown["rsi"] = f"✗ RSI={rsi:.1f} (overbought, reversal risk) (0.0)"
        elif 45 <= rsi <= 55:
            # Neutral zone
            score += 0.5
            breakdown["rsi"] = f"~ RSI={rsi:.1f} (neutral) (+0.5)"
        elif rsi > 50:
            # Above 50 = bullish momentum
            score += 0.7
            breakdown["rsi"] = f"✓ RSI={rsi:.1f} (bullish momentum) (+0.7)"
        else:
            # Below 50 = bearish momentum
            score += 0.3
            breakdown["rsi"] = f"~ RSI={rsi:.1f} (weak momentum) (+0.3)"
        
        # ── MACD ───────────────────────────────────────────────────────────
        macd = latest.get("MACD", 0)
        macd_signal = latest.get("MACD_signal", 0)
        macd_crossover = latest.get("MACD_crossover", 0)
        
        if macd_crossover:
            # Recent bullish crossover
            score += 1.0
            breakdown["macd"] = "✓ MACD bullish crossover (+1.0)"
        elif macd > macd_signal and macd > 0:
            # MACD above signal and positive
            score += 0.8
            breakdown["macd"] = "✓ MACD above signal (bullish) (+0.8)"
        elif macd > macd_signal:
            # MACD above signal but negative
            score += 0.5
            breakdown["macd"] = "~ MACD above signal but negative (+0.5)"
        else:
            # MACD below signal (bearish)
            score += 0.0
            breakdown["macd"] = "✗ MACD below signal (bearish) (0.0)"
        
        # ── Stochastic ─────────────────────────────────────────────────────
        stoch_k = latest.get("stoch_k", 50)
        stoch_d = latest.get("stoch_d", 50)
        
        if stoch_k < 20:
            # Oversold
            score += 1.0
            breakdown["stochastic"] = f"✓ Stoch={stoch_k:.1f} (oversold) (+1.0)"
        elif stoch_k > 80:
            # Overbought
            score += 0.0
            breakdown["stochastic"] = f"✗ Stoch={stoch_k:.1f} (overbought) (0.0)"
        elif stoch_k > stoch_d:
            # %K above %D (bullish)
            score += 0.6
            breakdown["stochastic"] = f"✓ Stoch %K > %D (bullish) (+0.6)"
        else:
            # %K below %D (bearish)
            score += 0.3
            breakdown["stochastic"] = f"~ Stoch %K < %D (bearish) (+0.3)"
        
        return min(score, 3.0), breakdown
    
    # ── Scoring: Volume ────────────────────────────────────────────────────
    
    def _score_volume(self, latest: pd.Series) -> tuple[float, Dict[str, Any]]:
        """
        Scores volume confirmation (0-2 points).
        
        Components:
          - Volume ratio (1 point): Today's volume vs average
          - OBV trend (1 point): On-Balance Volume momentum
        """
        score = 0.0
        breakdown = {}
        
        # ── Volume Ratio ───────────────────────────────────────────────────
        volume_ratio = latest.get("volume_ratio", 1.0)
        
        if volume_ratio > VOLUME_SURGE_MULTIPLIER:
            # High volume = strong conviction
            score += 1.0
            breakdown["volume_ratio"] = f"✓ Volume {volume_ratio:.1f}x average (surge) (+1.0)"
        elif volume_ratio > 1.2:
            # Above average volume
            score += 0.7
            breakdown["volume_ratio"] = f"✓ Volume {volume_ratio:.1f}x average (above avg) (+0.7)"
        elif volume_ratio > 0.8:
            # Normal volume
            score += 0.5
            breakdown["volume_ratio"] = f"~ Volume {volume_ratio:.1f}x average (normal) (+0.5)"
        else:
            # Below average volume (weak conviction)
            score += 0.2
            breakdown["volume_ratio"] = f"~ Volume {volume_ratio:.1f}x average (low) (+0.2)"
        
        # ── OBV Trend (simple: compare today vs 5 days ago) ───────────────
        # OBV is cumulative, so we just check if it's rising
        # This is a simplified check - ideally we'd look at OBV slope
        score += 0.5  # Neutral contribution since we can't easily trend OBV here
        breakdown["obv"] = "~ OBV trend (neutral contribution) (+0.5)"
        
        return min(score, 2.0), breakdown
    
    # ── Scoring: Support/Resistance ────────────────────────────────────────
    
    def _score_support_resistance(
        self,
        latest: pd.Series,
    ) -> tuple[float, Dict[str, Any]]:
        """
        Scores position relative to support/resistance (0-2 points).
        
        Components:
          - Bollinger Bands position (1 point): Where price sits in the bands
          - Support/Resistance proximity (1 point): Near key levels
        """
        score = 0.0
        breakdown = {}
        
        # ── Bollinger Bands Position ───────────────────────────────────────
        bb_position = latest.get("BB_position", 0.5)
        
        if bb_position < BB_LOWER_THRESHOLD:
            # Near lower band (oversold, potential bounce)
            score += 1.0
            breakdown["bb_position"] = f"✓ BB position {bb_position:.2f} (near lower, bounce potential) (+1.0)"
        elif bb_position > BB_UPPER_THRESHOLD:
            # Near upper band (overbought, reversal risk)
            score += 0.0
            breakdown["bb_position"] = f"✗ BB position {bb_position:.2f} (near upper, reversal risk) (0.0)"
        elif 0.4 <= bb_position <= 0.6:
            # Middle of bands (neutral)
            score += 0.5
            breakdown["bb_position"] = f"~ BB position {bb_position:.2f} (middle) (+0.5)"
        elif bb_position > 0.5:
            # Above middle (bullish)
            score += 0.7
            breakdown["bb_position"] = f"✓ BB position {bb_position:.2f} (above middle) (+0.7)"
        else:
            # Below middle (bearish)
            score += 0.3
            breakdown["bb_position"] = f"~ BB position {bb_position:.2f} (below middle) (+0.3)"
        
        # ── Support/Resistance Proximity ───────────────────────────────────
        near_support = latest.get("near_support", 0)
        near_resistance = latest.get("near_resistance", 0)
        
        if near_support:
            # Near support = bounce potential
            score += 1.0
            breakdown["support_resistance"] = "✓ Near support level (bounce potential) (+1.0)"
        elif near_resistance:
            # Near resistance = breakout or reversal
            score += 0.5
            breakdown["support_resistance"] = "~ Near resistance (breakout or reversal) (+0.5)"
        else:
            # Not near key levels
            score += 0.5
            breakdown["support_resistance"] = "~ No key levels nearby (+0.5)"
        
        return min(score, 2.0), breakdown
    
    # ── Helpers ────────────────────────────────────────────────────────────
    
    def _get_macd_signal(self, latest: pd.Series) -> str:
        """Returns MACD signal as string."""
        macd = latest.get("MACD", 0)
        macd_signal = latest.get("MACD_signal", 0)
        
        if macd > macd_signal and macd > 0:
            return "BULLISH"
        elif macd < macd_signal:
            return "BEARISH"
        else:
            return "NEUTRAL"
