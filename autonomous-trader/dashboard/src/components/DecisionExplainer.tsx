import { useState, useEffect } from 'react';
import { Brain, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { api, Decision } from '@/lib/api';
import { format } from 'date-fns';

export default function DecisionExplainer() {
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [selectedDecision, setSelectedDecision] = useState<Decision | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchDecisions = async () => {
      try {
        const data = await api.getRecentDecisions(10);
        setDecisions(data);
        if (data.length > 0 && !selectedDecision) {
          setSelectedDecision(data[0]);
        }
      } catch (error) {
        console.error('Failed to fetch decisions:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchDecisions();
    const interval = setInterval(fetchDecisions, 10000); // Update every 10s

    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-8 text-center">
        <Brain className="w-6 h-6 animate-spin mx-auto text-gray-400" />
        <p className="mt-2 text-gray-500">Loading decisions...</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow">
      <div className="p-6 border-b border-gray-200 dark:border-gray-700">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-white flex items-center">
          <Brain className="w-5 h-5 mr-2" />
          Decision Explainer
        </h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          AI decision breakdown and reasoning
        </p>
      </div>

      <div className="p-6">
        {/* Recent Decisions List */}
        <div className="mb-6">
          <h3 className="text-sm font-medium text-gray-700 dark:text-gray-300 mb-3">
            Recent Decisions ({decisions.length})
          </h3>
          <div className="space-y-2">
            {decisions.slice(0, 5).map((decision) => (
              <button
                key={`${decision.symbol}-${decision.timestamp}`}
                onClick={() => setSelectedDecision(decision)}
                className={`w-full text-left p-3 rounded-lg transition-colors ${
                  selectedDecision?.symbol === decision.symbol && selectedDecision?.timestamp === decision.timestamp
                    ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800'
                    : 'bg-gray-50 dark:bg-gray-700/50 hover:bg-gray-100 dark:hover:bg-gray-700'
                }`}
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center space-x-3">
                    <DecisionIcon decision={decision.decision} />
                    <div>
                      <p className="font-medium text-gray-900 dark:text-white">{decision.symbol}</p>
                      <p className="text-xs text-gray-500 dark:text-gray-400">
                        {format(new Date(decision.timestamp), 'MMM dd, HH:mm')}
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-sm font-semibold text-gray-900 dark:text-white">
                      {(decision.confidence * 100).toFixed(0)}%
                    </p>
                    <p className="text-xs text-gray-500 dark:text-gray-400">confidence</p>
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Selected Decision Details */}
        {selectedDecision && (
          <div className="space-y-4">
            <div className="p-4 bg-gradient-to-r from-blue-50 to-purple-50 dark:from-blue-900/20 dark:to-purple-900/20 rounded-lg border border-blue-200 dark:border-blue-800">
              <div className="flex items-center justify-between mb-2">
                <h4 className="text-lg font-bold text-gray-900 dark:text-white">
                  {selectedDecision.symbol}
                </h4>
                <DecisionBadge decision={selectedDecision.decision} />
              </div>
              <p className="text-sm text-gray-600 dark:text-gray-300 mb-3">
                {selectedDecision.reasoning}
              </p>
              <div className="flex items-center justify-between text-xs text-gray-500 dark:text-gray-400">
                <span>Confidence: {(selectedDecision.confidence * 100).toFixed(1)}%</span>
                <span>{format(new Date(selectedDecision.timestamp), 'MMM dd, yyyy HH:mm')}</span>
              </div>
            </div>

            {/* Score Breakdown */}
            <div className="space-y-3">
              <h4 className="text-sm font-medium text-gray-700 dark:text-gray-300">Score Breakdown</h4>
              <ScoreBar
                label="Technical"
                score={selectedDecision.technical_score}
                maxScore={10}
                color="blue"
              />
              <ScoreBar
                label="Fundamental"
                score={selectedDecision.fundamental_score}
                maxScore={10}
                color="green"
              />
              <ScoreBar
                label="Sentiment"
                score={selectedDecision.sentiment_score}
                maxScore={10}
                color="purple"
              />
              <ScoreBar
                label="ML Model"
                score={selectedDecision.ml_score * 10}
                maxScore={10}
                color="orange"
              />
              <div className="pt-3 border-t border-gray-200 dark:border-gray-700">
                <ScoreBar
                  label="Combined"
                  score={selectedDecision.combined_score}
                  maxScore={10}
                  color="indigo"
                  bold
                />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DecisionIcon({ decision }: { decision: string }) {
  if (decision === 'BUY') {
    return (
      <div className="p-2 bg-green-100 dark:bg-green-900/30 text-green-600 dark:text-green-400 rounded">
        <TrendingUp className="w-4 h-4" />
      </div>
    );
  }
  if (decision === 'SELL') {
    return (
      <div className="p-2 bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 rounded">
        <TrendingDown className="w-4 h-4" />
      </div>
    );
  }
  return (
    <div className="p-2 bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400 rounded">
      <Minus className="w-4 h-4" />
    </div>
  );
}

function DecisionBadge({ decision }: { decision: string }) {
  const config = {
    BUY: { label: 'BUY', color: 'bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-400' },
    SELL: { label: 'SELL', color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-400' },
    HOLD: { label: 'HOLD', color: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-400' },
  };

  const { label, color } = config[decision as keyof typeof config] || config.HOLD;

  return (
    <span className={`px-3 py-1 rounded-full text-xs font-bold ${color}`}>
      {label}
    </span>
  );
}

function ScoreBar({
  label,
  score,
  maxScore,
  color,
  bold = false,
}: {
  label: string;
  score: number;
  maxScore: number;
  color: string;
  bold?: boolean;
}) {
  const percentage = (score / maxScore) * 100;
  
  const colorClasses: Record<string, string> = {
    blue: 'bg-blue-500',
    green: 'bg-green-500',
    purple: 'bg-purple-500',
    orange: 'bg-orange-500',
    indigo: 'bg-indigo-500',
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <span className={`text-sm ${bold ? 'font-semibold' : ''} text-gray-700 dark:text-gray-300`}>
          {label}
        </span>
        <span className={`text-sm ${bold ? 'font-bold' : 'font-medium'} text-gray-900 dark:text-white`}>
          {score.toFixed(1)} / {maxScore}
        </span>
      </div>
      <div className="h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div
          className={`h-full ${colorClasses[color]} transition-all duration-500`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
