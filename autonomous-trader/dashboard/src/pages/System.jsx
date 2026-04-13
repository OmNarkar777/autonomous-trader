import React from 'react';

export default function System() {
  return (
    <div className='p-6'>
      <h1 className='text-3xl font-bold mb-6'>System Health</h1>
      <div className='bg-white rounded-lg shadow p-6'>
        <div className='flex items-center gap-2'>
          <div className='w-3 h-3 bg-green-500 rounded-full'></div>
          <p className='font-semibold'>System Healthy</p>
        </div>
      </div>
    </div>
  );
}
