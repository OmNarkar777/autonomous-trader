"""
agents/decision_agent.py
=========================
THE DECISION AGENT - The brain of the autonomous trading system.

This is the most critical agent. It orchestrates ALL other agents
and makes the final BUY/SELL/HOLD decision.

Decision Flow:
  Phase 1: Data Collection
    â†’ PriceAgent: Get current price + historical data
    â†’ NewsAgent: Get news articles
    â†’ MacroAgent: Get market regime
    â†’ EarningsAgent: Check earnings risk
  
  Phase 2: Data Validation
    â†’ DataValidator: Validate all data quality
    â†’ If validation fails â†’ HOLD (skip symbol)
  
  Phase 3: Analysis (TODO: implement these agents)
    â†’ TechnicalAgent: Calculate technical score (0-10)
    â†’ FundamentalAgent: Calculate fundamental score (0-10)
    â†’ SentimentAgent: Calculate sentiment score (0-10)
    â†’ MLAgent: Get ML model prediction (0-1)
  
  Phase 4: Risk Assessment
    â†’ EventRiskAgent: Check event-based risks (macro + earnings)
    â†’ PortfolioRiskAgent: Check portfolio constraints
    â†’ PositionSizingAgent: Calculate position size
  
  Phase 5: Decision Making
    â†’ Combine all scores with weights
    â†’ Apply confidence threshold
    â†’ Make final BUY/SELL/HOLD decision
    â†’ Generate detailed reasoning

Output:
  - decision: "BUY" | "SELL" | "HOLD"
  - confidence: float (0-1)
  - quantity: int (if BUY)
  - stop_loss: float (if BUY)
  - take_profit: float (if BUY)
  - reasoning: str (detailed explanation)
  - all_scores: Dict (technical, fundamental, sentiment, ml, combined)

Usage:
    from agents.decision_agent import DecisionAgent
    agent = DecisionAgent()
    result = agent.run(symbol="RELIANCE.NS", company_name="Reliance Industries")
    
    if result.success and result.data.decision == "BUY":
        print(f"BUY {result.data.quantity} shares @ {result.data.entry_price}")
        print(f"Reasoning: {result.data.reasoning}")
"""

from __future__ import annotations

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from data.storage.recommendation_db import RecommendationDB

from agents.base_agent import BaseAgent, AgentResult
from agents.data_agents.price_agent import PriceAgent
from agents.data_agents.news_agent import NewsAgent
from agents.data_agents.macro_agent import MacroAgent
from agents.data_agents.earnings_agent import EarningsAgent
from agents.risk_agents.position_sizing_agent import PositionSizingAgent
from agents.risk_agents.event_risk_agent import EventRiskAgent
from agents.risk_agents.portfolio_risk_agent import PortfolioRiskAgent
from data.validators.data_validator import DataValidator
from data.storage.database import DatabaseManager
from data.collectors.macro_collector import MacroCollector
from config.constants import (
    DECISION_CONFIDENCE_THRESHOLD,
    DECISION_TECHNICAL_WEIGHT,
    DECISION_FUNDAMENTAL_WEIGHT,
    DECISION_SENTIMENT_WEIGHT,
    DECISION_ML_WEIGHT,
)
from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DATA CLASSES
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

@dataclass
class DecisionOutput:
    """Complete decision output with all details."""
    symbol: str
    company_name: str
    decision: str  # "BUY" | "SELL" | "HOLD"
    confidence: float  # 0-1
    
    # Trade details (populated if BUY)
    quantity: int = 0
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_value: float = 0.0
    risk_amount: float = 0.0
    
    # Scores (0-10 scale except ML which is 0-1)
    technical_score: float = 5.0
    fundamental_score: float = 5.0
    sentiment_score: float = 5.0
    ml_score: float = 0.5
    combined_score: float = 5.0  # Weighted average of all scores
    
    # Data quality
    data_quality_score: float = 1.0
    validation_passed: bool = True
    
    # Risk factors
    event_risk_multiplier: float = 1.0
    blocks_trading: bool = False
    risk_factors: list = field(default_factory=list)
    
    # Reasoning
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.utcnow())


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# DECISION AGENT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

class DecisionAgent(BaseAgent):
    """
    THE DECISION AGENT
    
    Orchestrates all agents and makes final trading decisions.
    This is the "CEO" of the agent system.
    """
    
    def __init__(self, db: DatabaseManager = None):
        super().__init__(agent_name="DecisionAgent")
        
        # Data agents
        self.price_agent = PriceAgent()
        self.news_agent = NewsAgent()
        self.macro_agent = MacroAgent()
        self.earnings_agent = EarningsAgent()
        
        # Analysis agents (TODO: implement these)
        # self.technical_agent = TechnicalAgent()
        # self.fundamental_agent = FundamentalAgent()
        # self.sentiment_agent = SentimentAgent()
        # self.ml_agent = MLAgent()
        
        # Risk agents
        self.position_sizing_agent = PositionSizingAgent()
        self.event_risk_agent = EventRiskAgent()
        self.portfolio_risk_agent = PortfolioRiskAgent(db=db)
        
        # Utilities
        self.validator = DataValidator()
        self.macro_collector = MacroCollector()
        self.db = db or DatabaseManager()
    
    def execute(
        self,
        symbol: str,
        company_name: str,
        **kwargs
    ) -> AgentResult:
        """
        Makes a trading decision for a symbol.
        
        Args:
            symbol: Stock symbol
            company_name: Company name for news search
            **kwargs: Additional parameters
        
        Returns:
            AgentResult with DecisionOutput in data field
        """
        self.logger.info(f"[{symbol}] â•â•â• STARTING DECISION PROCESS â•â•â•")
        
        output = DecisionOutput(symbol=symbol, company_name=company_name, decision="HOLD", confidence=0.0)
        
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        # PHASE 1: DATA COLLECTION
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        
        self.logger.info(f"[{symbol}] Phase 1: Data Collection")
        
        # â”€â”€ Fetch price data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        price_result = self.price_agent.run(symbol=symbol)
        if not price_result.success:
            output.decision = "HOLD"
            output.reasoning = f"Data collection failed: {price_result.error}"
            return self.success_result(data=output)
        
        price_data = price_result.data.current_price
        historical_data = price_result.data.historical_data
        
        # â”€â”€ Fetch news data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        news_result = self.news_agent.run(
            symbol=symbol,
            company_name=company_name,
            hours_back=48
        )
        if not news_result.success:
            self.logger.warning(f"[{symbol}] News fetch failed: {news_result.error}")
            news_data = []
        else:
            news_data = news_result.data.articles
        
        # â”€â”€ Fetch macro data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        macro_result = self.macro_agent.run()
        if not macro_result.success:
            output.decision = "HOLD"
            output.reasoning = f"Macro data fetch failed: {macro_result.error}"
            return self.success_result(data=output)
        
        macro_data = macro_result.data
        
        # â”€â”€ Fetch earnings risk â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        earnings_result = self.earnings_agent.run(symbol=symbol)
        if not earnings_result.success:
            output.decision = "HOLD"
            output.reasoning = f"Earnings check failed: {earnings_result.error}"
            return self.success_result(data=output)
        
        earnings_data = earnings_result.data
        
        self.logger.info(
            f"[{symbol}] Data collected | "
            f"Price: {price_data.current_price:.2f}, "
            f"News: {len(news_data)}, "
            f"Regime: {macro_data.regime}"
        )
        
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        # PHASE 2: DATA VALIDATION
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        
        self.logger.info(f"[{symbol}] Phase 2: Data Validation")
        
        validation_result = self.validator.validate_all_data_for_symbol(
            symbol=symbol,
            price_data=price_data,
            news_data=news_data,
            historical_data=historical_data,
        )
        
        output.validation_passed = validation_result.is_valid
        output.data_quality_score = validation_result.data_quality_score
        
        if not validation_result.is_valid:
            output.decision = "HOLD"
            output.reasoning = (
                f"Data validation failed: {validation_result.reason}. "
                f"Quality score: {validation_result.data_quality_score:.2f}"
            )
            self.logger.warning(f"[{symbol}] {output.reasoning}")
            return self.success_result(data=output)
        
        self.logger.info(
            f"[{symbol}] Validation passed | Quality: {validation_result.data_quality_score:.2f}"
        )
        
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        # PHASE 3: ANALYSIS
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        
        self.logger.info(f"[{symbol}] Phase 3: Analysis")
        
        # TODO: Call TechnicalAgent
        # For now, use placeholder score based on simple price momentum
        technical_score = self._placeholder_technical_score(historical_data)
        output.technical_score = technical_score
        
        # TODO: Call FundamentalAgent
        # For now, use placeholder score
        fundamental_score = self._placeholder_fundamental_score()
        output.fundamental_score = fundamental_score
        
        # TODO: Call SentimentAgent
        # For now, use placeholder score based on news count
        sentiment_score = self._placeholder_sentiment_score(news_data)
        output.sentiment_score = sentiment_score
        
        # TODO: Call MLAgent
        # For now, use placeholder score
        ml_score = self._placeholder_ml_score()
        output.ml_score = ml_score
        
        self.logger.info(
            f"[{symbol}] Analysis complete | "
            f"Technical: {technical_score:.1f}, "
            f"Fundamental: {fundamental_score:.1f}, "
            f"Sentiment: {sentiment_score:.1f}, "
            f"ML: {ml_score:.2f}"
        )
        
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        # PHASE 4: RISK ASSESSMENT
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        
        self.logger.info(f"[{symbol}] Phase 4: Risk Assessment")
        
        # â”€â”€ Check event risks â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        event_risk_result = self.event_risk_agent.run(
            symbol=symbol,
            macro_output=macro_data,
            earnings_output=earnings_data,
        )
        
        if not event_risk_result.success:
            output.decision = "HOLD"
            output.reasoning = f"Event risk check failed: {event_risk_result.error}"
            return self.success_result(data=output)
        
        event_risk_data = event_risk_result.data
        
        # If event risk blocks trading â†’ immediate HOLD
        if event_risk_data.blocks_trading:
            output.decision = "HOLD"
            output.blocks_trading = True
            output.risk_factors = event_risk_data.risk_factors
            output.reasoning = (
                f"Trade blocked by event risk: {', '.join(event_risk_data.risk_factors)}"
            )
            self.logger.warning(f"[{symbol}] {output.reasoning}")
            return self.success_result(data=output)
        
        output.event_risk_multiplier = event_risk_data.combined_multiplier
        output.risk_factors = event_risk_data.risk_factors
        
        # â”€â”€ Calculate position size â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Get ATR from historical data
        atr = historical_data["ATR_14"].iloc[-1] if "ATR_14" in historical_data.columns else price_data.current_price * 0.02
        
        # Get available capital
        portfolio_value = self.db.get_portfolio_value() or 100000
        available_capital = portfolio_value  # Simplified - in production, check cash balance
        
        position_sizing_result = self.position_sizing_agent.run(
            symbol=symbol,
            current_price=price_data.current_price,
            atr=atr,
            available_capital=available_capital,
            regime_multiplier=event_risk_data.regime_multiplier,
            earnings_multiplier=event_risk_data.earnings_multiplier,
            data_quality_score=validation_result.data_quality_score,
        )
        
        if not position_sizing_result.success:
            output.decision = "HOLD"
            output.reasoning = f"Position sizing failed: {position_sizing_result.error}"
            return self.success_result(data=output)
        
        position_sizing_data = position_sizing_result.data
        
        # If position sizing rejected â†’ HOLD
        if not position_sizing_data.is_valid:
            output.decision = "HOLD"
            output.reasoning = f"Position sizing rejected: {position_sizing_data.rejection_reason}"
            self.logger.warning(f"[{symbol}] {output.reasoning}")
            return self.success_result(data=output)
        
        # â”€â”€ Check portfolio constraints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Get sector for this symbol
        sector = self.macro_collector.get_sector_for_symbol(symbol) or "UNKNOWN"
        
        portfolio_risk_result = self.portfolio_risk_agent.run(
            symbol=symbol,
            sector=sector,
            position_value=position_sizing_data.position_value,
            portfolio_value=portfolio_value,
        )
        
        if not portfolio_risk_result.success:
            output.decision = "HOLD"
            output.reasoning = f"Portfolio risk check failed: {portfolio_risk_result.error}"
            return self.success_result(data=output)
        
        portfolio_risk_data = portfolio_risk_result.data
        
        # If portfolio constraints violated â†’ HOLD
        if not portfolio_risk_data.can_open_position:
            output.decision = "HOLD"
            output.reasoning = f"Portfolio constraint: {portfolio_risk_data.rejection_reason}"
            self.logger.warning(f"[{symbol}] {output.reasoning}")
            return self.success_result(data=output)
        
        self.logger.info(
            f"[{symbol}] Risk assessment passed | "
            f"Event multiplier: {event_risk_data.combined_multiplier:.2f}, "
            f"Position: {position_sizing_data.quantity} shares @ {price_data.current_price:.2f}"
        )
        
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        # PHASE 5: DECISION MAKING
        # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
        
        self.logger.info(f"[{symbol}] Phase 5: Decision Making")
        
        # â”€â”€ Calculate combined score â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Convert ML score (0-1) to 0-10 scale
        ml_score_scaled = ml_score * 10
        
        # Weighted average
        combined_score = (
            DECISION_TECHNICAL_WEIGHT * technical_score +
            DECISION_FUNDAMENTAL_WEIGHT * fundamental_score +
            DECISION_SENTIMENT_WEIGHT * sentiment_score +
            DECISION_ML_WEIGHT * ml_score_scaled
        )
        
        output.combined_score = combined_score
        
        # â”€â”€ Calculate confidence â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Confidence factors:
        #  1. Score distance from neutral (5.0) - higher distance = higher confidence
        #  2. Data quality score
        #  3. Event risk multiplier (low risk = higher confidence)
        
        score_distance = abs(combined_score - 5.0) / 5.0  # 0-1
        confidence = (
            0.5 * score_distance +
            0.3 * validation_result.data_quality_score +
            0.2 * event_risk_data.combined_multiplier
        )
        
        output.confidence = min(1.0, confidence)
        
        # â”€â”€ Make decision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Decision thresholds:
        #   - BUY if score â‰¥ 6.5 AND confidence â‰¥ threshold
        #   - SELL if score â‰¤ 3.5 AND confidence â‰¥ threshold
        #   - HOLD otherwise
        
        if combined_score >= 6.5 and confidence >= DECISION_CONFIDENCE_THRESHOLD:
            output.decision = "BUY"
            output.quantity = position_sizing_data.quantity
            output.entry_price = price_data.current_price
            output.stop_loss = position_sizing_data.stop_loss_price
            output.take_profit = position_sizing_data.take_profit_price
            output.position_value = position_sizing_data.position_value
            output.risk_amount = position_sizing_data.risk_amount
        
        elif combined_score <= 3.5 and confidence >= DECISION_CONFIDENCE_THRESHOLD:
            output.decision = "SELL"
            # Note: SELL is for closing existing positions, not opening shorts
            # DecisionAgent doesn't handle position closure - that's done by PositionMonitor
        
        else:
            output.decision = "HOLD"
        
        # â”€â”€ Generate reasoning â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        output.reasoning = self._generate_reasoning(
            output, event_risk_data, position_sizing_data, portfolio_risk_data
        )
        
        self.logger.info(
            f"[{symbol}] â•â•â• DECISION: {output.decision} â•â•â• | "
            f"Score: {combined_score:.2f}/10, Confidence: {confidence:.1%}"
        )
        if output.decision == "BUY":
            self.logger.info(
                f"[{symbol}] BUY {output.quantity} @ {output.entry_price:.2f} | "
                f"SL: {output.stop_loss:.2f}, TP: {output.take_profit:.2f}"
            )
        
        return self.success_result(
            data=output,
            metadata={
                "symbol": symbol,
                "decision": output.decision,
                "confidence": output.confidence,
                "combined_score": combined_score,
            }
        )
    
    # â”€â”€ Placeholder Analysis Methods (TODO: replace with real agents) â”€â”€â”€â”€â”€
    
    def _placeholder_technical_score(self, historical_data) -> float:
        """Placeholder technical score based on simple momentum."""
        try:
            # Simple momentum: 5-day return
            if "return_5d" in historical_data.columns:
                momentum = historical_data["return_5d"].iloc[-1]
                # Scale to 0-10: -10% â†’ 0, 0% â†’ 5, +10% â†’ 10
                score = 5.0 + (momentum / 10 * 5)
                return max(0.0, min(10.0, score))
            else:
                return 5.0  # Neutral
        except Exception:
            return 5.0
    
    def _placeholder_fundamental_score(self) -> float:
        """Placeholder fundamental score."""
        return 5.0  # Neutral - will be replaced by FundamentalAgent
    
    def _placeholder_sentiment_score(self, news_data) -> float:
        """Placeholder sentiment score based on news count."""
        # More news = slightly bullish bias (just a placeholder)
        if len(news_data) >= 5:
            return 6.0
        elif len(news_data) >= 2:
            return 5.5
        else:
            return 5.0
    
    def _placeholder_ml_score(self) -> float:
        """Placeholder ML score."""
        return 0.55  # Slightly bullish - will be replaced by MLAgent
    
    # â”€â”€ Reasoning Generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    
    def _generate_reasoning(
        self,
        output: DecisionOutput,
        event_risk_data,
        position_sizing_data,
        portfolio_risk_data,
    ) -> str:
        """Generates human-readable reasoning for the decision."""
        parts = []
        
        # â”€â”€ Decision header â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if output.decision == "BUY":
            parts.append(
                f"**BUY SIGNAL** | Score: {output.combined_score:.2f}/10, "
                f"Confidence: {output.confidence:.1%}"
            )
        elif output.decision == "SELL":
            parts.append(
                f"**SELL SIGNAL** | Score: {output.combined_score:.2f}/10, "
                f"Confidence: {output.confidence:.1%}"
            )
        else:
            parts.append(
                f"**HOLD** | Score: {output.combined_score:.2f}/10 (neutral), "
                f"Confidence: {output.confidence:.1%}"
            )
        
        # â”€â”€ Score breakdown â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        parts.append(
            f"Scores: Technical {output.technical_score:.1f}, "
            f"Fundamental {output.fundamental_score:.1f}, "
            f"Sentiment {output.sentiment_score:.1f}, "
            f"ML {output.ml_score:.2f}"
        )
        
        # â”€â”€ Risk factors â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if output.risk_factors:
            parts.append(f"Risk factors: {', '.join(output.risk_factors)}")
        
        # â”€â”€ Position details (if BUY) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if output.decision == "BUY":
            parts.append(
                f"Position: {output.quantity} shares @ {output.entry_price:.2f} = "
                f"{output.position_value:,.0f} "
                f"({output.position_value/portfolio_risk_data.portfolio_value*100:.1f}% of portfolio)"
            )
            parts.append(
                f"Risk management: SL {output.stop_loss:.2f}, TP {output.take_profit:.2f}, "
                f"Risk ${output.risk_amount:,.0f} "
                f"(R/R: {position_sizing_data.risk_reward_ratio:.2f})"
            )
        
        # â”€â”€ Data quality â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if output.data_quality_score < 0.8:
            parts.append(
                f"âš ï¸ Data quality: {output.data_quality_score:.2f} (below optimal)"
            )
        
        return " | ".join(parts)

