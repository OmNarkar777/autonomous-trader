import { useState, useEffect } from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { TrendingUp } from 'lucide-react';
import { api, PriceData } from '@/lib/api';

export default function LivePriceChart() {
  const [symbol, setSymbol] = useState('RELIANCE.NS');
  const [priceData, setPriceData] = useState<Array<{ time: string; price: number }>>([]);
  const [currentPrice, setCurrentPrice] = useState<PriceData | null>(null);

  useEffect(() => {
    const fetchPrice = async () => {
      try {
        const data = await api.getCurrentPrices([symbol]);
        if (data.length > 0) {
          setCurrentPrice(data[0]);
          
          // Add to chart data
          setPriceData((prev) => {
            const newData = [
              ...prev,
              {
                time: new Date().toLocaleTimeString(),
                price: data[0].price,
              },
            ];
            // Keep only last 20 data points
            return newData.slice(-20);
          });
        }
      } catch (error) {
        console.error('Failed to fetch price:', error);
      }
    };

    fetchPrice();
    const interval = setInterval(fetchPrice, 5000); // Update every 5s

    return () => clearInterval(interval);
  }, [symbol]);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center">
            <TrendingUp className="w-5 h-5 mr-2" />
            Live Price Chart
          </h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Real-time price updates</p>
        </div>
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="px-3 py-2 border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white text-sm"
        >
          <option value="RELIANCE.NS">RELIANCE.NS</option>
          <option value="TCS.NS">TCS.NS</option>
          <option value="INFY.NS">INFY.NS</option>
          <option value="AAPL">AAPL</option>
          <option value="TSLA">TSLA</option>
          <option value="GOOGL">GOOGL</option>
        </select>
      </div>

      {currentPrice && (
        <div className="mb-6 p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
          <div className="flex items-baseline space-x-3">
            <span className="text-3xl font-bold text-gray-900 dark:text-white">
              ${currentPrice.price.toFixed(2)}
            </span>
            <span
              className={`text-sm font-medium ${
                currentPrice.change >= 0
                  ? 'text-green-600 dark:text-green-400'
                  : 'text-red-600 dark:text-red-400'
              }`}
            >
              {currentPrice.change >= 0 ? '+' : ''}
              {currentPrice.change.toFixed(2)} ({currentPrice.change_pct.toFixed(2)}%)
            </span>
          </div>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-1">
            Volume: {currentPrice.volume.toLocaleString()}
          </p>
        </div>
      )}

      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={priceData}>
            <CartesianGrid strokeDasharray="3 3" className="stroke-gray-200 dark:stroke-gray-700" />
            <XAxis
              dataKey="time"
              tick={{ fontSize: 12 }}
              className="text-gray-600 dark:text-gray-400"
            />
            <YAxis
              tick={{ fontSize: 12 }}
              className="text-gray-600 dark:text-gray-400"
              domain={['auto', 'auto']}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: 'rgba(255, 255, 255, 0.9)',
                border: '1px solid #e5e7eb',
                borderRadius: '0.5rem',
              }}
            />
            <Line
              type="monotone"
              dataKey="price"
              stroke="#3b82f6"
              strokeWidth={2}
              dot={false}
              animationDuration={300}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
