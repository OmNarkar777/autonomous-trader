import { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Clock, CheckCircle, XCircle } from 'lucide-react';
import { api, Trade } from '@/lib/api';
import { format } from 'date-fns';

export default function TradeHistory() {
  const [trades, setTrades] = useState<Trade[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<'all' | 'BUY' | 'SELL'>('all');

  useEffect(() => {
    const fetchTrades = async () => {
      try {
        const data = await api.getTrades(100);
        setTrades(data);
      } catch (error) {
        console.error('Failed to fetch trades:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchTrades();
  }, []);

  const filteredTrades = trades.filter(
    (trade) => filter === 'all' || trade.action === filter
  );

  const stats = {
    total: trades.length,
    buys: trades.filter((t) => t.action === 'BUY').length,
    sells: trades.filter((t) => t.action === 'SELL').length,
    totalPnL: trades.reduce((sum, t) => sum + (t.pnl || 0), 0),
  };

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-8 text-center">
        <div className="animate-pulse">Loading trades...</div>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white">
            Trade History
          </h2>
          <div className="flex items-center space-x-2">
            <FilterButton
              label="All"
              count={stats.total}
              active={filter === 'all'}
              onClick={() => setFilter('all')}
            />
            <FilterButton
              label="Buys"
              count={stats.buys}
              active={filter === 'BUY'}
              onClick={() => setFilter('BUY')}
              color="green"
            />
            <FilterButton
              label="Sells"
              count={stats.sells}
              active={filter === 'SELL'}
              onClick={() => setFilter('SELL')}
              color="red"
            />
          </div>
        </div>

        {/* Stats Summary */}
        <div className="mt-4 grid grid-cols-4 gap-4">
          <StatItem label="Total Trades" value={stats.total} />
          <StatItem label="Buys" value={stats.buys} color="green" />
          <StatItem label="Sells" value={stats.sells} color="red" />
          <StatItem
            label="Total P&L"
            value={`$${stats.totalPnL.toFixed(2)}`}
            color={stats.totalPnL >= 0 ? 'green' : 'red'}
          />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-gray-50 dark:bg-gray-700">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Date
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Symbol
              </th>
              <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Action
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Quantity
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Price
              </th>
              <th className="px-6 py-3 text-center text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Status
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                Confidence
              </th>
              <th className="px-6 py-3 text-right text-xs font-medium text-gray-500 dark:text-gray-300 uppercase">
                P&L
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {filteredTrades.map((trade) => (
              <tr key={trade.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500 dark:text-gray-300">
                  {format(new Date(trade.created_at), 'MMM dd, HH:mm')}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-white">
                  {trade.symbol}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-center">
                  <span
                    className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      trade.action === 'BUY'
                        ? 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400'
                        : 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400'
                    }`}
                  >
                    {trade.action === 'BUY' ? (
                      <TrendingUp className="w-3 h-3 mr-1" />
                    ) : (
                      <TrendingDown className="w-3 h-3 mr-1" />
                    )}
                    {trade.action}
                  </span>
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-500 dark:text-gray-300">
                  {trade.quantity}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-500 dark:text-gray-300">
                  ${trade.entry_price.toFixed(2)}
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-center">
                  <StatusBadge status={trade.status} />
                </td>
                <td className="px-6 py-4 whitespace-nowrap text-sm text-right text-gray-500 dark:text-gray-300">
                  {(trade.confidence_score * 100).toFixed(0)}%
                </td>
                <td
                  className={`px-6 py-4 whitespace-nowrap text-sm text-right font-medium ${
                    (trade.pnl || 0) >= 0
                      ? 'text-green-600 dark:text-green-400'
                      : 'text-red-600 dark:text-red-400'
                  }`}
                >
                  {trade.pnl !== undefined ? `$${trade.pnl.toFixed(2)}` : '-'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FilterButton({
  label,
  count,
  active,
  onClick,
  color = 'blue',
}: {
  label: string;
  count: number;
  active: boolean;
  onClick: () => void;
  color?: 'blue' | 'green' | 'red';
}) {
  const colorClasses = {
    blue: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    green: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400',
    red: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  };

  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
        active
          ? colorClasses[color]
          : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-300 dark:hover:bg-gray-600'
      }`}
    >
      {label} ({count})
    </button>
  );
}

function StatItem({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: 'green' | 'red';
}) {
  const textColorClass = color
    ? color === 'green'
      ? 'text-green-600 dark:text-green-400'
      : 'text-red-600 dark:text-red-400'
    : 'text-gray-900 dark:text-white';

  return (
    <div>
      <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
      <p className={`text-lg font-semibold ${textColorClass}`}>{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
    FILLED: {
      label: 'Filled',
      color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400',
      icon: <CheckCircle className="w-3 h-3" />,
    },
    PENDING: {
      label: 'Pending',
      color: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-400',
      icon: <Clock className="w-3 h-3" />,
    },
    REJECTED: {
      label: 'Rejected',
      color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400',
      icon: <XCircle className="w-3 h-3" />,
    },
  };

  const { label, color, icon } = config[status] || config.PENDING;

  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${color}`}>
      {icon}
      <span className="ml-1">{label}</span>
    </span>
  );
}
