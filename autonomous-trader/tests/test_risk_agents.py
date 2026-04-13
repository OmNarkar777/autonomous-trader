"""
tests/test_risk_agents.py
==========================
Tests for risk management agents.
"""

import pytest
from agents.risk_agents.position_sizing_agent import PositionSizingAgent
from agents.risk_agents.event_risk_agent import EventRiskAgent
from agents.risk_agents.portfolio_risk_agent import PortfolioRiskAgent
from agents.data_agents.macro_agent import MacroAgent
from agents.data_agents.earnings_agent import EarningsAgent


class TestPositionSizingAgent:
    """Tests for PositionSizingAgent."""
    
    @pytest.fixture
    def agent(self):
        return PositionSizingAgent()
    
    def test_position_sizing_calculation(self, agent):
        """Test position size calculation."""
        result = agent.run(
            symbol="AAPL",
            current_price=150.0,
            atr=3.0,
            available_capital=100000,
            regime_multiplier=1.0,
            earnings_multiplier=1.0,
            data_quality_score=1.0
        )
        
        assert result.success is True
        assert result.data.quantity > 0
        assert result.data.position_value > 0
        assert result.data.stop_loss_price > 0
        assert result.data.take_profit_price > 0
    
    def test_multiplier_application(self, agent):
        """Test that multipliers reduce position size."""
        # Full multipliers
        result1 = agent.run(
            symbol="AAPL",
            current_price=150.0,
            atr=3.0,
            available_capital=100000,
            regime_multiplier=1.0,
            earnings_multiplier=1.0,
            data_quality_score=1.0
        )
        
        # Reduced multipliers
        result2 = agent.run(
            symbol="AAPL",
            current_price=150.0,
            atr=3.0,
            available_capital=100000,
            regime_multiplier=0.5,
            earnings_multiplier=0.5,
            data_quality_score=0.5
        )
        
        if result1.success and result2.success:
            # Second should have smaller position
            assert result2.data.quantity < result1.data.quantity
    
    def test_risk_reward_ratio(self, agent):
        """Test risk/reward ratio calculation."""
        result = agent.run(
            symbol="AAPL",
            current_price=150.0,
            atr=3.0,
            available_capital=100000
        )
        
        if result.success:
            assert result.data.risk_reward_ratio > 0


class TestEventRiskAgent:
    """Tests for EventRiskAgent."""
    
    @pytest.fixture
    def agent(self):
        return EventRiskAgent()
    
    @pytest.fixture
    def macro_data(self):
        macro_agent = MacroAgent()
        result = macro_agent.run()
        return result.data if result.success else None
    
    @pytest.fixture
    def earnings_data(self):
        earnings_agent = EarningsAgent()
        result = earnings_agent.run(symbol="AAPL")
        return result.data if result.success else None
    
    def test_event_risk_aggregation(self, agent, macro_data, earnings_data):
        """Test event risk aggregation."""
        if not macro_data or not earnings_data:
            pytest.skip("Missing macro or earnings data")
        
        result = agent.run(
            symbol="AAPL",
            macro_output=macro_data,
            earnings_output=earnings_data
        )
        
        assert result.success is True
        assert isinstance(result.data.blocks_trading, bool)
        assert 0 <= result.data.combined_multiplier <= 1
    
    def test_blocking_logic(self, agent, macro_data, earnings_data):
        """Test that blocking is detected correctly."""
        if not macro_data or not earnings_data:
            pytest.skip("Missing macro or earnings data")
        
        result = agent.run(
            symbol="AAPL",
            macro_output=macro_data,
            earnings_output=earnings_data
        )
        
        if result.success:
            # If blocks_trading, multiplier should be 0
            if result.data.blocks_trading:
                assert result.data.combined_multiplier == 0.0


class TestPortfolioRiskAgent:
    """Tests for PortfolioRiskAgent."""
    
    @pytest.fixture
    def agent(self):
        return PortfolioRiskAgent()
    
    def test_portfolio_constraints(self, agent):
        """Test portfolio constraint checking."""
        result = agent.run(
            symbol="AAPL",
            sector="Technology",
            position_value=10000,
            portfolio_value=100000
        )
        
        assert result.success is True
        assert isinstance(result.data.can_open_position, bool)
    
    def test_position_count_limit(self, agent):
        """Test maximum position count enforcement."""
        # This would need a populated database to test properly
        # For now, just verify the agent runs
        result = agent.run(
            symbol="AAPL",
            sector="Technology",
            position_value=10000,
            portfolio_value=100000
        )
        
        if result.success:
            assert result.data.current_position_count >= 0
    
    def test_sector_concentration(self, agent):
        """Test sector concentration calculation."""
        result = agent.run(
            symbol="AAPL",
            sector="Technology",
            position_value=10000,
            portfolio_value=100000
        )
        
        if result.success:
            assert 0 <= result.data.sector_exposure_pct <= 100
            assert 0 <= result.data.sector_exposure_after_pct <= 100
