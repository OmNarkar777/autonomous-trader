# 🤖 Autonomous Trading System

**100% autonomous AI-powered stock trading system with multi-agent architecture, ML models, and real-time dashboard.**

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 📋 Table of Contents

- [Features](#-features)
- [Architecture](#-architecture)
- [Prerequisites](#-prerequisites)
- [Quick Start](#-quick-start)
- [Configuration](#-configuration)
- [Usage](#-usage)
- [Dashboard](#-dashboard)
- [Testing](#-testing)
- [Project Structure](#-project-structure)
- [Contributing](#-contributing)
- [License](#-license)

---

## ✨ Features

### **🧠 AI-Powered Decision Making**
- **Multi-agent system** with specialized agents (Data, Analysis, Risk, Execution)
- **Ensemble ML models** (LSTM + XGBoost) for price prediction
- **4-factor scoring**: Technical, Fundamental, Sentiment, ML model predictions
- **Confidence-based execution** with adjustable thresholds

### **⚡ Real-Time Trading**
- **Live market data** from Yahoo Finance, NewsAPI, FRED
- **Automated scheduling** (hourly during market hours)
- **WebSocket dashboard** for real-time monitoring
- **Circuit breaker** for automatic risk management

### **🛡️ Risk Management**
- **Position sizing** based on ATR (Average True Range)
- **Event risk detection** (earnings announcements, market regime)
- **Portfolio constraints** (max positions, sector concentration)
- **Stop loss & take profit** automatically calculated

### **📊 Multi-Market Support**
- **Indian markets** (NSE/BSE) via Zerodha
- **US markets** (NYSE/NASDAQ) via Alpaca
- **Paper trading** mode for testing

### **📈 Analytics & Monitoring**
- **React dashboard** with live updates
- **Telegram & Email notifications**
- **Comprehensive backtesting** with Sharpe ratio, win rate
- **Model performance tracking**

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     DECISION AGENT (Brain)                  │
│                  Orchestrates all other agents              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
┌───────▼────────┐   ┌────────▼────────┐   ┌───────▼────────┐
│  DATA AGENTS   │   │  ANALYSIS       │   │  RISK AGENTS   │
│                │   │  (TODO)         │   │                │
│ • Price        │   │ • Technical     │   │ • Position     │
│ • News         │   │ • Fundamental   │   │   Sizing       │
│ • Macro        │   │ • Sentiment     │   │ • Event Risk   │
│ • Earnings     │   │ • ML Models     │   │ • Portfolio    │
└────────────────┘   └─────────────────┘   └────────────────┘
                              │
                    ┌─────────▼──────────┐
                    │ EXECUTION AGENT    │
                    │ • Paper Broker     │
                    │ • Zerodha (India)  │
                    │ • Alpaca (US)      │
                    └────────────────────┘
```

---

## 📦 Prerequisites

### **Required**
- **Python 3.9+** ([Download](https://www.python.org/downloads/))
- **pip** (comes with Python)
- **Node.js 18+** ([Download](https://nodejs.org/)) - for dashboard

### **Optional**
- **Redis** - for caching (falls back to in-memory if not available)
- **PostgreSQL** - for production database (SQLite used by default)

### **API Keys** (sign up for free)
- **NewsAPI** - [newsapi.org](https://newsapi.org/)
- **FRED** - [fred.stlouisfed.org/docs/api/](https://fred.stlouisfed.org/docs/api/)
- **Zerodha** (India) - [kite.trade](https://kite.trade/)
- **Alpaca** (US) - [alpaca.markets](https://alpaca.markets/)

---

## 🚀 Quick Start

### **1. Clone Repository**

```bash
git clone https://github.com/yourusername/autonomous-trader.git
cd autonomous-trader
```

### **2. Run Automated Setup**

```bash
chmod +x scripts/setup.sh
./scripts/setup.sh
```

This will:
- ✅ Create virtual environment
- ✅ Install Python dependencies
- ✅ Initialize database
- ✅ Create `.env` template
- ✅ Set up dashboard
- ✅ Run tests

### **3. Configure API Keys**

Edit `.env` file with your API keys:

```bash
nano .env  # or use your favorite editor
```

**Minimum required for testing:**
```env
NEWSAPI_KEY=your_newsapi_key_here
FRED_API_KEY=your_fred_api_key_here
```

### **4. Train ML Models**

```bash
source venv/bin/activate
python scripts/train_models.py --market india --epochs 100
```

This will train LSTM + XGBoost models for all watchlist symbols (~30 minutes).

### **5. Run Backtest**

```bash
python scripts/backtest.py --market india --days 365
```

Validates strategy performance on 1 year of historical data.

### **6. Check System Health**

```bash
python scripts/health_check.py
```

Verifies all components are working correctly.

### **7. Start Trading! 🎉**

**Paper trading (recommended first):**
```bash
python -m orchestrator.scheduler
```

**Or trigger single cycle:**
```bash
python scripts/run_cycle.py
```

### **8. Launch Dashboard**

```bash
cd dashboard
npm run dev
```

Dashboard available at `http://localhost:3000`

---

## ⚙️ Configuration

### **Environment Variables (.env)**

```env
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# API KEYS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEWSAPI_KEY=your_newsapi_key
FRED_API_KEY=your_fred_api_key

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# BROKER CREDENTIALS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Zerodha (India)
ZERODHA_API_KEY=your_zerodha_api_key
ZERODHA_API_SECRET=your_zerodha_secret
ZERODHA_ACCESS_TOKEN=your_access_token

# Alpaca (US)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_API_SECRET=your_alpaca_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# NOTIFICATIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USERNAME=your_email@gmail.com
EMAIL_PASSWORD=your_app_password
EMAIL_FROM=your_email@gmail.com
EMAIL_TO=recipient@email.com

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SYSTEM SETTINGS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TARGET_MARKET=india              # india | us | both
INITIAL_CAPITAL=100000            # Starting capital
DATABASE_URL=sqlite:///autonomous_trader.db
```

### **Watchlist Configuration**

Edit `config/constants.py`:

```python
# Indian stocks
INDIA_WATCHLIST = [
    "RELIANCE.NS",
    "TCS.NS",
    "INFY.NS",
    # Add more...
]

# US stocks
US_WATCHLIST = [
    "AAPL",
    "TSLA",
    "GOOGL",
    # Add more...
]
```

### **Risk Parameters**

Edit `config/constants.py`:

```python
# Position sizing
POSITION_RISK_PCT = 0.02          # 2% risk per trade
STOP_LOSS_ATR_MULTIPLIER = 2.0    # 2 × ATR
TAKE_PROFIT_ATR_MULTIPLIER = 3.0  # 3 × ATR

# Portfolio limits
MAX_OPEN_POSITIONS = 10           # Max concurrent positions
MAX_SECTOR_CONCENTRATION = 0.3    # 30% max in one sector
MAX_PORTFOLIO_HEAT = 0.4          # 40% total capital at risk

# Decision thresholds
DECISION_CONFIDENCE_THRESHOLD = 0.65
```

---

## 📖 Usage

### **Manual Trading Cycle**

```bash
python -c "
from orchestrator.scheduler import TradingScheduler
scheduler = TradingScheduler(broker_type='paper')
results = scheduler.run_trading_cycle()
print(results)
"
```

### **Automated Scheduling**

```bash
# Start scheduler (runs hourly during market hours)
python -m orchestrator.scheduler
```

### **Train Models for Specific Symbols**

```bash
python scripts/train_models.py --symbols AAPL TSLA GOOGL --epochs 50
```

### **Backtest with Custom Parameters**

```bash
python scripts/backtest.py --symbols RELIANCE.NS TCS.NS --days 180
```

### **Check Specific Components**

```python
from agents.decision_agent import DecisionAgent

agent = DecisionAgent()
result = agent.run(symbol="AAPL", company_name="Apple Inc")

print(f"Decision: {result.data.decision}")
print(f"Confidence: {result.data.confidence:.1%}")
print(f"Reasoning: {result.data.reasoning}")
```

---

## 📊 Dashboard

### **Features**

- **Portfolio Overview**: Real-time value, P&L, positions
- **Live Price Charts**: 5-second updates with Recharts
- **Agent Status**: Monitor all AI agents
- **Trade History**: Filter by BUY/SELL, view statistics
- **Decision Explainer**: Score breakdown and reasoning
- **System Health**: Circuit breaker, errors, uptime
- **Manual Controls**: Trigger cycles, manage circuit breaker

### **Setup**

```bash
cd dashboard
npm install
npm run dev
```

### **Build for Production**

```bash
npm run build
npm run preview
```

### **Environment Variables**

Create `dashboard/.env`:

```env
VITE_API_URL=http://localhost:8000/api
VITE_WS_URL=ws://localhost:8000/ws
```

---

## 🧪 Testing

### **Run All Tests**

```bash
pytest tests/ -v
```

### **Run Specific Test File**

```bash
pytest tests/test_decision_agent.py -v
```

### **Run with Coverage**

```bash
pytest tests/ --cov=. --cov-report=html
```

### **Test Categories**

- `test_data_collectors.py` - Data collection APIs
- `test_ml_models.py` - LSTM, XGBoost, Ensemble
- `test_agents.py` - Base agent + data agents
- `test_decision_agent.py` - Decision-making logic
- `test_risk_agents.py` - Position sizing, risk management
- `test_execution_agent.py` - Order execution

---

## 📁 Project Structure

```
autonomous-trader/
├── config/                    # Configuration
│   ├── settings.py           # Environment settings
│   ├── constants.py          # Trading parameters
│   └── logging_config.py     # Logging setup
├── data/                      # Data layer
│   ├── collectors/           # Data collection APIs
│   ├── validators/           # Data validation
│   └── storage/              # Database & cache
├── ml/                        # Machine learning
│   ├── features/             # Feature engineering
│   ├── models/               # LSTM, XGBoost, Ensemble
│   └── training/             # Training & backtesting
├── agents/                    # AI agents
│   ├── base_agent.py         # Base agent class
│   ├── data_agents/          # Price, News, Macro, Earnings
│   ├── risk_agents/          # Position sizing, Risk management
│   ├── decision_agent.py     # THE BRAIN
│   └── execution_agent.py    # Order execution
├── orchestrator/              # System orchestration
│   ├── state.py              # State management
│   ├── graph.py              # LangGraph state machine
│   ├── circuit_breaker.py    # Safety mechanism
│   └── scheduler.py          # Automated scheduling
├── broker/                    # Broker integrations
│   ├── base_broker.py        # Abstract broker interface
│   ├── paper_broker.py       # Simulated trading
│   ├── zerodha_broker.py     # Zerodha (India)
│   └── alpaca_broker.py      # Alpaca (US)
├── notifications/             # Alert system
│   ├── telegram_notifier.py  # Telegram bot
│   └── email_notifier.py     # Email alerts
├── dashboard/                 # React dashboard
│   ├── src/
│   │   ├── components/       # UI components
│   │   ├── hooks/            # Custom hooks
│   │   └── lib/              # API client
│   └── package.json
├── tests/                     # Test suite
├── scripts/                   # Utility scripts
│   ├── setup.sh              # Automated setup
│   ├── train_models.py       # Model training
│   ├── backtest.py           # Backtesting
│   └── health_check.py       # System diagnostics
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

**Total: 18,522 lines of production code**
- Backend (Python): 16,732 lines
- Frontend (React/TypeScript): 1,790 lines

---

## 🔧 Troubleshooting

### **Import Errors**

```bash
# Ensure virtual environment is activated
source venv/bin/activate

# Reinstall dependencies
pip install -r requirements.txt
```

### **Database Issues**

```bash
# Reset database
rm autonomous_trader.db
python -c "from data.storage.database import DatabaseManager; DatabaseManager().init_database()"
```

### **Model Training Fails**

```bash
# Check data availability
python -c "from data.collectors.price_collector import PriceCollector; print(PriceCollector().get_current_price('AAPL'))"

# Train with fewer epochs
python scripts/train_models.py --epochs 20
```

### **Dashboard Won't Start**

```bash
cd dashboard
rm -rf node_modules package-lock.json
npm install
npm run dev
```

---

## 🤝 Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

## ⚠️ Disclaimer

**This software is for educational purposes only.**

- Trading stocks involves risk of loss
- Past performance does not guarantee future results
- Always use paper trading first
- Consult a financial advisor before live trading
- The authors are not responsible for any financial losses

---

## 📞 Support

- **Issues**: [GitHub Issues](https://github.com/yourusername/autonomous-trader/issues)
- **Discussions**: [GitHub Discussions](https://github.com/yourusername/autonomous-trader/discussions)
- **Email**: your.email@example.com

---

## 🙏 Acknowledgments

- **LangGraph** - Agent orchestration framework
- **TensorFlow** - Deep learning models
- **XGBoost** - Gradient boosting
- **yfinance** - Market data
- **React** - Dashboard UI
- **Recharts** - Data visualization

---

**Built with ❤️ for algorithmic trading enthusiasts**
