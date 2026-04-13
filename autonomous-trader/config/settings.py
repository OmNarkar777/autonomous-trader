"""
config/settings.py
==================
Central configuration module. Loads all settings from the .env file,
validates types, and provides a single Settings object used across the system.

Usage:
    from config.settings import settings
    print(settings.GROQ_API_KEY)
    print(settings.MAX_CAPITAL_PER_TRADE_PERCENT)
"""

import os
from pathlib import Path
from typing import List, Literal, Optional
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ── Base directory (project root) ───────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """
    All system configuration loaded from environment variables / .env file.
    Each field includes a description and validation.
    If a required field is missing, Pydantic will raise a clear error
    telling you exactly which variable to add to your .env file.
    """

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",   # Silently ignore unrecognised env vars
    )

    # ── LLM ────────────────────────────────────────────────────────────────
    GROQ_API_KEY: str = Field(
        ...,
        description="Groq API key. Get free at https://console.groq.com",
    )
    GROQ_MODEL: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model to use. llama-3.3-70b-versatile is free and powerful.",
    )
    GROQ_MAX_TOKENS: int = Field(
        default=1024,
        description="Max tokens per Groq API call. Keep low to conserve free tier quota.",
    )
    # Daily Groq request budget — free tier allows 14,400/day
    GROQ_DAILY_REQUEST_LIMIT: int = Field(
        default=12000,
        description="Safety cap on daily Groq requests (below the 14,400 free limit).",
    )

    # ── News APIs ───────────────────────────────────────────────────────────
    NEWSAPI_KEY: Optional[str] = Field(
        default=None,
        description="NewsAPI key (100 req/day free). Get at https://newsapi.org",
    )
    GNEWS_API_KEY: Optional[str] = Field(
        default=None,
        description="GNews API key (100 req/day free). Get at https://gnews.io",
    )

    # ── Reddit ──────────────────────────────────────────────────────────────
    REDDIT_CLIENT_ID: Optional[str] = Field(default=None)
    REDDIT_CLIENT_SECRET: Optional[str] = Field(default=None)
    REDDIT_USER_AGENT: str = Field(
        default="AutonomousTrader/1.0",
        description="Reddit app user agent string.",
    )

    # ── Alpha Vantage ───────────────────────────────────────────────────────
    ALPHA_VANTAGE_KEY: Optional[str] = Field(
        default=None,
        description="Alpha Vantage key (25 req/day free). Used as price data fallback.",
    )

    # ── Zerodha (India) ─────────────────────────────────────────────────────
    ZERODHA_API_KEY: Optional[str] = Field(default=None)
    ZERODHA_API_SECRET: Optional[str] = Field(default=None)
    ZERODHA_USER_ID: Optional[str] = Field(default=None)
    ZERODHA_ACCESS_TOKEN: Optional[str] = Field(
        default=None,
        description="Refreshed daily. Leave blank on first run.",
    )

    # ── Alpaca (US) ─────────────────────────────────────────────────────────
    ALPACA_API_KEY: Optional[str] = Field(default=None)
    ALPACA_SECRET_KEY: Optional[str] = Field(default=None)
    ALPACA_BASE_URL: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Use paper URL for testing. Switch to live URL only after 100+ paper trades.",
    )

    # ── Notifications ───────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None)
    TELEGRAM_CHAT_ID: Optional[str] = Field(default=None)
    EMAIL_SENDER: Optional[str] = Field(default=None)
    EMAIL_PASSWORD: Optional[str] = Field(default=None)
    EMAIL_RECIPIENT: Optional[str] = Field(default=None)

    # ── Trading Configuration ────────────────────────────────────────────────
    TRADING_MODE: Literal["paper", "live"] = Field(
        default="paper",
        description="'paper' = fake money safe testing. 'live' = real money. ALWAYS start with paper.",
    )
    TARGET_MARKET: Literal["india", "us", "both"] = Field(
        default="india",
        description="Which market to trade: india (NSE), us (NYSE/NASDAQ), or both.",
    )
    TRADING_STYLE: Literal["intraday", "swing"] = Field(
        default="swing",
        description="'intraday' = close all positions by market close. 'swing' = hold 3-7 days.",
    )

    MAX_CAPITAL_PER_TRADE_PERCENT: float = Field(
        default=2.0,
        ge=0.1,
        le=10.0,
        description="Max % of portfolio to risk per trade. Recommended: 1-3.",
    )
    MAX_PORTFOLIO_DRAWDOWN_PERCENT: float = Field(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Trading pauses if portfolio drops this % from its peak.",
    )
    DAILY_LOSS_LIMIT_PERCENT: float = Field(
        default=5.0,
        ge=1.0,
        le=20.0,
        description="Trading pauses if daily losses exceed this % of portfolio.",
    )
    MINIMUM_TRADE_CONFIDENCE: float = Field(
        default=0.65,
        ge=0.5,
        le=1.0,
        description="Min confidence (0-1) before placing a trade. Recommended: 0.65-0.75.",
    )
    MAX_OPEN_POSITIONS: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Maximum number of stocks held simultaneously.",
    )
    PAPER_TRADING_CAPITAL: float = Field(
        default=100_000.0,
        ge=1000.0,
        description="Starting capital for paper trading simulation (in local currency).",
    )

    # Minimum paper trades required before live mode is unlocked
    MIN_PAPER_TRADES_FOR_LIVE: int = Field(
        default=100,
        description="System blocks live trading until this many paper trades are completed.",
    )
    MIN_PAPER_WIN_RATE_FOR_LIVE: float = Field(
        default=0.50,
        description="Minimum paper trading win rate (0-1) required before live mode.",
    )

    # ── ML Configuration ─────────────────────────────────────────────────────
    LSTM_WEIGHT: float = Field(
        default=0.45,
        ge=0.0,
        le=1.0,
        description="Weight of LSTM model in ensemble prediction (must sum to 1.0 with XGBOOST_WEIGHT).",
    )
    XGBOOST_WEIGHT: float = Field(
        default=0.55,
        ge=0.0,
        le=1.0,
        description="Weight of XGBoost model in ensemble prediction.",
    )
    LSTM_LOOKBACK_DAYS: int = Field(
        default=60,
        description="Number of past trading days LSTM uses as input sequence.",
    )
    MODEL_RETRAIN_DAY: str = Field(
        default="sunday",
        description="Day of week to retrain ML models (lowercase). Runs at 23:00.",
    )

    # ── Signal Weights (must sum to 1.0) ─────────────────────────────────────
    TECHNICAL_SIGNAL_WEIGHT: float = Field(default=0.25)
    FUNDAMENTAL_SIGNAL_WEIGHT: float = Field(default=0.20)
    SENTIMENT_SIGNAL_WEIGHT: float = Field(default=0.20)
    ML_SIGNAL_WEIGHT: float = Field(default=0.35)

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_PATH: str = Field(
        default="./data/trading.db",
        description="Path to SQLite database file.",
    )
    SUPABASE_URL: Optional[str] = Field(default=None)
    SUPABASE_KEY: Optional[str] = Field(default=None)

    # ── Redis Cache ───────────────────────────────────────────────────────────
    REDIS_HOST: str = Field(default="localhost")
    REDIS_PORT: int = Field(default=6379)
    REDIS_DB: int = Field(default=0)
    PRICE_CACHE_TTL_SECONDS: int = Field(
        default=60,
        description="How long to cache live prices (seconds). 60s is safe for 5-min cycles.",
    )
    HISTORICAL_CACHE_TTL_SECONDS: int = Field(
        default=21_600,
        description="How long to cache historical OHLCV data (seconds). Default: 6 hours.",
    )

    # ── API Server ────────────────────────────────────────────────────────────
    API_HOST: str = Field(default="127.0.0.1")
    API_PORT: int = Field(default=8000, ge=1024, le=65535)
    API_RELOAD: bool = Field(
        default=False,
        description="Auto-reload on code changes. Set True only during development.",
    )

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = Field(default="INFO")
    LOG_FILE: str = Field(default="./logs/trader.log")

    # ── Watchlist ─────────────────────────────────────────────────────────────
    # Override these in .env to customize which stocks are monitored.
    # Format: comma-separated symbols (e.g., "RELIANCE.NS,TCS.NS,INFY.NS")
    INDIA_WATCHLIST_OVERRIDE: Optional[str] = Field(
        default=None,
        description="Comma-separated NSE symbols. If blank, uses the default top-20 list.",
    )
    US_WATCHLIST_OVERRIDE: Optional[str] = Field(
        default=None,
        description="Comma-separated US symbols. If blank, uses the default top-20 list.",
    )

    # ── Validators ────────────────────────────────────────────────────────────

    @field_validator("TRADING_MODE")
    @classmethod
    def warn_if_live(cls, v: str) -> str:
        if v == "live":
            print(
                "\n⚠️  WARNING: TRADING_MODE is set to 'live'. "
                "This system will use REAL MONEY. "
                "Ensure you have completed 100+ paper trades first.\n"
            )
        return v

    @model_validator(mode="after")
    def validate_signal_weights_sum_to_one(self) -> "Settings":
        total = (
            self.TECHNICAL_SIGNAL_WEIGHT
            + self.FUNDAMENTAL_SIGNAL_WEIGHT
            + self.SENTIMENT_SIGNAL_WEIGHT
            + self.ML_SIGNAL_WEIGHT
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"Signal weights must sum to 1.0, but got {total:.4f}. "
                f"Check TECHNICAL_SIGNAL_WEIGHT, FUNDAMENTAL_SIGNAL_WEIGHT, "
                f"SENTIMENT_SIGNAL_WEIGHT, ML_SIGNAL_WEIGHT in your .env file."
            )
        return self

    @model_validator(mode="after")
    def validate_ensemble_weights_sum_to_one(self) -> "Settings":
        total = self.LSTM_WEIGHT + self.XGBOOST_WEIGHT
        if abs(total - 1.0) > 0.001:
            raise ValueError(
                f"LSTM_WEIGHT + XGBOOST_WEIGHT must sum to 1.0, but got {total:.4f}."
            )
        return self

    @model_validator(mode="after")
    def validate_broker_credentials(self) -> "Settings":
        """
        Checks that the right broker credentials are provided
        based on the chosen TARGET_MARKET.
        """
        if self.TRADING_MODE == "paper":
            # Paper mode doesn't need real broker credentials
            return self

        if self.TARGET_MARKET in ("india", "both"):
            if not all([self.ZERODHA_API_KEY, self.ZERODHA_API_SECRET, self.ZERODHA_USER_ID]):
                raise ValueError(
                    "TARGET_MARKET includes India but ZERODHA_API_KEY, "
                    "ZERODHA_API_SECRET, and ZERODHA_USER_ID are not all set in .env"
                )

        if self.TARGET_MARKET in ("us", "both"):
            if not all([self.ALPACA_API_KEY, self.ALPACA_SECRET_KEY]):
                raise ValueError(
                    "TARGET_MARKET includes US but ALPACA_API_KEY and "
                    "ALPACA_SECRET_KEY are not set in .env"
                )
        return self

    # ── Computed Properties ───────────────────────────────────────────────────

    @property
    def is_paper_mode(self) -> bool:
        return self.TRADING_MODE == "paper"

    @property
    def is_live_mode(self) -> bool:
        return self.TRADING_MODE == "live"

    @property
    def india_watchlist(self) -> List[str]:
        """Returns the active India watchlist (override or default)."""
        from config.constants import DEFAULT_INDIA_WATCHLIST
        if self.INDIA_WATCHLIST_OVERRIDE:
            return [s.strip() for s in self.INDIA_WATCHLIST_OVERRIDE.split(",") if s.strip()]
        return DEFAULT_INDIA_WATCHLIST

    @property
    def us_watchlist(self) -> List[str]:
        """Returns the active US watchlist (override or default)."""
        from config.constants import DEFAULT_US_WATCHLIST
        if self.US_WATCHLIST_OVERRIDE:
            return [s.strip() for s in self.US_WATCHLIST_OVERRIDE.split(",") if s.strip()]
        return DEFAULT_US_WATCHLIST

    @property
    def active_watchlist(self) -> List[str]:
        """Returns the watchlist for the configured target market."""
        if self.TARGET_MARKET == "india":
            return self.india_watchlist
        elif self.TARGET_MARKET == "us":
            return self.us_watchlist
        else:  # both
            return self.india_watchlist + self.us_watchlist

    @property
    def database_path_resolved(self) -> Path:
        """Returns the absolute path to the SQLite database file."""
        p = Path(self.DATABASE_PATH)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def log_file_resolved(self) -> Path:
        """Returns the absolute path to the log file."""
        p = Path(self.LOG_FILE)
        if not p.is_absolute():
            p = BASE_DIR / p
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def notifications_enabled(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)

    def summary(self) -> str:
        """Returns a human-readable config summary for startup logs."""
        lines = [
            "=" * 55,
            "  AUTONOMOUS TRADER — CONFIGURATION SUMMARY",
            "=" * 55,
            f"  Trading Mode  : {self.TRADING_MODE.upper()}",
            f"  Target Market : {self.TARGET_MARKET.upper()}",
            f"  Trading Style : {self.TRADING_STYLE.upper()}",
            f"  Watchlist Size: {len(self.active_watchlist)} symbols",
            f"  Risk Per Trade: {self.MAX_CAPITAL_PER_TRADE_PERCENT}%",
            f"  Max Drawdown  : {self.MAX_PORTFOLIO_DRAWDOWN_PERCENT}%",
            f"  Daily Loss Cap: {self.DAILY_LOSS_LIMIT_PERCENT}%",
            f"  Min Confidence: {self.MINIMUM_TRADE_CONFIDENCE}",
            f"  Max Positions : {self.MAX_OPEN_POSITIONS}",
            f"  Notifications : {'Enabled (Telegram)' if self.notifications_enabled else 'Disabled'}",
            f"  Database      : {self.database_path_resolved}",
            "=" * 55,
        ]
        return "\n".join(lines)


# ── Singleton instance ────────────────────────────────────────────────────────
# Import this object everywhere in the codebase:
#   from config.settings import settings
#
# It is loaded once at import time. If any required field is missing
# from the .env file, the program will exit with a clear error message.
try:
    settings = Settings()
except Exception as e:
    raise SystemExit(
        f"\n❌ Configuration Error — could not load settings:\n{e}\n\n"
        f"Fix: Check your .env file. Copy .env.example as a template.\n"
    ) from e
