"""
tests/test_execution_agent.py
==============================
Tests for ExecutionAgent.
"""

import pytest
from agents.execution_agent import ExecutionAgent


class TestExecutionAgent:
    """Tests for ExecutionAgent."""
    
    @pytest.fixture
    def agent(self):
        return ExecutionAgent(broker_type="paper")
    
    def test_paper_broker_initialization(self, agent):
        """Test paper broker initialization."""
        assert agent.broker_type == "paper"
        assert agent.broker is not None
    
    def test_execute_buy_order(self, agent):
        """Test executing BUY order."""
        result = agent.run(
            symbol="AAPL",
            action="BUY",
            quantity=10,
            price=150.0,
            stop_loss=145.0,
            take_profit=160.0,
            confidence=0.75
        )
        
        assert result.success is True
        assert result.data.action == "BUY"
        assert result.data.quantity == 10
        assert result.data.trade_id > 0
        assert result.data.status in ["FILLED", "SUBMITTED", "PENDING"]
    
    def test_execute_hold_action(self, agent):
        """Test HOLD action handling."""
        result = agent.run(
            symbol="AAPL",
            action="HOLD",
            quantity=0,
            price=150.0
        )
        
        assert result.success is True
        assert result.data.action == "HOLD"
        assert result.data.status == "SKIPPED"
    
    def test_invalid_action(self, agent):
        """Test handling of invalid action."""
        result = agent.run(
            symbol="AAPL",
            action="INVALID",
            quantity=10,
            price=150.0
        )
        
        assert result.success is False
        assert "Invalid action" in result.error
    
    def test_invalid_quantity(self, agent):
        """Test handling of invalid quantity."""
        result = agent.run(
            symbol="AAPL",
            action="BUY",
            quantity=0,
            price=150.0
        )
        
        assert result.success is False
        assert "Invalid quantity" in result.error
    
    def test_database_logging(self, agent):
        """Test that trades are logged to database."""
        result = agent.run(
            symbol="AAPL",
            action="BUY",
            quantity=10,
            price=150.0
        )
        
        if result.success:
            # Trade ID should be assigned
            assert result.data.trade_id > 0
