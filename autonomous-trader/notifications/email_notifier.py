"""
notifications/email_notifier.py
=================================
Email notifications for trading alerts.

Sends HTML-formatted emails for:
  - Trade confirmations
  - Daily/weekly summaries
  - Error alerts
  - Performance reports

Setup:
  Configure SMTP settings in .env:
    EMAIL_HOST=smtp.gmail.com
    EMAIL_PORT=587
    EMAIL_USERNAME=your_email@gmail.com
    EMAIL_PASSWORD=your_app_password
    EMAIL_FROM=your_email@gmail.com
    EMAIL_TO=recipient@email.com

For Gmail:
  - Enable 2FA
  - Generate app-specific password
  - Use that password in EMAIL_PASSWORD

Usage:
    from notifications.email_notifier import EmailNotifier
    notifier = EmailNotifier()
    notifier.send_trade_notification("BUY", "AAPL", 10, 150.00)
"""

from __future__ import annotations

from typing import Optional, List
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from config.settings import settings
from config.logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# EMAIL NOTIFIER
# ═══════════════════════════════════════════════════════════════

class EmailNotifier:
    """
    Sends trading notifications via email.
    """
    
    def __init__(self):
        """Initializes email notifier."""
        self.host = settings.EMAIL_HOST
        self.port = settings.EMAIL_PORT
        self.username = settings.EMAIL_USERNAME
        self.password = settings.EMAIL_PASSWORD
        self.from_email = settings.EMAIL_FROM
        self.to_email = settings.EMAIL_TO
        
        self.enabled = all([
            self.host,
            self.port,
            self.username,
            self.password,
            self.from_email,
            self.to_email,
        ])
        
        if not self.enabled:
            logger.warning(
                "Email notifications disabled: Missing SMTP configuration"
            )
        else:
            logger.info("Email notifier initialized")
    
    # ── Core Sending ───────────────────────────────────────────────────────
    
    def send_email(
        self,
        subject: str,
        body_html: str,
        body_text: Optional[str] = None,
    ) -> bool:
        """
        Sends an email.
        
        Args:
            subject: Email subject
            body_html: HTML email body
            body_text: Plain text fallback (optional)
        
        Returns:
            True if sent successfully
        """
        if not self.enabled:
            return False
        
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.from_email
            msg['To'] = self.to_email
            
            # Add text part (fallback)
            if body_text:
                text_part = MIMEText(body_text, 'plain')
                msg.attach(text_part)
            
            # Add HTML part
            html_part = MIMEText(body_html, 'html')
            msg.attach(html_part)
            
            # Send via SMTP
            with smtplib.SMTP(self.host, self.port) as server:
                server.starttls()
                server.login(self.username, self.password)
                server.send_message(msg)
            
            logger.info(f"Email sent: {subject}")
            return True
        
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
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
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
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
            stop_loss: Stop loss price
            take_profit: Take profit price
            reasoning: Decision reasoning
        
        Returns:
            True if sent successfully
        """
        subject = f"🔔 {action} ORDER {status}: {symbol}"
        
        # HTML body
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background-color: {'#4CAF50' if action == 'BUY' else '#f44336'}; 
                          color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .detail-row {{ padding: 8px 0; border-bottom: 1px solid #eee; }}
                .label {{ font-weight: bold; display: inline-block; width: 150px; }}
                .value {{ color: #333; }}
                .reasoning {{ background-color: #f5f5f5; padding: 15px; 
                            margin-top: 15px; border-left: 4px solid #2196F3; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>{action} ORDER {status}</h1>
            </div>
            <div class="content">
                <div class="detail-row">
                    <span class="label">Symbol:</span>
                    <span class="value">{symbol}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Quantity:</span>
                    <span class="value">{quantity}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Price:</span>
                    <span class="value">${price:.2f}</span>
                </div>
                <div class="detail-row">
                    <span class="label">Total Value:</span>
                    <span class="value">${price * quantity:,.2f}</span>
                </div>
        """
        
        if order_id:
            html += f"""
                <div class="detail-row">
                    <span class="label">Order ID:</span>
                    <span class="value">{order_id}</span>
                </div>
            """
        
        if stop_loss:
            html += f"""
                <div class="detail-row">
                    <span class="label">Stop Loss:</span>
                    <span class="value">${stop_loss:.2f}</span>
                </div>
            """
        
        if take_profit:
            html += f"""
                <div class="detail-row">
                    <span class="label">Take Profit:</span>
                    <span class="value">${take_profit:.2f}</span>
                </div>
            """
        
        if reasoning:
            html += f"""
                <div class="reasoning">
                    <strong>Decision Reasoning:</strong><br>
                    {reasoning}
                </div>
            """
        
        html += f"""
                <div style="margin-top: 20px; color: #999; font-size: 12px;">
                    {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC
                </div>
            </div>
        </body>
        </html>
        """
        
        return self.send_email(subject, html)
    
    # ── Daily Summary ──────────────────────────────────────────────────────
    
    def send_daily_summary(
        self,
        date: str,
        trades_executed: int,
        total_pnl: float,
        portfolio_value: float,
        winning_trades: int,
        losing_trades: int,
        trade_details: Optional[List[dict]] = None,
    ) -> bool:
        """
        Sends daily trading summary.
        
        Args:
            date: Trading date
            trades_executed: Number of trades
            total_pnl: Total P&L
            portfolio_value: Current portfolio value
            winning_trades: Number of wins
            losing_trades: Number of losses
            trade_details: List of trade dicts (optional)
        
        Returns:
            True if sent successfully
        """
        subject = f"📊 Daily Trading Summary - {date}"
        
        win_rate = winning_trades / trades_executed * 100 if trades_executed > 0 else 0
        pnl_color = '#4CAF50' if total_pnl > 0 else '#f44336' if total_pnl < 0 else '#999'
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background-color: #2196F3; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .summary-box {{ background-color: #f5f5f5; padding: 15px; margin: 10px 0; 
                              border-radius: 5px; }}
                .metric {{ padding: 10px 0; }}
                .metric-label {{ font-weight: bold; color: #666; }}
                .metric-value {{ font-size: 24px; color: #333; }}
                .pnl {{ color: {pnl_color}; font-weight: bold; }}
                table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                th {{ background-color: #2196F3; color: white; padding: 10px; text-align: left; }}
                td {{ padding: 8px; border-bottom: 1px solid #ddd; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>Daily Trading Summary</h1>
                <p>{date}</p>
            </div>
            <div class="content">
                <div class="summary-box">
                    <div class="metric">
                        <div class="metric-label">Total Trades</div>
                        <div class="metric-value">{trades_executed}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Win Rate</div>
                        <div class="metric-value">{win_rate:.1f}%</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Total P&L</div>
                        <div class="metric-value pnl">${total_pnl:,.2f}</div>
                    </div>
                    <div class="metric">
                        <div class="metric-label">Portfolio Value</div>
                        <div class="metric-value">${portfolio_value:,.2f}</div>
                    </div>
                </div>
        """
        
        if trade_details:
            html += """
                <h2>Trade Details</h2>
                <table>
                    <tr>
                        <th>Symbol</th>
                        <th>Action</th>
                        <th>Quantity</th>
                        <th>Price</th>
                        <th>P&L</th>
                    </tr>
            """
            
            for trade in trade_details:
                pnl = trade.get('pnl', 0)
                pnl_class = 'pnl' if pnl != 0 else ''
                html += f"""
                    <tr>
                        <td>{trade.get('symbol', '')}</td>
                        <td>{trade.get('action', '')}</td>
                        <td>{trade.get('quantity', 0)}</td>
                        <td>${trade.get('price', 0):.2f}</td>
                        <td class="{pnl_class}">${pnl:,.2f}</td>
                    </tr>
                """
            
            html += "</table>"
        
        html += """
            </div>
        </body>
        </html>
        """
        
        return self.send_email(subject, html)
    
    # ── Error Notifications ────────────────────────────────────────────────
    
    def send_error_notification(
        self,
        error_type: str,
        error_message: str,
        symbol: Optional[str] = None,
        stack_trace: Optional[str] = None,
    ) -> bool:
        """
        Sends error notification.
        
        Args:
            error_type: Type of error
            error_message: Error details
            symbol: Related symbol
            stack_trace: Full stack trace
        
        Returns:
            True if sent successfully
        """
        subject = f"⚠️ Trading System Error: {error_type}"
        
        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .header {{ background-color: #f44336; color: white; padding: 20px; text-align: center; }}
                .content {{ padding: 20px; }}
                .error-box {{ background-color: #ffebee; padding: 15px; 
                            border-left: 4px solid #f44336; margin: 10px 0; }}
                .stack {{ background-color: #f5f5f5; padding: 10px; font-family: monospace; 
                         font-size: 12px; overflow-x: auto; }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>⚠️ ERROR ALERT</h1>
            </div>
            <div class="content">
                <div class="error-box">
                    <h2>{error_type}</h2>
                    <p><strong>Message:</strong> {error_message}</p>
        """
        
        if symbol:
            html += f"<p><strong>Symbol:</strong> {symbol}</p>"
        
        html += f"<p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>"
        
        if stack_trace:
            html += f"""
                </div>
                <h3>Stack Trace:</h3>
                <div class="stack">{stack_trace}</div>
            """
        else:
            html += "</div>"
        
        html += """
            </div>
        </body>
        </html>
        """
        
        return self.send_email(subject, html)
