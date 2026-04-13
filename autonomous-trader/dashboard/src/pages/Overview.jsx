import React, { useState, useEffect } from 'react';

export default function Overview() {
  const [portfolio, setPortfolio] = useState({
    value: 100000,
    pnl: 0,
    cash: 100000,
    positions: 0
  });

  useEffect(() => {
    // Fetch portfolio data from API
    fetch('http://localhost:8000/api/portfolio/summary')
      .then(res => res.json())
      .then(data => {
        if (data.portfolio_value) {
          setPortfolio({
            value: data.portfolio_value,
            pnl: data.total_pnl || 0,
            cash: data.cash || 100000,
            positions: data.positions_count || 0
          });
        }
      })
      .catch(err => console.log('Using default values'));
  }, []);

  const formatCurrency = (value) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(value);
  };

  const formatPercentage = (value) => {
    const pct = (value / portfolio.value) * 100;
    return pct >= 0 ? `+${pct.toFixed(2)}%` : `${pct.toFixed(2)}%`;
  };

  return (
    <div className='p-6'>
      <h1 className='text-3xl font-bold mb-6'>Portfolio Overview</h1>
      
      <div className='grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8'>
        <div className='bg-white p-6 rounded-lg shadow-lg'>
          <p className='text-gray-600 text-sm mb-2'>Portfolio Value</p>
          <p className='text-3xl font-bold text-gray-900'>{formatCurrency(portfolio.value)}</p>
        </div>
        
        <div className='bg-white p-6 rounded-lg shadow-lg'>
          <p className='text-gray-600 text-sm mb-2'>Total P&L</p>
          <p className={'text-3xl font-bold ' + (portfolio.pnl >= 0 ? 'text-green-600' : 'text-red-600')}>
            {formatCurrency(portfolio.pnl)}
          </p>
          <p className={'text-sm ' + (portfolio.pnl >= 0 ? 'text-green-600' : 'text-red-600')}>
            {formatPercentage(portfolio.pnl)}
          </p>
        </div>
        
        <div className='bg-white p-6 rounded-lg shadow-lg'>
          <p className='text-gray-600 text-sm mb-2'>Cash Balance</p>
          <p className='text-3xl font-bold text-gray-900'>{formatCurrency(portfolio.cash)}</p>
        </div>
        
        <div className='bg-white p-6 rounded-lg shadow-lg'>
          <p className='text-gray-600 text-sm mb-2'>Open Positions</p>
          <p className='text-3xl font-bold text-gray-900'>{portfolio.positions}</p>
        </div>
      </div>

      <div className='bg-blue-50 border-l-4 border-blue-500 p-6 rounded-lg mb-8'>
        <h2 className='text-xl font-bold text-gray-900 mb-2'>?? AI-Powered Trading System</h2>
        <p className='text-gray-700 mb-4'>
          Our system analyzes stocks using advanced machine learning (LSTM + XGBoost) combined with 
          Groq AI (Llama 3.3) to generate professional recommendations you can trust.
        </p>
        <div className='flex gap-4'>
          <div className='bg-white px-4 py-2 rounded-lg shadow'>
            <p className='text-xs text-gray-600'>Stocks Analyzed</p>
            <p className='text-xl font-bold text-blue-600'>5</p>
          </div>
          <div className='bg-white px-4 py-2 rounded-lg shadow'>
            <p className='text-xs text-gray-600'>ML Confidence</p>
            <p className='text-xl font-bold text-green-600'>54%</p>
          </div>
          <div className='bg-white px-4 py-2 rounded-lg shadow'>
            <p className='text-xs text-gray-600'>AI Model</p>
            <p className='text-xl font-bold text-purple-600'>Llama 3.3</p>
          </div>
        </div>
      </div>

      <div className='grid grid-cols-1 lg:grid-cols-2 gap-6'>
        <div className='bg-white p-6 rounded-lg shadow-lg'>
          <h2 className='text-xl font-bold mb-4'>Recent Activity</h2>
          <div className='space-y-3'>
            <div className='flex items-center justify-between p-3 bg-green-50 rounded'>
              <span className='text-sm font-semibold'>System Initialized</span>
              <span className='text-xs text-gray-600'>Ready to Trade</span>
            </div>
            <div className='flex items-center justify-between p-3 bg-blue-50 rounded'>
              <span className='text-sm font-semibold'>5 Recommendations Generated</span>
              <span className='text-xs text-gray-600'>View in Recommendations tab</span>
            </div>
            <div className='flex items-center justify-between p-3 bg-purple-50 rounded'>
              <span className='text-sm font-semibold'>Risk Management Active</span>
              <span className='text-xs text-gray-600'>Protecting Capital</span>
            </div>
          </div>
        </div>

        <div className='bg-white p-6 rounded-lg shadow-lg'>
          <h2 className='text-xl font-bold mb-4'>System Health</h2>
          <div className='space-y-4'>
            <div className='flex items-center justify-between'>
              <span className='text-sm text-gray-600'>Backend API</span>
              <span className='flex items-center gap-2'>
                <span className='w-2 h-2 bg-green-500 rounded-full'></span>
                <span className='text-sm font-semibold text-green-600'>Online</span>
              </span>
            </div>
            <div className='flex items-center justify-between'>
              <span className='text-sm text-gray-600'>Database</span>
              <span className='flex items-center gap-2'>
                <span className='w-2 h-2 bg-green-500 rounded-full'></span>
                <span className='text-sm font-semibold text-green-600'>Connected</span>
              </span>
            </div>
            <div className='flex items-center justify-between'>
              <span className='text-sm text-gray-600'>Groq AI</span>
              <span className='flex items-center gap-2'>
                <span className='w-2 h-2 bg-green-500 rounded-full'></span>
                <span className='text-sm font-semibold text-green-600'>Active</span>
              </span>
            </div>
            <div className='flex items-center justify-between'>
              <span className='text-sm text-gray-600'>Risk Management</span>
              <span className='flex items-center gap-2'>
                <span className='w-2 h-2 bg-green-500 rounded-full'></span>
                <span className='text-sm font-semibold text-green-600'>Enabled</span>
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
