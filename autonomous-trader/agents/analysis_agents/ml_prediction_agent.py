"""
agents/analysis_agents/ml_prediction_agent.py
===============================================
ML Prediction Agent - runs trained ensemble model for price prediction.

This agent:
  1. Loads the trained ensemble model (LSTM + XGBoost)
  2. Makes predictions on latest data
  3. Returns probability of price increase and model confidence

The ML score is a critical input to the Decision Agent's final call.

ML score interpretation (probability of 5-day price increase):
  - 0.75-1.00: Very high probability of gain (strong BUY signal)
  - 0.60-0.75: High probability (BUY signal)
  - 0.40-0.60: Uncertain (HOLD)
  - 0.25-0.40: Low probability (SELL signal)
  - 0.00-0.25: Very low probability (strong SELL signal)

Usage:
    from agents.analysis_agents.ml_prediction_agent import MLPredictionAgent
    agent = MLPredictionAgent()
    result = agent.run(symbol="RELIANCE.NS", historical_df=df)
    
    if result.success:
        prob = result.data.probability_up
        print(f"ML predicts {prob:.1%} chance of price increase")
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd

from agents.base_agent import BaseAgent, AgentResult
from ml.models.ensemble import EnsemblePredictor, EnsemblePrediction
from ml.training.trainer import ModelTrainer
from data.storage.cache import cache
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class MLPredictionAgentOutput:
    """Structured output from MLPredictionAgent."""
    symbol: str
    
    # Predictions
    probability_up: float  # 0-1 (ensemble probability of price increase)
    ml_score: float        # 0-10 (normalized from probability)
    decision: str          # "BUY" | "SELL" | "HOLD" (from ensemble)
    confidence: float      # 0-1 (model confidence)
    
    # Individual model outputs
    lstm_prob: float       # LSTM 5-day probability
    xgboost_prob: float    # XGBoost probability
    model_agreement: float # How much models agree (0-1)
    
    # Meta
    reasoning: str
    disagreement_flag: bool  # True if models strongly disagree
    ensemble_prediction: EnsemblePrediction  # Full prediction object


# ═══════════════════════════════════════════════════════════════
# ML PREDICTION AGENT
# ═══════════════════════════════════════════════════════════════

class MLPredictionAgent(BaseAgent):
    """
    Agent that makes ML-based predictions using trained ensemble.
    
    Loads the trained LSTM + XGBoost ensemble and runs inference
    on the latest historical data to predict price movement.
    """
    
    def __init__(self):
        super().__init__(agent_name="MLPredictionAgent")
        self.trainer = ModelTrainer()
        self._loaded_models: Dict[str, EnsemblePredictor] = {}
    
    def execute(
        self,
        symbol: str,
        historical_df: pd.DataFrame,
        **kwargs
    ) -> AgentResult:
        """
        Makes ML prediction for a symbol.
        
        Args:
            symbol: Stock symbol
            historical_df: DataFrame with OHLCV data (at least 200 days)
            **kwargs: Additional parameters (currently unused)
        
        Returns:
            AgentResult with MLPredictionAgentOutput in data field
        """
        self.logger.info(f"[{symbol}] Running ML prediction")
        
        # ── Check cache ────────────────────────────────────────────────────
        cached_output = cache.get_cached_agent_output("MLPredictionAgent", symbol)
        if cached_output:
            self.logger.debug(f"[{symbol}] Using cached ML prediction")
            # Re-hydrate EnsemblePrediction
            ensemble_pred = EnsemblePrediction(**cached_output["ensemble_prediction"])
            cached_output["ensemble_prediction"] = ensemble_pred
            return self.success_result(
                data=MLPredictionAgentOutput(**cached_output),
                metadata={"source": "cache"}
            )
        
        # ── Load or train model ────────────────────────────────────────────
        try:
            ensemble = self._get_model(symbol, historical_df)
        except Exception as e:
            self.logger.error(f"[{symbol}] Failed to load/train model: {e}")
            return self.failure_result(
                error=f"Model loading failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # ── Make prediction ────────────────────────────────────────────────
        try:
            prediction = ensemble.predict(historical_df)
            
            self.logger.debug(
                f"[{symbol}] Ensemble prediction: {prediction.decision} | "
                f"Score: {prediction.score:.2f} | Confidence: {prediction.confidence:.2f}"
            )
        
        except Exception as e:
            self.logger.error(f"[{symbol}] Prediction failed: {e}")
            return self.failure_result(
                error=f"Prediction failed: {e}",
                metadata={"symbol": symbol}
            )
        
        # ── Extract components ─────────────────────────────────────────────
        probability_up = prediction.score  # Ensemble score is already a 0-1 probability
        ml_score = probability_up * 10     # Normalize to 0-10 scale
        
        lstm_prob = prediction.lstm_prediction.prob_up_5day
        xgboost_prob = prediction.xgboost_prediction.prob_up
        
        # ── Build output ───────────────────────────────────────────────────
        output = MLPredictionAgentOutput(
            symbol=symbol,
            probability_up=round(probability_up, 3),
            ml_score=round(ml_score, 2),
            decision=prediction.decision,
            confidence=round(prediction.confidence, 2),
            lstm_prob=round(lstm_prob, 3),
            xgboost_prob=round(xgboost_prob, 3),
            model_agreement=round(prediction.model_agreement, 2),
            reasoning=prediction.reasoning,
            disagreement_flag=prediction.disagreement_flag,
            ensemble_prediction=prediction,
        )
        
        self.logger.info(
            f"[{symbol}] ML score: {ml_score:.1f}/10 | "
            f"Probability up: {probability_up:.1%} | "
            f"Decision: {prediction.decision} | "
            f"Confidence: {prediction.confidence:.2f}"
        )
        
        # ── Log disagreement warning ───────────────────────────────────────
        if output.disagreement_flag:
            self.logger.warning(
                f"[{symbol}] ⚠️ Model disagreement detected | "
                f"LSTM: {lstm_prob:.1%}, XGBoost: {xgboost_prob:.1%}"
            )
        
        # ── Cache the output ───────────────────────────────────────────────
        cache_data = output.__dict__.copy()
        cache_data["ensemble_prediction"] = {
            "symbol": prediction.symbol,
            "score": prediction.score,
            "decision": prediction.decision,
            "confidence": prediction.confidence,
            "model_agreement": prediction.model_agreement,
            "disagreement_flag": prediction.disagreement_flag,
            "reasoning": prediction.reasoning,
            "lstm_prediction": {
                "prob_up_1day": prediction.lstm_prediction.prob_up_1day,
                "prob_up_3day": prediction.lstm_prediction.prob_up_3day,
                "prob_up_7day": prediction.lstm_prediction.prob_up_7day,
                "confidence": prediction.lstm_prediction.confidence,
            },
            "xgboost_prediction": {
                "prob_up": prediction.xgboost_prediction.prob_up,
                "confidence": prediction.xgboost_prediction.confidence,
            },
        }
        
        cache.cache_agent_output(
            "MLPredictionAgent",
            symbol,
            cache_data,
            ttl=600  # 10 minutes (predictions can be reused within a trading cycle)
        )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "ml_score": ml_score,
                "probability_up": probability_up,
                "decision": prediction.decision,
                "confidence": prediction.confidence,
            }
        )
    
    # ── Model Management ───────────────────────────────────────────────────
    
    def _get_model(
        self,
        symbol: str,
        historical_df: pd.DataFrame,
    ) -> EnsemblePredictor:
        """
        Gets the trained model for a symbol.
        
        Strategy:
          1. Check in-memory cache
          2. Try to load from disk
          3. If model doesn't exist or is stale, train a new one
        
        Args:
            symbol: Stock symbol
            historical_df: Historical data for training if needed
        
        Returns:
            Trained EnsemblePredictor
        """
        # ── Check in-memory cache ──────────────────────────────────────────
        if symbol in self._loaded_models:
            self.logger.debug(f"[{symbol}] Using in-memory cached model")
            return self._loaded_models[symbol]
        
        # ── Try to load from disk ──────────────────────────────────────────
        if self.trainer.model_exists(symbol):
            model_age = self.trainer.get_model_age(symbol)
            
            # Check if model is fresh enough (< 7 days old)
            if model_age and model_age.days < 7:
                self.logger.info(
                    f"[{symbol}] Loading trained model from disk "
                    f"(age: {model_age.days} days)"
                )
                
                try:
                    ensemble = self.trainer.load_model(symbol)
                    self._loaded_models[symbol] = ensemble
                    return ensemble
                
                except Exception as e:
                    self.logger.warning(
                        f"[{symbol}] Failed to load model from disk: {e}. "
                        f"Will train a new one."
                    )
            else:
                self.logger.warning(
                    f"[{symbol}] Model is stale ({model_age.days} days old). "
                    f"Training a new one."
                )
        
        # ── Train a new model ──────────────────────────────────────────────
        self.logger.info(f"[{symbol}] Training new ensemble model")
        
        ensemble = EnsemblePredictor(symbol=symbol)
        
        try:
            ensemble.train(
                historical_df,
                lstm_epochs=50,  # Reduced for faster inference
                lstm_verbose=0,
            )
            
            # Save the model for future use
            try:
                model_path = self.trainer._get_model_path(symbol)
                ensemble.save(str(model_path))
                self.logger.info(f"[{symbol}] Model trained and saved to {model_path}")
            except Exception as e:
                self.logger.warning(f"[{symbol}] Failed to save model: {e}")
            
            # Cache in memory
            self._loaded_models[symbol] = ensemble
            
            return ensemble
        
        except Exception as e:
            self.logger.error(f"[{symbol}] Model training failed: {e}")
            raise
    
    # ── Model Stats ────────────────────────────────────────────────────────
    
    def get_loaded_models(self) -> list[str]:
        """Returns list of symbols with models loaded in memory."""
        return list(self._loaded_models.keys())
    
    def clear_model_cache(self) -> None:
        """Clears in-memory model cache to free RAM."""
        count = len(self._loaded_models)
        self._loaded_models.clear()
        self.logger.info(f"Cleared {count} models from memory cache")
