import { useState } from 'react';
import { Activity, TrendingUp, AlertCircle, Brain } from 'lucide-react';
import PortfolioOverview from './components/PortfolioOverview';
import AgentStatusPanel from './components/AgentStatusPanel';
import TradeHistory from './components/TradeHistory';
import LivePriceChart from './components/LivePriceChart';
import SystemHealth from './components/SystemHealth';
import DecisionExplainer from './components/DecisionExplainer';
import CircuitBreakerPanel from './components/CircuitBreakerPanel';

type Tab = 'overview' | 'trades' | 'agents' | 'system';

function App() {
  const [activeTab, setActiveTab] = useState<Tab>('overview');

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-900">
      {/* Header */}
      <header className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <Brain className="w-8 h-8 text-blue-600" />
              <div>
                <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
                  Autonomous Trader
                </h1>
                <p className="text-sm text-gray-500 dark:text-gray-400">
                  AI-Powered Trading System
                </p>
              </div>
            </div>
            <div className="flex items-center space-x-2">
              <div className="flex items-center space-x-1 px-3 py-1.5 bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 rounded-full text-sm">
                <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                <span>Live</span>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* Navigation Tabs */}
      <div className="bg-white dark:bg-gray-800 border-b border-gray-200 dark:border-gray-700">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <nav className="flex space-x-8">
            <TabButton
              active={activeTab === 'overview'}
              onClick={() => setActiveTab('overview')}
              icon={<TrendingUp className="w-5 h-5" />}
              label="Overview"
            />
            <TabButton
              active={activeTab === 'trades'}
              onClick={() => setActiveTab('trades')}
              icon={<Activity className="w-5 h-5" />}
              label="Trades"
            />
            <TabButton
              active={activeTab === 'agents'}
              onClick={() => setActiveTab('agents')}
              icon={<Brain className="w-5 h-5" />}
              label="Agents"
            />
            <TabButton
              active={activeTab === 'system'}
              onClick={() => setActiveTab('system')}
              icon={<AlertCircle className="w-5 h-5" />}
              label="System"
            />
          </nav>
        </div>
      </div>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {activeTab === 'overview' && (
          <div className="space-y-6">
            <PortfolioOverview />
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <LivePriceChart />
              <DecisionExplainer />
            </div>
          </div>
        )}

        {activeTab === 'trades' && (
          <div className="space-y-6">
            <TradeHistory />
          </div>
        )}

        {activeTab === 'agents' && (
          <div className="space-y-6">
            <AgentStatusPanel />
          </div>
        )}

        {activeTab === 'system' && (
          <div className="space-y-6">
            <SystemHealth />
            <CircuitBreakerPanel />
          </div>
        )}
      </main>
    </div>
  );
}

interface TabButtonProps {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}

function TabButton({ active, onClick, icon, label }: TabButtonProps) {
  return (
    <button
      onClick={onClick}
      className={`
        flex items-center space-x-2 px-1 py-4 border-b-2 font-medium text-sm
        transition-colors
        ${
          active
            ? 'border-blue-500 text-blue-600 dark:text-blue-400'
            : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 dark:text-gray-400 dark:hover:text-gray-300'
        }
      `}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

export default App;
