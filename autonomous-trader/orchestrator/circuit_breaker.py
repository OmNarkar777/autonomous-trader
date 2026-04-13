"""
orchestrator/circuit_breaker.py
=================================
Circuit Breaker pattern for trading system safety.

When things go wrong, the circuit breaker prevents cascading failures
by halting trading until the issue is resolved.

States:
  - CLOSED: Normal operation
  - OPEN: Trading halted due to errors
  - HALF_OPEN: Testing if system has recovered

Triggers:
  - N consecutive errors (default: 5)
  - Critical errors (API failures, broker errors)
  - Manual trigger via admin interface

Recovery:
  - After timeout, enters HALF_OPEN
  - If next attempt succeeds, returns to CLOSED
  - If next attempt fails, returns to OPEN

Usage:
    from orchestrator.circuit_breaker import CircuitBreaker
    breaker = CircuitBreaker()
    
    if breaker.is_open():
        print("Trading halted!")
    else:
        # Execute trade
        try:
            trade()
            breaker.record_success()
        except Exception as e:
            breaker.record_failure(str(e))
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# ENUMS AND DATA CLASSES
# ═══════════════════════════════════════════════════════════════

class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "CLOSED"        # Normal operation
    OPEN = "OPEN"            # Trading halted
    HALF_OPEN = "HALF_OPEN"  # Testing recovery


@dataclass
class CircuitBreakerStatus:
    """Circuit breaker status information."""
    state: str
    failure_count: int
    last_failure_time: Optional[datetime]
    opened_at: Optional[datetime]
    reason: str


# ═══════════════════════════════════════════════════════════════
# CIRCUIT BREAKER
# ═══════════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    Circuit breaker for trading system safety.
    
    Prevents cascading failures by halting trading when
    too many errors occur.
    """
    
    def __init__(
        self,
        error_threshold: int = 5,
        timeout_seconds: int = 300,  # 5 minutes
    ):
        """
        Initializes the circuit breaker.
        
        Args:
            error_threshold: Number of consecutive failures before opening
            timeout_seconds: How long to wait before attempting recovery
        """
        self.error_threshold = error_threshold
        self.timeout_seconds = timeout_seconds
        
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._opened_at: Optional[datetime] = None
        self._open_reason = ""
    
    # ── State Checks ───────────────────────────────────────────────────────
    
    def is_open(self) -> bool:
        """Returns True if circuit is open (trading halted)."""
        if self._state == CircuitState.OPEN:
            # Check if timeout has elapsed
            if self._should_attempt_recovery():
                self._state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker: OPEN → HALF_OPEN (attempting recovery)")
                return False
            return True
        
        return False
    
    def is_closed(self) -> bool:
        """Returns True if circuit is closed (normal operation)."""
        return self._state == CircuitState.CLOSED
    
    def is_half_open(self) -> bool:
        """Returns True if circuit is half-open (testing recovery)."""
        return self._state == CircuitState.HALF_OPEN
    
    # ── State Transitions ──────────────────────────────────────────────────
    
    def record_success(self) -> None:
        """Records a successful operation."""
        if self._state == CircuitState.HALF_OPEN:
            # Recovery successful
            self._close_circuit()
        
        # Reset failure counter
        self._failure_count = 0
        self._last_failure_time = None
    
    def record_failure(self, reason: str) -> None:
        """Records a failed operation."""
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()
        
        logger.warning(
            f"Circuit breaker: Failure recorded ({self._failure_count}/{self.error_threshold}) | "
            f"Reason: {reason}"
        )
        
        if self._state == CircuitState.HALF_OPEN:
            # Recovery failed, reopen circuit
            self._open_circuit(reason="Recovery attempt failed")
        
        elif self._failure_count >= self.error_threshold:
            # Threshold reached, open circuit
            self._open_circuit(reason=f"Error threshold reached: {reason}")
    
    def open_circuit(self, reason: str) -> None:
        """Manually opens the circuit."""
        self._open_circuit(reason=reason)
    
    def close_circuit(self) -> None:
        """Manually closes the circuit."""
        self._close_circuit()
    
    def reset(self) -> None:
        """Resets the circuit breaker to initial state."""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = None
        self._opened_at = None
        self._open_reason = ""
        logger.info("Circuit breaker: RESET")
    
    # ── Internal State Management ──────────────────────────────────────────
    
    def _open_circuit(self, reason: str) -> None:
        """Opens the circuit (halts trading)."""
        if self._state != CircuitState.OPEN:
            self._state = CircuitState.OPEN
            self._opened_at = datetime.utcnow()
            self._open_reason = reason
            
            logger.error(
                f"⚠️ CIRCUIT BREAKER OPENED ⚠️ | Reason: {reason} | "
                f"Trading halted for {self.timeout_seconds}s"
            )
    
    def _close_circuit(self) -> None:
        """Closes the circuit (resumes trading)."""
        if self._state != CircuitState.CLOSED:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._open_reason = ""
            
            logger.info("✓ Circuit breaker: CLOSED (trading resumed)")
    
    def _should_attempt_recovery(self) -> bool:
        """Checks if enough time has passed to attempt recovery."""
        if not self._opened_at:
            return False
        
        elapsed = (datetime.utcnow() - self._opened_at).total_seconds()
        return elapsed >= self.timeout_seconds
    
    # ── Status ─────────────────────────────────────────────────────────────
    
    def get_status(self) -> CircuitBreakerStatus:
        """Returns current circuit breaker status."""
        return CircuitBreakerStatus(
            state=self._state.value,
            failure_count=self._failure_count,
            last_failure_time=self._last_failure_time,
            opened_at=self._opened_at,
            reason=self._open_reason,
        )
