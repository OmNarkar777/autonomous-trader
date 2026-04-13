import { useState, useEffect } from 'react';
import { api, Portfolio, Position } from '@/lib/api';
import { useWebSocket } from './useWebSocket';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

export function usePortfolio() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // WebSocket for real-time updates
  const { isConnected, lastMessage } = useWebSocket(`${WS_URL}/portfolio`, {
    onMessage: (message) => {
      if (message.type === 'portfolio_update') {
        setPortfolio(message.data.portfolio);
        setPositions(message.data.positions || []);
      } else if (message.type === 'position_update') {
        // Update individual position
        setPositions((prev) => {
          const index = prev.findIndex(p => p.symbol === message.data.symbol);
          if (index >= 0) {
            const updated = [...prev];
            updated[index] = message.data;
            return updated;
          }
          return [...prev, message.data];
        });
      }
    },
  });

  // Initial fetch
  useEffect(() => {
    let mounted = true;

    const fetchPortfolio = async () => {
      try {
        setLoading(true);
        setError(null);
        
        const [portfolioData, positionsData] = await Promise.all([
          api.getPortfolio(),
          api.getPositions(),
        ]);

        if (mounted) {
          setPortfolio(portfolioData);
          setPositions(positionsData);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to fetch portfolio');
          console.error('Portfolio fetch error:', err);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    fetchPortfolio();

    return () => {
      mounted = false;
    };
  }, []);

  // Refresh function
  const refresh = async () => {
    try {
      const [portfolioData, positionsData] = await Promise.all([
        api.getPortfolio(),
        api.getPositions(),
      ]);
      
      setPortfolio(portfolioData);
      setPositions(positionsData);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to refresh portfolio');
      console.error('Portfolio refresh error:', err);
    }
  };

  return {
    portfolio,
    positions,
    loading,
    error,
    isLive: isConnected,
    refresh,
  };
}
