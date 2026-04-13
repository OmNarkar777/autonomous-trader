#!/bin/bash
#
# scripts/setup.sh
# ================
# Complete setup script for autonomous trading system
#

set -e  # Exit on error

echo "=========================================="
echo "Autonomous Trader - Setup Script"
echo "=========================================="
echo ""

# Check Python version
echo "Checking Python version..."
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

if ! python3 -c 'import sys; assert sys.version_info >= (3, 9)' 2>/dev/null; then
    echo "ERROR: Python 3.9+ required"
    exit 1
fi

# Create virtual environment
echo ""
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Create .env file if it doesn't exist
echo ""
echo "Setting up environment variables..."
if [ ! -f ".env" ]; then
    cat > .env << 'ENV'
# API Keys
NEWSAPI_KEY=your_newsapi_key_here
FRED_API_KEY=your_fred_api_key_here

# Broker Credentials (Zerodha)
ZERODHA_API_KEY=your_zerodha_api_key
ZERODHA_API_SECRET=your_zerodha_secret
ZERODHA_ACCESS_TOKEN=your_zerodha_access_token

# Broker Credentials (Alpaca)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_API_SECRET=your_alpaca_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Notifications
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# Email
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@email.com

# Database
DATABASE_URL=sqlite:///autonomous_trader.db

# System
TARGET_MARKET=india
INITIAL_CAPITAL=100000
ENV
    echo "✓ .env file created - PLEASE UPDATE WITH YOUR API KEYS"
else
    echo "✓ .env file already exists"
fi

# Create directories
echo ""
echo "Creating directories..."
mkdir -p models logs data

# Initialize database
echo ""
echo "Initializing database..."
python3 << 'PYTHON'
from data.storage.database import DatabaseManager
db = DatabaseManager()
db.init_database()
print("✓ Database initialized")
PYTHON

# Run tests
echo ""
echo "Running tests..."
pytest tests/ -v --tb=short || echo "⚠ Some tests failed (this is OK for initial setup)"

# Dashboard setup
echo ""
echo "Setting up React dashboard..."
if [ -d "dashboard" ]; then
    cd dashboard
    if [ ! -d "node_modules" ]; then
        echo "Installing npm dependencies..."
        npm install
        echo "✓ Dashboard dependencies installed"
    else
        echo "✓ Dashboard dependencies already installed"
    fi
    cd ..
else
    echo "⚠ Dashboard directory not found"
fi

echo ""
echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Update .env file with your API keys"
echo "2. Train models: python scripts/train_models.py"
echo "3. Run backtest: python scripts/backtest.py"
echo "4. Check system health: python scripts/health_check.py"
echo "5. Start trading: python -m orchestrator.scheduler"
echo ""
echo "To activate the virtual environment:"
echo "  source venv/bin/activate"
echo ""
