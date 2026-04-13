"""
agents/base_agent.py
=====================
Base agent class that all agents inherit from.

Provides common functionality:
  - Logging with agent name
  - Timing execution
  - Result formatting
  - Error handling
  - State management

All agents return AgentResult dataclass with:
  - success: bool
  - data: Any (agent-specific output)
  - error: Optional[str]
  - execution_time_ms: float
  - metadata: Dict (agent-specific)

Usage:
    class MyAgent(BaseAgent):
        def execute(self, **kwargs):
            # Your logic here
            return self.success_result(data=result)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional, Dict

from config.logging_config import get_logger


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES
# ═══════════════════════════════════════════════════════════════

@dataclass
class AgentResult:
    """
    Standard result format for all agents.
    
    This ensures consistency across the agent system and makes it
    easy to track what happened in each agent execution.
    """
    agent_name: str
    success: bool
    data: Any = None
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts result to dictionary for serialization."""
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        return d


# ═══════════════════════════════════════════════════════════════
# BASE AGENT
# ═══════════════════════════════════════════════════════════════

class BaseAgent(ABC):
    """
    Abstract base class for all agents.
    
    Provides:
      - Consistent logging
      - Execution timing
      - Result formatting
      - Error handling wrapper
    
    All agents must implement execute() method.
    """
    
    def __init__(self, agent_name: Optional[str] = None):
        """
        Initialises the base agent.
        
        Args:
            agent_name: Name for this agent (defaults to class name)
        """
        self.agent_name = agent_name or self.__class__.__name__
        self.logger = get_logger(f"agents.{self.agent_name}")
        self._execution_count = 0
        self._last_execution_time = None
    
    # ── Abstract Methods ───────────────────────────────────────────────────
    
    @abstractmethod
    def execute(self, **kwargs) -> AgentResult:
        """
        Main execution method - must be implemented by subclasses.
        
        Args:
            **kwargs: Agent-specific parameters
        
        Returns:
            AgentResult with success status and data
        """
        pass
    
    # ── Execution Wrapper ──────────────────────────────────────────────────
    
    def run(self, **kwargs) -> AgentResult:
        """
        Wraps execute() with timing and error handling.
        
        This is the method that should be called to run an agent.
        It automatically:
          - Times the execution
          - Catches and logs errors
          - Increments execution counter
          - Updates last execution time
        
        Args:
            **kwargs: Passed to execute()
        
        Returns:
            AgentResult from execute() or error result if exception
        """
        start_time = time.time()
        self._execution_count += 1
        
        try:
            self.logger.debug(f"Starting execution #{self._execution_count}")
            
            # Call the agent's execute method
            result = self.execute(**kwargs)
            
            # Add execution time
            execution_time_ms = (time.time() - start_time) * 1000
            result.execution_time_ms = execution_time_ms
            
            # Update stats
            self._last_execution_time = datetime.now(timezone.utc)
            
            if result.success:
                self.logger.info(
                    f"Execution #{self._execution_count} completed successfully "
                    f"in {execution_time_ms:.1f}ms"
                )
            else:
                self.logger.warning(
                    f"Execution #{self._execution_count} completed with failure: "
                    f"{result.error}"
                )
            
            return result
        
        except Exception as e:
            execution_time_ms = (time.time() - start_time) * 1000
            
            self.logger.error(
                f"Execution #{self._execution_count} crashed: {e}",
                exc_info=True
            )
            
            return AgentResult(
                agent_name=self.agent_name,
                success=False,
                error=f"Agent crashed: {str(e)}",
                execution_time_ms=execution_time_ms,
            )
    
    # ── Result Helpers ─────────────────────────────────────────────────────
    
    def success_result(
        self,
        data: Any,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Creates a success result.
        
        Args:
            data: The successful output data
            metadata: Optional metadata about the execution
        
        Returns:
            AgentResult with success=True
        """
        return AgentResult(
            agent_name=self.agent_name,
            success=True,
            data=data,
            metadata=metadata or {},
        )
    
    def failure_result(
        self,
        error: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AgentResult:
        """
        Creates a failure result.
        
        Args:
            error: Error message explaining the failure
            metadata: Optional metadata about the failure
        
        Returns:
            AgentResult with success=False
        """
        return AgentResult(
            agent_name=self.agent_name,
            success=False,
            error=error,
            metadata=metadata or {},
        )
    
    # ── Agent Stats ────────────────────────────────────────────────────────
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Returns statistics about this agent's execution history.
        
        Returns:
            Dict with execution count, last run time, etc.
        """
        return {
            "agent_name": self.agent_name,
            "execution_count": self._execution_count,
            "last_execution_time": (
                self._last_execution_time.isoformat()
                if self._last_execution_time else None
            ),
        }
    
    def reset_stats(self) -> None:
        """Resets execution statistics."""
        self._execution_count = 0
        self._last_execution_time = None
        self.logger.debug("Agent statistics reset")
    
    # ── String Representation ──────────────────────────────────────────────
    
    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(name='{self.agent_name}', "
            f"executions={self._execution_count})"
        )
