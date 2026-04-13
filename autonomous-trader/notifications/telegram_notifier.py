"""
notifications/telegram_notifier.py
====================================
Telegram bot for trading notifications.

Sends real-time notifications for:
  - Trade executions
  - Portfolio updates
  - Errors and warnings
  - Daily summaries

Setup:
  1. Create bot via @BotFather on Telegram
  2. Get bot token
  3. Get your chat ID (send /start to bot, check updates)
  4. Add to .env:
     TELEGRAM_BOT_TOKEN=your_bot_token
     TELEGRAM_CHAT_ID=your_chat_id

Usage:
    from notifications.telegram_notifier import TelegramNotifier
    notifier = TelegramNotifier()
    notifier.send_trade_notification("BUY", "AAPL", 10, 150.00)
"""

from __future__ import annotations

from typing import Optional
import requests
from datetime import datetime

from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# TELEGRAM NOTIFIER
# ═══════════════════════════════════════════════════════════════

class TelegramNotifier:
    """
    Sends trading notifications via Telegram bot.
    """
    
    def __init__(self):
        """Initializes Telegram notifier."""
        self.bot_token = settings.TELEGRAM_BOT_TOKEN
        self.chat_id = settings.TELEGRAM_CHAT_ID
        self.enabled = bool(self.bot_token and self.chat_id)
        
        if not self.enabled:
            logger.warning(
                "Telegram notifications disabled: Missing bot token or chat ID"
            )
        else:
            logger.info("Telegram notifier initialized")
    
    # ── Core Sending ───────────────────────────────────────────────────────
    
    def send_message(
        self,
        message: str,
        parse_mode: str = "Markdown",
        disable_notification: bool = False,
    ) -> bool:
        """
        Sends a message via Telegram bot.
        
        Args:
            message: Message text (supports Markdown/HTML)
            parse_mode: "Markdown" | "HTML" | None
            disable_notification: If True, sends silently
        
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False
        
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_notification": disable_notification,
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return True
        
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False
    
    # ── Trade Notifications ────────────────────────────────────────────────
    
    def send_trade_notification(
        self,
        action: str,
        symbol: str,
        quantity: int,
        price: float,
        status: str = "FILLED",
        order_id: Optional[str] = None,
        reasoning: Optional[str] = None,
    ) -> bool:
        """
        Sends trade execution notification.
        
        Args:
            action: "BUY" | "SELL"
            symbol: Stock symbol
            quantity: Number of shares
            price: Execution price
            status: Order status
            order_id: Broker order ID
            reasoning: Decision reasoning
        
        Returns:
            True if sent successfully
        """
        emoji = "🟢" if action == "BUY" else "🔴"
        
        message = f"{emoji} *{action} ORDER {status}*\n\n"
        message += f"*Symbol:* {symbol}\n"
        message += f"*Quantity:* {quantity}\n"
        message += f"*Price:* ${price:.2f}\n"
        message += f"*Total:* ${price * quantity:,.2f}\n"
        
        if order_id:
            message += f"*Order ID:* `{order_id}`\n"
        
        if reasoning:
            # Truncate reasoning if too long
            if len(reasoning) > 200:
                reasoning = reasoning[:197] + "..."
            message += f"\n_{reasoning}_"
        
        message += f"\n\n🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        
        return self.send_message(message)
    
    def send_position_update(
        self,
        symbol: str,
        quantity: int,
        entry_price: float,
        current_price: float,
        unrealized_pnl: float,
    ) -> bool:
        """
        Sends position update notification.
        
        Args:
            symbol: Stock symbol
            quantity: Current quantity
            entry_price: Average entry price
            current_price: Current market price
            unrealized_pnl: Unrealized P&L
        
        Returns:
            True if sent successfully
        """
        pnl_emoji = "📈" if unrealized_pnl > 0 else "📉"
        pnl_pct = (current_price - entry_price) / entry_price * 100
        
        message = f"{pnl_emoji} *POSITION UPDATE: {symbol}*\n\n"
        message += f"*Quantity:* {quantity}\n"
        message += f"*Entry Price:* ${entry_price:.2f}\n"
        message += f"*Current Price:* ${current_price:.2f}\n"
        message += f"*Unrealized P&L:* ${unrealized_pnl:,.2f} ({pnl_pct:+.2f}%)\n"
        message += f"\n🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        
        return self.send_message(message)
    
    # ── System Notifications ───────────────────────────────────────────────
    
    def send_error_notification(
        self,
        error_type: str,
        error_message: str,
        symbol: Optional[str] = None,
    ) -> bool:
        """
        Sends error notification.
        
        Args:
            error_type: Type of error
            error_message: Error details
            symbol: Related symbol (if any)
        
        Returns:
            True if sent successfully
        """
        message = f"⚠️ *ERROR: {error_type}*\n\n"
        
        if symbol:
            message += f"*Symbol:* {symbol}\n"
        
        message += f"*Details:* {error_message}\n"
        message += f"\n🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        
        return self.send_message(message)
    
    def send_circuit_breaker_notification(
        self,
        state: str,
        reason: str,
    ) -> bool:
        """
        Sends circuit breaker status notification.
        
        Args:
            state: "OPEN" | "CLOSED"
            reason: Reason for state change
        
        Returns:
            True if sent successfully
        """
        if state == "OPEN":
            emoji = "🚨"
            title = "CIRCUIT BREAKER OPENED"
        else:
            emoji = "✅"
            title = "CIRCUIT BREAKER CLOSED"
        
        message = f"{emoji} *{title}*\n\n"
        message += f"*Reason:* {reason}\n"
        message += f"\n🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        
        return self.send_message(message)
    
    def send_daily_summary(
        self,
        trades_executed: int,
        total_pnl: float,
        portfolio_value: float,
        winning_trades: int,
        losing_trades: int,
    ) -> bool:
        """
        Sends daily trading summary.
        
        Args:
            trades_executed: Number of trades today
            total_pnl: Total P&L today
            portfolio_value: Current portfolio value
            winning_trades: Number of winning trades
            losing_trades: Number of losing trades
        
        Returns:
            True if sent successfully
        """
        pnl_emoji = "📈" if total_pnl > 0 else "📉" if total_pnl < 0 else "➖"
        win_rate = winning_trades / trades_executed * 100 if trades_executed > 0 else 0
        
        message = f"📊 *DAILY TRADING SUMMARY*\n\n"
        message += f"*Trades Executed:* {trades_executed}\n"
        message += f"*Winning Trades:* {winning_trades}\n"
        message += f"*Losing Trades:* {losing_trades}\n"
        message += f"*Win Rate:* {win_rate:.1f}%\n\n"
        message += f"{pnl_emoji} *Total P&L:* ${total_pnl:,.2f}\n"
        message += f"*Portfolio Value:* ${portfolio_value:,.2f}\n"
        message += f"\n🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        
        return self.send_message(message)
    
    # ── Market Updates ─────────────────────────────────────────────────────
    
    def send_market_regime_notification(
        self,
        regime: str,
        reasoning: str,
    ) -> bool:
        """
        Sends market regime change notification.
        
        Args:
            regime: New market regime
            reasoning: Reason for regime classification
        
        Returns:
            True if sent successfully
        """
        emoji_map = {
            "STRONG_BULL": "🚀",
            "BULL": "📈",
            "NEUTRAL": "➖",
            "BEAR": "📉",
            "STRONG_BEAR": "🔻",
        }
        
        emoji = emoji_map.get(regime, "📊")
        
        message = f"{emoji} *MARKET REGIME: {regime}*\n\n"
        message += f"_{reasoning}_\n"
        message += f"\n🕒 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        
        # Send silently for neutral regime
        silent = (regime == "NEUTRAL")
        
        return self.send_message(message, disable_notification=silent)
