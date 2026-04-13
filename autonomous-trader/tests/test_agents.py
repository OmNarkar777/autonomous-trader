"""
tests/test_agents.py
====================
Tests for base agent and data agents.
"""

import pytest
from datetime import datetime

from agents.base_agent import BaseAgent, AgentResult
from agents.data_agents.price_agent import PriceAgent
from agents.data_agents.news_agent import NewsAgent
from agents.data_agents.macro_agent import MacroAgent
from agents.data_agents.earnings_agent import EarningsAgent


class TestBaseAgent:
    """Tests for BaseAgent."""
    
    def test_agent_initialization(self):
        """Test base agent initialization."""
        
        class TestAgent(BaseAgent):
            def execute(self, **kwargs):
                return self.success_result(data="test")
        
        agent = TestAgent()
        assert agent.agent_name == "TestAgent"
        assert agent._execution_count == 0
    
    def test_agent_run_wrapper(self):
        """Test that run() wrapper adds execution timing."""
        
        class TestAgent(BaseAgent):
            def execute(self, **kwargs):
                return self.success_result(data="test")
        
        agent = TestAgent()
        result = agent.run()
        
        assert result.success is True
        assert result.execution_time_ms > 0
        assert agent._execution_count == 1
    
    def test_agent_error_handling(self):
        """Test that run() catches exceptions."""
        
        class TestAgent(BaseAgent):
            def execute(self, **kwargs):
                raise ValueError("Test error")
        
        agent = TestAgent()
        result = agent.run()
        
        assert result.success is False
        assert "Test error" in result.error
    
    def test_agent_stats(self):
        """Test agent statistics tracking."""
        
        class TestAgent(BaseAgent):
            def execute(self, **kwargs):
                return self.success_result(data="test")
        
        agent = TestAgent()
        
        # Run multiple times
        for _ in range(3):
            agent.run()
        
        stats = agent.get_stats()
        assert stats["execution_count"] == 3
        assert stats["last_execution_time"] is not None


class TestPriceAgent:
    """Tests for PriceAgent."""
    
    @pytest.fixture
    def agent(self):
        return PriceAgent()
    
    def test_price_agent_success(self, agent):
        """Test successful price data fetch."""
        result = agent.run(symbol="AAPL")
        
        assert result.success is True
        assert result.data is not None
        assert result.data.symbol == "AAPL"
        assert result.data.current_price is not None
        assert result.data.historical_data is not None
    
    def test_price_agent_validation(self, agent):
        """Test that price agent validates data."""
        result = agent.run(symbol="AAPL")
        
        if result.success:
            assert result.data.is_valid is True
            assert result.data.validation_issues is not None
    
    def test_price_agent_invalid_symbol(self, agent):
        """Test handling of invalid symbol."""
        result = agent.run(symbol="INVALID_SYMBOL_99999")
        
        # Should fail gracefully
        assert result.success is False
        assert result.error is not None


class TestNewsAgent:
    """Tests for NewsAgent."""
    
    @pytest.fixture
    def agent(self):
        return NewsAgent()
    
    def test_news_agent_success(self, agent):
        """Test successful news fetch."""
        result = agent.run(
            symbol="AAPL",
            company_name="Apple Inc",
            hours_back=48
        )
        
        assert result.success is True
        assert result.data is not None
        assert result.data.symbol == "AAPL"
        assert isinstance(result.data.articles, list)
    
    def test_news_agent_quality_score(self, agent):
        """Test news quality scoring."""
        result = agent.run(
            symbol="TSLA",
            company_name="Tesla",
            hours_back=24
        )
        
        if result.success:
            assert 0 <= result.data.quality_score <= 1
    
    def test_news_agent_empty_results(self, agent):
        """Test handling of no news found."""
        result = agent.run(
            symbol="OBSCURE_SYMBOL",
            company_name="Unknown Company",
            hours_back=1
        )
        
        # Should succeed even with no news
        if result.success:
            assert result.data.article_count >= 0


class TestMacroAgent:
    """Tests for MacroAgent."""
    
    @pytest.fixture
    def agent(self):
        return MacroAgent()
    
    def test_macro_agent_success(self, agent):
        """Test successful macro data fetch."""
        result = agent.run()
        
        assert result.success is True
        assert result.data is not None
        assert result.data.regime is not None
        assert result.data.regime in ["STRONG_BULL", "BULL", "NEUTRAL", "BEAR", "STRONG_BEAR"]
    
    def test_macro_agent_multiplier(self, agent):
        """Test regime multiplier is valid."""
        result = agent.run()
        
        if result.success:
            assert 0 <= result.data.regime_position_multiplier <= 1
    
    def test_macro_agent_sector_rotation(self, agent):
        """Test sector rotation signals."""
        result = agent.run()
        
        if result.success:
            assert isinstance(result.data.sector_rotation, dict)


class TestEarningsAgent:
    """Tests for EarningsAgent."""
    
    @pytest.fixture
    def agent(self):
        return EarningsAgent()
    
    def test_earnings_agent_success(self, agent):
        """Test successful earnings check."""
        result = agent.run(symbol="AAPL")
        
        assert result.success is True
        assert result.data is not None
        assert result.data.symbol == "AAPL"
        assert result.data.risk_level in ["NONE", "LOW", "HIGH", "BLOCK"]
    
    def test_earnings_agent_multiplier(self, agent):
        """Test position size multiplier is valid."""
        result = agent.run(symbol="TSLA")
        
        if result.success:
            assert 0 <= result.data.position_size_multiplier <= 1
    
    def test_earnings_agent_blocking(self, agent):
        """Test blocking detection."""
        result = agent.run(symbol="GOOGL")
        
        if result.success:
            blocks = result.data.blocks_trading()
            assert isinstance(blocks, bool)
            
            if blocks:
                # If blocking, multiplier should be 0
                assert result.data.position_size_multiplier == 0.0
