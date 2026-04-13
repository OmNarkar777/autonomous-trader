import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
import os

# Create directories
os.makedirs('data/historical', exist_ok=True)
os.makedirs('data/features', exist_ok=True)

# Watchlist
SYMBOLS = [
    # India
    'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS',
    'WIPRO.NS', 'AXISBANK.NS', 'KOTAKBANK.NS', 'LT.NS', 'BAJFINANCE.NS',
    'SBIN.NS', 'ASIANPAINT.NS', 'TITAN.NS', 'NESTLEIND.NS', 'DMART.NS',
    # US
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'JPM', 'V', 'WMT', 'PG', 'JNJ'
]

print('Downloading 5 years of historical data...')
start_date = (datetime.now() - timedelta(days=365*5)).strftime('%Y-%m-%d')
end_date = datetime.now().strftime('%Y-%m-%d')

for symbol in SYMBOLS:
    try:
        print(f'Downloading {symbol}...')
        data = yf.download(symbol, start=start_date, end=end_date, progress=False)
        data.to_csv(f'data/historical/{symbol}.csv')
        print(f'✅ {symbol}: {len(data)} days')
    except Exception as e:
        print(f'❌ {symbol}: {e}')

print('✅ Historical data download complete')
