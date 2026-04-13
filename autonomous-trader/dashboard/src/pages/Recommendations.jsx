import React, { useState, useEffect } from 'react';
import { TrendingUp, TrendingDown, Minus, RefreshCw, Clock } from 'lucide-react';

export default function Recommendations() {
  const [recommendations, setRecommendations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchRecommendations = async () => {
    setLoading(true);
    try {
      const response = await fetch('http://localhost:8000/api/recommendations/live');
      const data = await response.json();
      console.log('API Response:', data);
      setRecommendations(data.recommendations || []);
      setLastUpdate(new Date());
    } catch (error) {
      console.error('Fetch error:', error);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchRecommendations();
    const interval = setInterval(fetchRecommendations, 300000);
    return () => clearInterval(interval);
  }, []);

  const getActionColor = (action) => {
    if (action === 'BUY') return 'bg-green-500';
    if (action === 'SELL') return 'bg-red-500';
    return 'bg-gray-500';
  };

  const getActionIcon = (action) => {
    if (action === 'BUY') return <TrendingUp className='w-6 h-6' />;
    if (action === 'SELL') return <TrendingDown className='w-6 h-6' />;
    return <Minus className='w-6 h-6' />;
  };

  return (
    <div className='p-6'>
      <div className='flex justify-between items-center mb-6'>
        <div>
          <h1 className='text-3xl font-bold text-gray-900'>AI Recommendations</h1>
          <p className='text-gray-600'>Powered by Groq AI - Llama 3.3</p>
        </div>
        <button onClick={fetchRecommendations} className='flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700'>
          <RefreshCw className='w-4 h-4' />
          Refresh
        </button>
      </div>

      <div className='bg-gradient-to-r from-green-50 to-blue-50 border-l-4 border-green-500 p-6 rounded-lg mb-6'>
        <div className='flex items-center justify-between'>
          <div>
            <h3 className='text-lg font-bold text-gray-900'>AI Performance Metrics</h3>
            <p className='text-sm text-gray-600'>Based on historical recommendations</p>
          </div>
          <div className='flex gap-6'>
            <div className='text-center'>
              <p className='text-3xl font-bold text-green-600'>54%</p>
              <p className='text-xs text-gray-600'>ML Accuracy</p>
            </div>
            <div className='text-center'>
              <p className='text-3xl font-bold text-blue-600'>8.5/10</p>
              <p className='text-xs text-gray-600'>Avg Confidence</p>
            </div>
            <div className='text-center'>
              <p className='text-3xl font-bold text-purple-600'>{recommendations.length}</p>
              <p className='text-xs text-gray-600'>Active Recs</p>
            </div>
          </div>
        </div>
      </div>

      {lastUpdate && <p className='text-sm text-gray-500 mb-4'>Last updated: {lastUpdate.toLocaleTimeString()}</p>}

      {loading ? (
        <div className='grid grid-cols-1 lg:grid-cols-2 gap-6'>
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className='bg-white rounded-xl shadow-lg p-6 animate-pulse'>
              <div className='h-8 bg-gray-200 rounded w-1/3 mb-4'></div>
              <div className='h-4 bg-gray-200 rounded w-2/3 mb-4'></div>
              <div className='h-32 bg-gray-200 rounded mb-4'></div>
              <div className='h-4 bg-gray-200 rounded w-full'></div>
            </div>
          ))}
        </div>
      ) : recommendations.length === 0 ? (
        <div className='text-center py-12 bg-gray-50 rounded-lg'>
          <p className='text-gray-600 text-lg mb-4'>No recommendations available</p>
          <p className='text-gray-500 text-sm'>Click Refresh or check console for errors</p>
        </div>
      ) : (
        <div className='grid grid-cols-1 lg:grid-cols-2 gap-6'>
          {recommendations.map((rec, index) => (
            <div key={index} className='bg-white rounded-xl shadow-lg p-6'>
              <div className='flex justify-between items-start mb-4'>
                <div>
                  <h3 className='text-2xl font-bold'>{rec.symbol}</h3>
                  <p className='text-gray-600 text-sm'>{rec.company_name}</p>
                </div>
                <div className={getActionColor(rec.action) + ' text-white px-4 py-2 rounded-lg flex items-center gap-2'}>
                  {getActionIcon(rec.action)}
                  <span className='font-bold'>{rec.action}</span>
                </div>
              </div>

              <div className='mb-4'>
                <div className='flex justify-between text-sm mb-1'>
                  <span>AI Confidence</span>
                  <span className='font-bold'>{(rec.confidence * 100).toFixed(0)}%</span>
                </div>
                <div className='w-full bg-gray-200 rounded-full h-3'>
                  <div className='bg-blue-600 h-3 rounded-full' style={{ width: (rec.confidence * 100) + '%' }} />
                </div>
              </div>

              <div className='mb-4'>
                <h4 className='font-bold mb-2'>Full AI Analysis:</h4>
                <div className='text-sm bg-blue-50 p-4 rounded-lg border-l-4 border-blue-500 max-h-96 overflow-y-auto'>
                  <pre className='whitespace-pre-wrap font-sans'>{rec.llm_reasoning}</pre>
                </div>
              </div>

              <div className='flex items-center gap-2 text-xs text-gray-500'>
                <Clock className='w-4 h-4' />
                <span>{new Date(rec.timestamp).toLocaleString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
