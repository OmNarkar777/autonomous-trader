import { useState, useEffect } from 'react';
import { AlertTriangle, Power, RotateCcw, CheckCircle, XCircle } from 'lucide-react';
import { api, SystemHealth } from '@/lib/api';

export default function CircuitBreakerPanel() {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const data = await api.getSystemHealth();
        setHealth(data);
      } catch (error) {
        console.error('Failed to fetch system health:', error);
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 3000);

    return () => clearInterval(interval);
  }, []);

  const handleOpen = async () => {
    setLoading(true);
    try {
      await api.openCircuitBreaker();
      const data = await api.getSystemHealth();
      setHealth(data);
    } catch (error) {
      console.error('Failed to open circuit breaker:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleClose = async () => {
    setLoading(true);
    try {
      await api.closeCircuitBreaker();
      const data = await api.getSystemHealth();
      setHealth(data);
    } catch (error) {
      console.error('Failed to close circuit breaker:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleReset = async () => {
    setLoading(true);
    try {
      await api.resetCircuitBreaker();
      const data = await api.getSystemHealth();
      setHealth(data);
    } catch (error) {
      console.error('Failed to reset circuit breaker:', error);
    } finally {
      setLoading(false);
    }
  };

  if (!health) {
    return null;
  }

  const isOpen = health.circuit_breaker_open;

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center">
          <AlertTriangle className="w-5 h-5 mr-2" />
          Circuit Breaker Control
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          Emergency stop mechanism for trading system
        </p>
      </div>

      <div className="p-6">
        {/* Status Display */}
        <div className={`p-6 rounded-lg mb-6 ${
          isOpen
            ? 'bg-red-50 dark:bg-red-900/20 border-2 border-red-200 dark:border-red-800'
            : 'bg-green-50 dark:bg-green-900/20 border-2 border-green-200 dark:border-green-800'
        }`}>
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-4">
              {isOpen ? (
                <XCircle className="w-12 h-12 text-red-600 dark:text-red-400" />
              ) : (
                <CheckCircle className="w-12 h-12 text-green-600 dark:text-green-400" />
              )}
              <div>
                <h3 className={`text-2xl font-bold ${
                  isOpen ? 'text-red-600 dark:text-red-400' : 'text-green-600 dark:text-green-400'
                }`}>
                  Circuit Breaker {isOpen ? 'OPEN' : 'CLOSED'}
                </h3>
                <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">
                  {isOpen 
                    ? 'Trading is halted. All new positions blocked.'
                    : 'Trading is active. System operating normally.'
                  }
                </p>
              </div>
            </div>
          </div>

          {health.consecutive_errors > 0 && (
            <div className="mt-4 p-3 bg-yellow-100 dark:bg-yellow-900/20 rounded border border-yellow-200 dark:border-yellow-800">
              <p className="text-sm text-yellow-800 dark:text-yellow-400 font-medium">
                ⚠️ Consecutive Errors: {health.consecutive_errors}
              </p>
              <p className="text-xs text-yellow-700 dark:text-yellow-500 mt-1">
                Circuit breaker will open automatically at 5 consecutive errors
              </p>
            </div>
          )}
        </div>

        {/* Control Buttons */}
        <div className="grid grid-cols-3 gap-4">
          <button
            onClick={handleOpen}
            disabled={loading || isOpen}
            className={`p-4 rounded-lg border-2 transition-colors flex flex-col items-center ${
              isOpen
                ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/30'
            }`}
          >
            <Power className="w-6 h-6 mb-2" />
            <span className="text-sm font-medium">Open Circuit</span>
            <span className="text-xs mt-1 opacity-75">Stop Trading</span>
          </button>

          <button
            onClick={handleClose}
            disabled={loading || !isOpen}
            className={`p-4 rounded-lg border-2 transition-colors flex flex-col items-center ${
              !isOpen
                ? 'bg-gray-50 dark:bg-gray-700/50 border-gray-200 dark:border-gray-600 text-gray-400 cursor-not-allowed'
                : 'bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800 text-green-700 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/30'
            }`}
          >
            <CheckCircle className="w-6 h-6 mb-2" />
            <span className="text-sm font-medium">Close Circuit</span>
            <span className="text-xs mt-1 opacity-75">Resume Trading</span>
          </button>

          <button
            onClick={handleReset}
            disabled={loading}
            className="p-4 rounded-lg border-2 bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors flex flex-col items-center"
          >
            <RotateCcw className="w-6 h-6 mb-2" />
            <span className="text-sm font-medium">Reset</span>
            <span className="text-xs mt-1 opacity-75">Clear Errors</span>
          </button>
        </div>

        {/* Warning */}
        <div className="mt-6 p-4 bg-yellow-50 dark:bg-yellow-900/20 rounded-lg border border-yellow-200 dark:border-yellow-800">
          <div className="flex">
            <AlertTriangle className="w-5 h-5 text-yellow-600 dark:text-yellow-400 flex-shrink-0 mt-0.5" />
            <div className="ml-3">
              <h4 className="text-sm font-semibold text-yellow-800 dark:text-yellow-400">
                Manual Control Warning
              </h4>
              <p className="text-xs text-yellow-700 dark:text-yellow-500 mt-1">
                Opening the circuit breaker will immediately halt all trading operations.
                Only close it when you're certain the system issues have been resolved.
                The system can also automatically open the circuit breaker if too many errors occur.
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
