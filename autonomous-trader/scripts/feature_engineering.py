import pandas as pd
import numpy as np
import ta
from pathlib import Path

def create_features(df):
    '''Generate 60+ technical and statistical features'''
    
    # FIX: Convert columns to numeric (yfinance sometimes returns strings)
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    
    # Drop rows with NaN in essential columns
    df = df.dropna(subset=['Close'])
    
    features = pd.DataFrame(index=df.index)
    
    # Price features
    features['returns_1d'] = df['Close'].pct_change(1)
    features['returns_5d'] = df['Close'].pct_change(5)
    features['returns_20d'] = df['Close'].pct_change(20)
    features['returns_60d'] = df['Close'].pct_change(60)
    
    # Volatility
    features['volatility_10d'] = df['Close'].pct_change().rolling(10).std()
    features['volatility_20d'] = df['Close'].pct_change().rolling(20).std()
    
    # Volume
    features['volume_ratio'] = df['Volume'] / df['Volume'].rolling(20).mean()
    features['volume_change'] = df['Volume'].pct_change()
    
    # Technical indicators
    features['rsi'] = ta.momentum.RSIIndicator(df['Close'], window=14).rsi()
    features['rsi_30'] = ta.momentum.RSIIndicator(df['Close'], window=30).rsi()
    
    macd = ta.trend.MACD(df['Close'])
    features['macd'] = macd.macd()
    features['macd_signal'] = macd.macd_signal()
    features['macd_diff'] = macd.macd_diff()
    
    bb = ta.volatility.BollingerBands(df['Close'])
    features['bb_high'] = bb.bollinger_hband_indicator()
    features['bb_low'] = bb.bollinger_lband_indicator()
    features['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / df['Close']
    
    features['stoch_k'] = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close']).stoch()
    features['stoch_d'] = ta.momentum.StochasticOscillator(df['High'], df['Low'], df['Close']).stoch_signal()
    
    features['adx'] = ta.trend.ADXIndicator(df['High'], df['Low'], df['Close']).adx()
    features['cci'] = ta.trend.CCIIndicator(df['High'], df['Low'], df['Close']).cci()
    features['mfi'] = ta.volume.MFIIndicator(df['High'], df['Low'], df['Close'], df['Volume']).money_flow_index()
    
    # Moving averages
    for period in [5, 10, 20, 50, 200]:
        features[f'sma_{period}'] = df['Close'].rolling(period).mean()
        features[f'ema_{period}'] = df['Close'].ewm(span=period).mean()
        features[f'distance_to_sma_{period}'] = (df['Close'] - features[f'sma_{period}']) / features[f'sma_{period}']
    
    # Momentum
    for period in [5, 10, 20]:
        features[f'momentum_{period}'] = df['Close'] - df['Close'].shift(period)
        features[f'roc_{period}'] = ((df['Close'] - df['Close'].shift(period)) / df['Close'].shift(period)) * 100
    
    # Support/Resistance
    features['high_52w'] = df['High'].rolling(252).max()
    features['low_52w'] = df['Low'].rolling(252).min()
    features['distance_to_high'] = (features['high_52w'] - df['Close']) / df['Close']
    features['distance_to_low'] = (df['Close'] - features['low_52w']) / df['Close']
    
    # Target variable (next day returns > 0)
    features['target'] = (df['Close'].shift(-1) > df['Close']).astype(int)
    
    # Drop NaN rows
    features = features.dropna()
    
    return features

# Process all symbols
processed = 0
failed = 0
for csv_file in Path('data/historical').glob('*.csv'):
    try:
        print(f'Processing {csv_file.stem}...')
        df = pd.read_csv(csv_file, index_col=0, parse_dates=True)
        features = create_features(df)
        features.to_csv(f'data/features/{csv_file.stem}_features.csv')
        print(f'✅ {csv_file.stem}: {len(features)} samples, {len(features.columns)} features')
        processed += 1
    except Exception as e:
        print(f'❌ {csv_file.stem}: {e}')
        failed += 1

print(f'\n✅ Feature engineering complete: {processed} successful, {failed} failed')
