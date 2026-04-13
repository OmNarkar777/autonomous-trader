"""
data/storage/database.py
==========================
Central database manager. All SQL operations go through here.

Database: SQLite (file-based, zero-config, production-ready for this use case)
Tables:
  - trades: Permanent record of every trade decision and execution
  - portfolio: Current open positions
  - system_events: Agent activity log
  - performance_metrics: Daily trading performance summary
  - api_usage: Rate limit tracking for free tier APIs
  - price_cache: Cached price data (created by PriceCollector)
  - news_cache: Cached news articles (created by NewsCollector)
  - macro_cache: Cached macro data (created by MacroCollector)
  - earnings_events: Cached earnings calendar (created by EarningsCalendarCollector)

Transaction safety: All write operations use transactions with automatic retry on lock.
Connection pooling: Uses a simple pool to avoid "database is locked" errors.

Usage:
    from data.storage.database import DatabaseManager
    db = DatabaseManager()
    
    # Insert a trade
    trade_id = db.insert_trade(symbol="RELIANCE.NS", action="BUY", ...)
    
    # Get portfolio
    portfolio = db.get_portfolio()
    
    # Log an agent event
    db.log_event("AGENT_COMPLETE", agent_name="TechnicalAgent", ...)
"""

from __future__ import annotations

import sqlite3
import json
import threading
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from datetime import datetime, date, timezone
from typing import List, Dict, Optional, Any, Tuple
from pathlib import Path

from config.settings import settings
from config.constants import DB_POOL_SIZE, DB_POOL_TIMEOUT
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES (for type safety in CRUD operations)
# ═══════════════════════════════════════════════════════════════

@dataclass
class Trade:
    """Represents a single trade record."""
    id: Optional[int]
    symbol: str
    action: str                    # BUY | SELL | HOLD
    quantity: Optional[int]
    entry_price: Optional[float]
    exit_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    confidence_score: Optional[float]
    technical_score: Optional[float]
    fundamental_score: Optional[float]
    sentiment_score: Optional[float]
    ml_score: Optional[float]
    market_regime: Optional[str]
    decision_reasoning: Optional[str]  # JSON string
    order_id: Optional[str]
    status: str                        # PENDING | OPEN | CLOSED | CANCELLED | FAILED
    pnl: Optional[float]
    created_at: datetime
    executed_at: Optional[datetime]
    closed_at: Optional[datetime]


@dataclass
class Position:
    """Represents a currently open portfolio position."""
    symbol: str
    quantity: int
    avg_entry_price: float
    current_price: float
    unrealized_pnl: float
    stop_loss: float
    take_profit: float
    trade_id: int
    opened_at: datetime
    last_updated: datetime


@dataclass
class SystemEvent:
    """Represents a logged system/agent event."""
    id: Optional[int]
    event_type: str
    agent_name: Optional[str]
    symbol: Optional[str]
    message: str
    data: Optional[Dict]
    severity: str
    created_at: datetime


@dataclass
class PerformanceMetrics:
    """Daily performance summary."""
    date: date
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_pnl: float
    max_drawdown: float
    sharpe_ratio: Optional[float]
    portfolio_value: float


# ═══════════════════════════════════════════════════════════════
# DATABASE MANAGER
# ═══════════════════════════════════════════════════════════════

class DatabaseManager:
    """
    Thread-safe SQLite database manager with connection pooling.
    
    All methods automatically retry on "database is locked" errors.
    Transactions are used for all writes to ensure ACID properties.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: Optional[str] = None):
        """Singleton pattern — only one DatabaseManager per process."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, db_path: Optional[str] = None):
        if self._initialized:
            return
        
        self._db_path = db_path or str(settings.database_path_resolved)
        self._connection_pool: List[sqlite3.Connection] = []
        self._pool_lock = threading.Lock()
        self._local = threading.local()
        
        # Ensure database directory exists
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # Initialise schema
        self._init_schema()
        self._initialized = True
        
        logger.info(f"DatabaseManager initialised: {self._db_path}")
    
    # ── Connection Management ──────────────────────────────────────────────
    
    @contextmanager
    def _get_connection(self):
        """
        Context manager for thread-safe connection pooling.
        Automatically commits on success, rolls back on error.
        """
        conn = None
        try:
            # Try to get a connection from the pool
            with self._pool_lock:
                if self._connection_pool:
                    conn = self._connection_pool.pop()
            
            # If pool is empty, create a new connection
            if conn is None:
                conn = sqlite3.connect(
                    self._db_path,
                    timeout=DB_POOL_TIMEOUT,
                    check_same_thread=False,
                )
                conn.row_factory = sqlite3.Row
                # Enable foreign keys
                conn.execute("PRAGMA foreign_keys = ON")
                # Enable WAL mode for better concurrency
                conn.execute("PRAGMA journal_mode = WAL")
            
            yield conn
            conn.commit()
        
        except Exception as e:
            if conn:
                conn.rollback()
            raise
        
        finally:
            # Return connection to pool
            if conn:
                with self._pool_lock:
                    if len(self._connection_pool) < DB_POOL_SIZE:
                        self._connection_pool.append(conn)
                    else:
                        conn.close()
    
    def _execute_with_retry(
        self,
        query: str,
        params: tuple = (),
        fetch: str = None,
        max_retries: int = 3,
    ) -> Any:
        """
        Executes a query with automatic retry on database lock.
        
        Args:
            query: SQL query string
            params: Query parameters
            fetch: "one" | "all" | "lastrowid" | None
            max_retries: Max retry attempts on lock
        
        Returns:
            Query result based on fetch parameter
        """
        for attempt in range(max_retries):
            try:
                with self._get_connection() as conn:
                    cursor = conn.execute(query, params)
                    
                    if fetch == "one":
                        return cursor.fetchone()
                    elif fetch == "all":
                        return cursor.fetchall()
                    elif fetch == "lastrowid":
                        return cursor.lastrowid
                    else:
                        return None
            
            except sqlite3.OperationalError as e:
                if "locked" in str(e).lower() and attempt < max_retries - 1:
                    import time
                    time.sleep(0.1 * (attempt + 1))  # Exponential backoff
                    continue
                else:
                    raise
    
    # ── Schema Initialisation ──────────────────────────────────────────────
    
    def _init_schema(self) -> None:
        """Creates all tables if they don't exist."""
        with self._get_connection() as conn:
            # ── Trades table ───────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('BUY', 'SELL', 'HOLD')),
                    quantity INTEGER,
                    entry_price REAL,
                    exit_price REAL,
                    stop_loss REAL,
                    take_profit REAL,
                    confidence_score REAL,
                    technical_score REAL,
                    fundamental_score REAL,
                    sentiment_score REAL,
                    ml_score REAL,
                    market_regime TEXT,
                    decision_reasoning TEXT,
                    order_id TEXT,
                    status TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK(status IN ('PENDING', 'OPEN', 'CLOSED', 'CANCELLED', 'FAILED')),
                    pnl REAL,
                    created_at TEXT NOT NULL,
                    executed_at TEXT,
                    closed_at TEXT
                )
            """)
            
            # Indices for fast queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_symbol
                ON trades(symbol)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_status
                ON trades(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_created
                ON trades(created_at DESC)
            """)
            
            # ── Portfolio table ────────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio (
                    symbol TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    avg_entry_price REAL NOT NULL,
                    current_price REAL NOT NULL,
                    unrealized_pnl REAL NOT NULL,
                    stop_loss REAL,
                    take_profit REAL,
                    trade_id INTEGER NOT NULL,
                    opened_at TEXT NOT NULL,
                    last_updated TEXT NOT NULL,
                    FOREIGN KEY (trade_id) REFERENCES trades(id)
                )
            """)
            
            # ── System Events table ────────────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    agent_name TEXT,
                    symbol TEXT,
                    message TEXT NOT NULL,
                    data TEXT,
                    severity TEXT NOT NULL DEFAULT 'INFO'
                        CHECK(severity IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')),
                    created_at TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_type
                ON system_events(event_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_severity
                ON system_events(severity)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_created
                ON system_events(created_at DESC)
            """)
            
            # ── Performance Metrics table ──────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS performance_metrics (
                    date TEXT PRIMARY KEY,
                    total_trades INTEGER NOT NULL DEFAULT 0,
                    winning_trades INTEGER NOT NULL DEFAULT 0,
                    losing_trades INTEGER NOT NULL DEFAULT 0,
                    win_rate REAL NOT NULL DEFAULT 0.0,
                    total_pnl REAL NOT NULL DEFAULT 0.0,
                    max_drawdown REAL NOT NULL DEFAULT 0.0,
                    sharpe_ratio REAL,
                    portfolio_value REAL NOT NULL
                )
            """)
            
            # ── API Usage Tracking table ───────────────────────────────────
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_usage (
                    api_name TEXT NOT NULL,
                    date TEXT NOT NULL,
                    calls_made INTEGER DEFAULT 0,
                    daily_limit INTEGER,
                    PRIMARY KEY (api_name, date)
                )
            """)
            
            # ── Cache tables (created by collectors, ensuring they exist) ──
            conn.execute("""
                CREATE TABLE IF NOT EXISTS price_cache (
                    symbol TEXT NOT NULL,
                    cache_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, cache_type)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_cache (
                    cache_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS macro_cache (
                    cache_key TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS earnings_events (
                    symbol TEXT NOT NULL,
                    earnings_date TEXT NOT NULL,
                    earnings_time TEXT DEFAULT 'UNKNOWN',
                    expected_eps REAL,
                    previous_eps REAL,
                    company_name TEXT,
                    source TEXT,
                    fetched_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    PRIMARY KEY (symbol, earnings_date)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS earnings_risk_cache (
                    symbol TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    cached_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                )
            """)
            
            conn.commit()
        
        logger.debug("Database schema initialised successfully")
    
    # ── CRUD: Trades ───────────────────────────────────────────────────────
    
    def insert_trade(
        self,
        symbol: str,
        action: str,
        quantity: Optional[int] = None,
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        confidence_score: Optional[float] = None,
        technical_score: Optional[float] = None,
        fundamental_score: Optional[float] = None,
        sentiment_score: Optional[float] = None,
        ml_score: Optional[float] = None,
        market_regime: Optional[str] = None,
        decision_reasoning: Optional[Dict] = None,
        status: str = "PENDING",
    ) -> int:
        """
        Inserts a new trade record. Returns the trade ID.
        This MUST be called BEFORE placing any order with the broker.
        """
        now = datetime.utcnow().isoformat()
        reasoning_json = json.dumps(decision_reasoning) if decision_reasoning else None
        
        trade_id = self._execute_with_retry("""
            INSERT INTO trades (
                symbol, action, quantity, entry_price, exit_price, stop_loss, take_profit,
                confidence_score, technical_score, fundamental_score, sentiment_score,
                ml_score, market_regime, decision_reasoning, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            symbol, action, quantity, entry_price, exit_price, stop_loss, take_profit,
            confidence_score, technical_score, fundamental_score, sentiment_score,
            ml_score, market_regime, reasoning_json, status, now
        ), fetch="lastrowid")
        
        logger.debug(f"[{symbol}] Trade inserted: ID={trade_id}, action={action}, status={status}")
        return trade_id
    
    def update_trade_status(
        self,
        trade_id: int,
        status: str,
        order_id: Optional[str] = None,
        executed_at: Optional[datetime] = None,
    ) -> None:
        """Updates trade status after order placement."""
        executed_str = executed_at.isoformat() if executed_at else None
        
        self._execute_with_retry("""
            UPDATE trades
            SET status = ?, order_id = ?, executed_at = ?
            WHERE id = ?
        """, (status, order_id, executed_str, trade_id))
        
        logger.debug(f"Trade {trade_id} status updated: {status}")
    
    def close_trade(
        self,
        trade_id: int,
        exit_price: float,
        pnl: float,
    ) -> None:
        """Marks a trade as closed with final P&L."""
        now = datetime.utcnow().isoformat()
        
        self._execute_with_retry("""
            UPDATE trades
            SET status = 'CLOSED', exit_price = ?, pnl = ?, closed_at = ?
            WHERE id = ?
        """, (exit_price, pnl, now, trade_id))
        
        logger.info(f"Trade {trade_id} closed: exit={exit_price}, P&L={pnl:+.2f}")
    
    def get_trade(self, trade_id: int) -> Optional[Trade]:
        """Retrieves a single trade by ID."""
        row = self._execute_with_retry("""
            SELECT * FROM trades WHERE id = ?
        """, (trade_id,), fetch="one")
        
        if row:
            return Trade(
                id=row["id"],
                symbol=row["symbol"],
                action=row["action"],
                quantity=row["quantity"],
                entry_price=row["entry_price"],
                exit_price=row["exit_price"],
                stop_loss=row["stop_loss"],
                take_profit=row["take_profit"],
                confidence_score=row["confidence_score"],
                technical_score=row["technical_score"],
                fundamental_score=row["fundamental_score"],
                sentiment_score=row["sentiment_score"],
                ml_score=row["ml_score"],
                market_regime=row["market_regime"],
                decision_reasoning=row["decision_reasoning"],
                order_id=row["order_id"],
                status=row["status"],
                pnl=row["pnl"],
                created_at=datetime.fromisoformat(row["created_at"]),
                executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
                closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            )
        return None
    
    def get_trades(
        self,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Trade]:
        """Retrieves multiple trades with optional filters."""
        query = "SELECT * FROM trades WHERE 1=1"
        params = []
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if status:
            query += " AND status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = self._execute_with_retry(query, tuple(params), fetch="all")
        
        trades = []
        for row in rows:
            trades.append(Trade(
                id=row["id"],
                symbol=row["symbol"],
                action=row["action"],
                quantity=row["quantity"],
                entry_price=row["entry_price"],
                exit_price=row["exit_price"],
                stop_loss=row["stop_loss"],
                take_profit=row["take_profit"],
                confidence_score=row["confidence_score"],
                technical_score=row["technical_score"],
                fundamental_score=row["fundamental_score"],
                sentiment_score=row["sentiment_score"],
                ml_score=row["ml_score"],
                market_regime=row["market_regime"],
                decision_reasoning=row["decision_reasoning"],
                order_id=row["order_id"],
                status=row["status"],
                pnl=row["pnl"],
                created_at=datetime.fromisoformat(row["created_at"]),
                executed_at=datetime.fromisoformat(row["executed_at"]) if row["executed_at"] else None,
                closed_at=datetime.fromisoformat(row["closed_at"]) if row["closed_at"] else None,
            ))
        
        return trades
    
    def get_open_trades(self) -> List[Trade]:
        """Returns all trades with status=OPEN."""
        return self.get_trades(status="OPEN", limit=1000)
    
    # ── CRUD: Portfolio ────────────────────────────────────────────────────
    
    def upsert_position(
        self,
        symbol: str,
        quantity: int,
        avg_entry_price: float,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        trade_id: int,
    ) -> None:
        """Inserts or updates a position in the portfolio."""
        now = datetime.utcnow().isoformat()
        unrealized_pnl = (current_price - avg_entry_price) * quantity
        
        self._execute_with_retry("""
            INSERT INTO portfolio (
                symbol, quantity, avg_entry_price, current_price, unrealized_pnl,
                stop_loss, take_profit, trade_id, opened_at, last_updated
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                quantity = excluded.quantity,
                avg_entry_price = excluded.avg_entry_price,
                current_price = excluded.current_price,
                unrealized_pnl = excluded.unrealized_pnl,
                stop_loss = excluded.stop_loss,
                take_profit = excluded.take_profit,
                last_updated = excluded.last_updated
        """, (
            symbol, quantity, avg_entry_price, current_price, unrealized_pnl,
            stop_loss, take_profit, trade_id, now, now
        ))
        
        logger.debug(f"[{symbol}] Position upserted: qty={quantity}, entry={avg_entry_price}")
    
    def update_position_price(self, symbol: str, current_price: float) -> None:
        """Updates the current price and unrealized P&L for a position."""
        now = datetime.utcnow().isoformat()
        
        self._execute_with_retry("""
            UPDATE portfolio
            SET current_price = ?,
                unrealized_pnl = (? - avg_entry_price) * quantity,
                last_updated = ?
            WHERE symbol = ?
        """, (current_price, current_price, now, symbol))
    
    def remove_position(self, symbol: str) -> None:
        """Removes a position from the portfolio (when closed)."""
        self._execute_with_retry("""
            DELETE FROM portfolio WHERE symbol = ?
        """, (symbol,))
        
        logger.info(f"[{symbol}] Position removed from portfolio")
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """Retrieves a single portfolio position."""
        row = self._execute_with_retry("""
            SELECT * FROM portfolio WHERE symbol = ?
        """, (symbol,), fetch="one")
        
        if row:
            return Position(
                symbol=row["symbol"],
                quantity=row["quantity"],
                avg_entry_price=row["avg_entry_price"],
                current_price=row["current_price"],
                unrealized_pnl=row["unrealized_pnl"],
                stop_loss=row["stop_loss"],
                take_profit=row["take_profit"],
                trade_id=row["trade_id"],
                opened_at=datetime.fromisoformat(row["opened_at"]),
                last_updated=datetime.fromisoformat(row["last_updated"]),
            )
        return None
    
    def get_portfolio(self) -> List[Position]:
        """Returns all current positions."""
        rows = self._execute_with_retry("""
            SELECT * FROM portfolio ORDER BY symbol
        """, fetch="all")
        
        positions = []
        for row in rows:
            positions.append(Position(
                symbol=row["symbol"],
                quantity=row["quantity"],
                avg_entry_price=row["avg_entry_price"],
                current_price=row["current_price"],
                unrealized_pnl=row["unrealized_pnl"],
                stop_loss=row["stop_loss"],
                take_profit=row["take_profit"],
                trade_id=row["trade_id"],
                opened_at=datetime.fromisoformat(row["opened_at"]),
                last_updated=datetime.fromisoformat(row["last_updated"]),
            ))
        
        return positions
    
    def get_portfolio_value(self) -> float:
        """Calculates total portfolio value (all positions at current prices)."""
        row = self._execute_with_retry("""
            SELECT SUM(current_price * quantity) as total_value
            FROM portfolio
        """, fetch="one")
        
        return row["total_value"] or 0.0
    
    # ── CRUD: System Events ────────────────────────────────────────────────
    
    def log_event(
        self,
        event_type: str,
        message: str,
        agent_name: Optional[str] = None,
        symbol: Optional[str] = None,
        data: Optional[Dict] = None,
        severity: str = "INFO",
    ) -> int:
        """Logs a system event (agent activity, errors, etc.)."""
        now = datetime.utcnow().isoformat()
        data_json = json.dumps(data) if data else None
        
        event_id = self._execute_with_retry("""
            INSERT INTO system_events (
                event_type, agent_name, symbol, message, data, severity, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (event_type, agent_name, symbol, message, data_json, severity, now),
        fetch="lastrowid")
        
        return event_id
    
    def get_recent_events(
        self,
        limit: int = 100,
        severity: Optional[str] = None,
        event_type: Optional[str] = None,
    ) -> List[SystemEvent]:
        """Retrieves recent system events with optional filters."""
        query = "SELECT * FROM system_events WHERE 1=1"
        params = []
        
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        
        rows = self._execute_with_retry(query, tuple(params), fetch="all")
        
        events = []
        for row in rows:
            data_dict = json.loads(row["data"]) if row["data"] else None
            events.append(SystemEvent(
                id=row["id"],
                event_type=row["event_type"],
                agent_name=row["agent_name"],
                symbol=row["symbol"],
                message=row["message"],
                data=data_dict,
                severity=row["severity"],
                created_at=datetime.fromisoformat(row["created_at"]),
            ))
        
        return events
    
    # ── CRUD: Performance Metrics ──────────────────────────────────────────
    
    def update_daily_metrics(
        self,
        date: date,
        total_trades: int,
        winning_trades: int,
        losing_trades: int,
        total_pnl: float,
        max_drawdown: float,
        portfolio_value: float,
        sharpe_ratio: Optional[float] = None,
    ) -> None:
        """Updates or inserts daily performance metrics."""
        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0
        date_str = date.isoformat()
        
        self._execute_with_retry("""
            INSERT INTO performance_metrics (
                date, total_trades, winning_trades, losing_trades, win_rate,
                total_pnl, max_drawdown, sharpe_ratio, portfolio_value
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                total_trades = excluded.total_trades,
                winning_trades = excluded.winning_trades,
                losing_trades = excluded.losing_trades,
                win_rate = excluded.win_rate,
                total_pnl = excluded.total_pnl,
                max_drawdown = excluded.max_drawdown,
                sharpe_ratio = excluded.sharpe_ratio,
                portfolio_value = excluded.portfolio_value
        """, (
            date_str, total_trades, winning_trades, losing_trades, win_rate,
            total_pnl, max_drawdown, sharpe_ratio, portfolio_value
        ))
        
        logger.debug(f"Daily metrics updated for {date_str}: "
                     f"{total_trades} trades, P&L={total_pnl:+.2f}, WR={win_rate:.1%}")
    
    def get_metrics(self, days_back: int = 30) -> List[PerformanceMetrics]:
        """Retrieves performance metrics for the last N days."""
        from_date = (date.today() - timedelta(days=days_back)).isoformat()
        
        rows = self._execute_with_retry("""
            SELECT * FROM performance_metrics
            WHERE date >= ?
            ORDER BY date DESC
        """, (from_date,), fetch="all")
        
        metrics = []
        for row in rows:
            metrics.append(PerformanceMetrics(
                date=date.fromisoformat(row["date"]),
                total_trades=row["total_trades"],
                winning_trades=row["winning_trades"],
                losing_trades=row["losing_trades"],
                win_rate=row["win_rate"],
                total_pnl=row["total_pnl"],
                max_drawdown=row["max_drawdown"],
                sharpe_ratio=row["sharpe_ratio"],
                portfolio_value=row["portfolio_value"],
            ))
        
        return metrics
    
    # ── Utility Methods ────────────────────────────────────────────────────
    
    def get_total_trade_count(self) -> int:
        """Returns total number of trades ever executed."""
        row = self._execute_with_retry("""
            SELECT COUNT(*) as count FROM trades
        """, fetch="one")
        return row["count"]
    
    def get_paper_trading_stats(self) -> Dict[str, Any]:
        """
        Returns paper trading performance stats.
        Used to determine if system is ready for live trading.
        """
        total = self.get_total_trade_count()
        
        row = self._execute_with_retry("""
            SELECT
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl > 0) as wins,
                COUNT(*) FILTER (WHERE status = 'CLOSED' AND pnl < 0) as losses,
                SUM(pnl) FILTER (WHERE status = 'CLOSED') as total_pnl
            FROM trades
        """, fetch="one")
        
        wins = row["wins"] or 0
        losses = row["losses"] or 0
        closed = wins + losses
        win_rate = wins / closed if closed > 0 else 0.0
        
        return {
            "total_trades": total,
            "closed_trades": closed,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": win_rate,
            "total_pnl": row["total_pnl"] or 0.0,
        }
    
    def cleanup_old_cache(self, days: int = 7) -> int:
        """Removes expired cache entries older than N days."""
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        tables = ["price_cache", "news_cache", "macro_cache", "earnings_risk_cache"]
        total_deleted = 0
        
        for table in tables:
            try:
                deleted = self._execute_with_retry(f"""
                    DELETE FROM {table} WHERE expires_at < ?
                """, (cutoff,))
                logger.debug(f"Cleaned {table}: removed entries older than {days} days")
            except Exception as e:
                logger.warning(f"Cache cleanup failed for {table}: {e}")
        
        logger.info(f"Cache cleanup complete: {total_deleted} entries removed")
        return total_deleted
