import React from 'react';

export default function Trades() {
  return (
    <div className='p-6'>
      <h1 className='text-3xl font-bold mb-6'>Trade History</h1>
      <div className='bg-white rounded-lg shadow p-6'>
        <p className='text-gray-600'>No trades yet</p>
      </div>
    </div>
  );
}
