import { useState, useEffect } from 'react';
import { Activity, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react';
import { api, SystemHealth as SystemHealthType } from '@/lib/api';

export default function SystemHealth() {
  const [health, setHealth] = useState<SystemHealthType | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchHealth = async () => {
      try {
        const data = await api.getSystemHealth();
        setHealth(data);
      } catch (error) {
        console.error('Failed to fetch system health:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchHealth();
    const interval = setInterval(fetchHealth, 3000); // Update every 3s

    return () => clearInterval(interval);
  }, []);

  if (loading || !health) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-8 text-center">
        <Activity className="w-6 h-6 animate-spin mx-auto text-gray-400" />
      </div>
    );
  }

  const successRate = health.total_cycles > 0
    ? (health.successful_cycles / health.total_cycles) * 100
    : 0;

  const uptimeHours = Math.floor(health.uptime_seconds / 3600);
  const uptimeMinutes = Math.floor((health.uptime_seconds % 3600) / 60);

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center">
          <Activity className="w-5 h-5 mr-2" />
          System Health
        </h2>
      </div>

      <div className="p-6">
        {/* Status Overview */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-6">
          <HealthMetric
            icon={health.circuit_breaker_open ? <XCircle className="w-6 h-6" /> : <CheckCircle className="w-6 h-6" />}
            label="Circuit Breaker"
            value={health.circuit_breaker_open ? 'OPEN' : 'CLOSED'}
            color={health.circuit_breaker_open ? 'red' : 'green'}
          />
          <HealthMetric
            icon={<AlertTriangle className="w-6 h-6" />}
            label="Consecutive Errors"
            value={health.consecutive_errors}
            color={health.consecutive_errors > 3 ? 'red' : 'green'}
          />
          <HealthMetric
            icon={<Activity className="w-6 h-6" />}
            label="Success Rate"
            value={`${successRate.toFixed(1)}%`}
            color={successRate >= 90 ? 'green' : successRate >= 70 ? 'yellow' : 'red'}
          />
          <HealthMetric
            icon={<Clock className="w-6 h-6" />}
            label="Uptime"
            value={`${uptimeHours}h ${uptimeMinutes}m`}
            color="blue"
          />
        </div>

        {/* Cycle Statistics */}
        <div className="grid grid-cols-3 gap-4">
          <div className="text-center p-4 bg-gray-50 dark:bg-gray-700/50 rounded-lg">
            <p className="text-2xl font-bold text-gray-900 dark:text-white">{health.total_cycles}</p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Total Cycles</p>
          </div>
          <div className="text-center p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
            <p className="text-2xl font-bold text-green-600 dark:text-green-400">{health.successful_cycles}</p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Successful</p>
          </div>
          <div className="text-center p-4 bg-red-50 dark:bg-red-900/20 rounded-lg">
            <p className="text-2xl font-bold text-red-600 dark:text-red-400">{health.failed_cycles}</p>
            <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">Failed</p>
          </div>
        </div>

        {/* Last Cycle */}
        {health.last_cycle_time && (
          <div className="mt-6 p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg">
            <p className="text-sm text-gray-600 dark:text-gray-300">
              Last cycle: {new Date(health.last_cycle_time).toLocaleString()}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}

function HealthMetric({
  icon,
  label,
  value,
  color,
}: {
  icon: React.ReactNode;
  label: string;
  value: string | number;
  color: 'green' | 'red' | 'yellow' | 'blue';
}) {
  const colorClasses = {
    green: 'bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400',
    red: 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400',
    yellow: 'bg-yellow-100 dark:bg-yellow-900/30 text-yellow-600 dark:text-yellow-400',
    blue: 'bg-blue-100 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400',
  };

  return (
    <div className="flex items-center space-x-3">
      <div className={`p-3 rounded-lg ${colorClasses[color]}`}>
        {icon}
      </div>
      <div>
        <p className="text-sm text-gray-500 dark:text-gray-400">{label}</p>
        <p className={`text-lg font-semibold ${colorClasses[color]}`}>{value}</p>
      </div>
    </div>
  );
}
