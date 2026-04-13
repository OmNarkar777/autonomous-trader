import { useState, useEffect } from 'react';
import { Brain, Activity, AlertCircle, Clock } from 'lucide-react';
import { api, AgentStatus } from '@/lib/api';
import { formatDistanceToNow } from 'date-fns';

export default function AgentStatusPanel() {
  const [agents, setAgents] = useState<AgentStatus[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAgents = async () => {
      try {
        const data = await api.getAgentStatus();
        setAgents(data);
      } catch (error) {
        console.error('Failed to fetch agent status:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchAgents();
    const interval = setInterval(fetchAgents, 5000); // Refresh every 5s

    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-8 text-center">
        <Activity className="w-6 h-6 animate-spin mx-auto text-gray-400" />
        <p className="mt-2 text-gray-500">Loading agents...</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center">
          <Brain className="w-5 h-5 mr-2" />
          Agent Status ({agents.length})
        </h2>
      </div>

      <div className="p-6">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {agents.map((agent) => (
            <AgentCard key={agent.agent_name} agent={agent} />
          ))}
        </div>
      </div>
    </div>
  );
}

function AgentCard({ agent }: { agent: AgentStatus }) {
  const statusConfig = {
    active: {
      icon: <Activity className="w-5 h-5" />,
      bgColor: 'bg-green-100 dark:bg-green-900/30',
      textColor: 'text-green-600 dark:text-green-400',
      label: 'Active',
    },
    idle: {
      icon: <Clock className="w-5 h-5" />,
      bgColor: 'bg-gray-100 dark:bg-gray-700',
      textColor: 'text-gray-600 dark:text-gray-400',
      label: 'Idle',
    },
    error: {
      icon: <AlertCircle className="w-5 h-5" />,
      bgColor: 'bg-red-100 dark:bg-red-900/30',
      textColor: 'text-red-600 dark:text-red-400',
      label: 'Error',
    },
  };

  const config = statusConfig[agent.status];

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-4 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-3">
        <div>
          <h3 className="font-semibold text-gray-900 dark:text-white text-sm">
            {agent.agent_name}
          </h3>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            {agent.last_run ? formatDistanceToNow(new Date(agent.last_run), { addSuffix: true }) : 'Never run'}
          </p>
        </div>
        <div className={`p-2 rounded ${config.bgColor} ${config.textColor}`}>
          {config.icon}
        </div>
      </div>

      <div className="space-y-2">
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500 dark:text-gray-400">Status:</span>
          <span className={`font-medium ${config.textColor}`}>{config.label}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500 dark:text-gray-400">Executions:</span>
          <span className="font-medium text-gray-900 dark:text-white">{agent.execution_count}</span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500 dark:text-gray-400">Avg Time:</span>
          <span className="font-medium text-gray-900 dark:text-white">
            {agent.avg_execution_time_ms.toFixed(0)}ms
          </span>
        </div>
        <div className="flex items-center justify-between text-xs">
          <span className="text-gray-500 dark:text-gray-400">Success Rate:</span>
          <span className={`font-medium ${agent.success_rate >= 90 ? 'text-green-600 dark:text-green-400' : 'text-yellow-600 dark:text-yellow-400'}`}>
            {agent.success_rate.toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Success rate bar */}
      <div className="mt-3">
        <div className="h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
          <div
            className={`h-full transition-all ${agent.success_rate >= 90 ? 'bg-green-500' : 'bg-yellow-500'}`}
            style={{ width: `${agent.success_rate}%` }}
          />
        </div>
      </div>
    </div>
  );
}
