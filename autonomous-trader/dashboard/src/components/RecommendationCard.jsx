import React from 'react';
import { TrendingUp, TrendingDown, Minus, Target, Shield, Clock } from 'lucide-react';

export default function RecommendationCard({ rec }) {
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
    <div className='bg-white rounded-xl shadow-lg p-6 hover:shadow-xl transition-shadow'>
      {/* Header */}
      <div className='flex justify-between items-start mb-4'>
        <div>
          <h3 className='text-2xl font-bold text-gray-900'>{rec.symbol}</h3>
          <p className='text-gray-600 text-sm'>{rec.company_name}</p>
        </div>
        <div className={\\ text-white px-4 py-2 rounded-lg flex items-center gap-2\}>
          {getActionIcon(rec.action)}
          <span className='font-bold text-lg'>{rec.action}</span>
        </div>
      </div>

      {/* Confidence Bar */}
      <div className='mb-4'>
        <div className='flex justify-between text-sm mb-1'>
          <span className='text-gray-600'>AI Confidence</span>
          <span className='font-bold text-gray-900'>{(rec.confidence * 100).toFixed(0)}%</span>
        </div>
        <div className='w-full bg-gray-200 rounded-full h-3'>
          <div 
            className='bg-blue-600 h-3 rounded-full transition-all'
            style={{ width: \\%\ }}
          />
        </div>
      </div>

      {/* Price Info */}
      <div className='grid grid-cols-3 gap-4 mb-4 p-4 bg-gray-50 rounded-lg'>
        <div>
          <p className='text-xs text-gray-500'>Current Price</p>
          <p className='text-lg font-bold'>\</p>
        </div>
        <div>
          <p className='text-xs text-gray-500 flex items-center gap-1'>
            <Target className='w-3 h-3' /> Target
          </p>
          <p className='text-lg font-bold text-green-600'>\</p>
        </div>
        <div>
          <p className='text-xs text-gray-500 flex items-center gap-1'>
            <Shield className='w-3 h-3' /> Stop Loss
          </p>
          <p className='text-lg font-bold text-red-600'>\</p>
        </div>
      </div>

      {/* Analysis Scores */}
      <div className='grid grid-cols-4 gap-2 mb-4'>
        <div className='text-center p-2 bg-blue-50 rounded'>
          <p className='text-xs text-gray-600'>Technical</p>
          <p className='text-sm font-bold'>{(rec.technical_score * 10).toFixed(1)}/10</p>
        </div>
        <div className='text-center p-2 bg-purple-50 rounded'>
          <p className='text-xs text-gray-600'>Sentiment</p>
          <p className='text-sm font-bold'>{(rec.sentiment_score * 10).toFixed(1)}/10</p>
        </div>
        <div className='text-center p-2 bg-green-50 rounded'>
          <p className='text-xs text-gray-600'>ML Score</p>
          <p className='text-sm font-bold'>{(rec.ml_score * 10).toFixed(1)}/10</p>
        </div>
        <div className='text-center p-2 bg-orange-50 rounded'>
          <p className='text-xs text-gray-600'>Fundamental</p>
          <p className='text-sm font-bold'>{(rec.fundamental_score * 10).toFixed(1)}/10</p>
        </div>
      </div>

      {/* LLM Reasoning */}
      <div className='mb-4'>
        <h4 className='font-bold text-gray-900 mb-2'>AI Analysis:</h4>
        <div className='text-sm text-gray-700 leading-relaxed bg-blue-50 p-4 rounded-lg border-l-4 border-blue-500'>
          {rec.llm_reasoning}
        </div>
      </div>

      {/* Timestamp */}
      <div className='flex items-center gap-2 text-xs text-gray-500'>
        <Clock className='w-4 h-4' />
        <span>Updated: {new Date(rec.timestamp).toLocaleString()}</span>
      </div>

      {/* Action Button */}
      <button className='w-full mt-4 bg-gradient-to-r from-blue-600 to-blue-700 text-white py-3 rounded-lg font-semibold hover:from-blue-700 hover:to-blue-800 transition-all shadow-md hover:shadow-lg'>
        View Detailed Analysis →
      </button>
    </div>
  );
}
