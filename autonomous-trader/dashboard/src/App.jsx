import { BrowserRouter as Router, Routes, Route, Link } from 'react-router-dom';
import Overview from './pages/Overview';
import Trades from './pages/Trades';
import Agents from './pages/Agents';
import System from './pages/System';
import Recommendations from './pages/Recommendations';

function App() {
  return (
    <Router>
      <div className='min-h-screen bg-gray-50'>
        <nav className='bg-white shadow-sm border-b'>
          <div className='max-w-7xl mx-auto px-4'>
            <div className='flex items-center justify-between h-16'>
              <div className='flex items-center gap-8'>
                <h1 className='text-2xl font-bold'>Autonomous Trader</h1>
                <div className='flex gap-6'>
                  <Link to='/' className='text-gray-600 hover:text-gray-900'>Overview</Link>
                  <Link to='/recommendations' className='text-gray-600 hover:text-gray-900'>Recommendations</Link>
                  <Link to='/trades' className='text-gray-600 hover:text-gray-900'>Trades</Link>
                  <Link to='/agents' className='text-gray-600 hover:text-gray-900'>Agents</Link>
                  <Link to='/system' className='text-gray-600 hover:text-gray-900'>System</Link>
                </div>
              </div>
              <div className='flex items-center gap-2'>
                <span className='w-2 h-2 bg-green-500 rounded-full'></span>
                <span className='text-sm text-gray-600'>Live</span>
              </div>
            </div>
          </div>
        </nav>
        
        <main className='max-w-7xl mx-auto py-6'>
          <Routes>
            <Route path='/' element={<Overview />} />
            <Route path='/recommendations' element={<Recommendations />} />
            <Route path='/trades' element={<Trades />} />
            <Route path='/agents' element={<Agents />} />
            <Route path='/system' element={<System />} />
          </Routes>
        </main>
      </div>
    </Router>
  );
}

export default App;
