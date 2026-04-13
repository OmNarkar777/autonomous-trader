# Autonomous Trader Dashboard

Real-time React dashboard for monitoring the autonomous trading system.

## Features

- **Portfolio Overview**: Real-time portfolio value, P&L, and position tracking
- **Live Price Charts**: Real-time price updates with Recharts
- **Agent Status Panel**: Monitor all AI agents with execution stats
- **Trade History**: Complete trade log with filtering and statistics
- **Decision Explainer**: Breakdown of AI decision-making process
- **System Health**: Monitor circuit breaker, errors, and uptime
- **Circuit Breaker Control**: Manual emergency stop controls

## Tech Stack

- **React 18** with TypeScript
- **Vite** for fast builds
- **TailwindCSS** for styling
- **Recharts** for charts
- **WebSocket** for real-time updates
- **date-fns** for date formatting

## Setup

### 1. Install Dependencies

```bash
npm install
```

### 2. Configure Environment

Create `.env` file:

```env
VITE_API_URL=http://localhost:8000/api
VITE_WS_URL=ws://localhost:8000/ws
```

### 3. Start Development Server

```bash
npm run dev
```

Dashboard will be available at `http://localhost:3000`

## Build for Production

```bash
npm run build
npm run preview
```

## Project Structure

```
dashboard/
├── src/
│   ├── components/          # React components
│   │   ├── PortfolioOverview.tsx
│   │   ├── AgentStatusPanel.tsx
│   │   ├── TradeHistory.tsx
│   │   ├── LivePriceChart.tsx
│   │   ├── SystemHealth.tsx
│   │   ├── DecisionExplainer.tsx
│   │   └── CircuitBreakerPanel.tsx
│   ├── hooks/              # Custom React hooks
│   │   ├── useWebSocket.ts
│   │   └── usePortfolio.ts
│   ├── lib/                # Utilities
│   │   └── api.ts          # API client
│   ├── App.tsx             # Main app component
│   ├── main.tsx            # Entry point
│   └── index.css           # Global styles
├── package.json
├── vite.config.ts
├── tsconfig.json
├── tailwind.config.js
└── README.md
```

## API Endpoints Required

The dashboard expects the following backend endpoints:

### Portfolio
- `GET /api/portfolio` - Get portfolio summary
- `GET /api/portfolio/positions` - Get all positions

### Trades
- `GET /api/trades?limit=N` - Get recent trades
- `GET /api/trades/:id` - Get trade details

### Agents
- `GET /api/agents/status` - Get all agent statuses

### System
- `GET /api/system/health` - Get system health metrics
- `POST /api/system/trigger-cycle` - Trigger manual trading cycle
- `POST /api/system/circuit-breaker/open` - Open circuit breaker
- `POST /api/system/circuit-breaker/close` - Close circuit breaker
- `POST /api/system/circuit-breaker/reset` - Reset circuit breaker

### Decisions
- `GET /api/decisions?limit=N` - Get recent decisions

### Prices
- `GET /api/prices?symbols=SYM1,SYM2` - Get current prices

### WebSocket
- `WS /ws/portfolio` - Real-time portfolio updates

## WebSocket Message Format

```json
{
  "type": "portfolio_update",
  "data": {
    "portfolio": { ... },
    "positions": [ ... ]
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## Dark Mode

Dashboard automatically adapts to system dark mode preference.

## Browser Support

- Chrome/Edge 90+
- Firefox 88+
- Safari 14+
