import pandas as pd
import numpy as np
from pathlib import Path
import tensorflow as tf
from tensorflow.keras.models import Sequential
from tensorflow.keras.layers import LSTM, Dense, Dropout
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import joblib

# Combine all features
all_features = []
for file in Path('data/features').glob('*_features.csv'):
    df = pd.read_csv(file, index_col=0)
    df['symbol'] = file.stem.replace('_features', '')
    all_features.append(df)

data = pd.concat(all_features, ignore_index=True)
print(f'Total samples: {len(data)}')

# Prepare data
feature_cols = [col for col in data.columns if col not in ['target', 'symbol']]
X = data[feature_cols].values
y = data['target'].values

# FIX: Replace inf/-inf with NaN, then fill with 0
X = np.where(np.isinf(X), np.nan, X)
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

print(f'Cleaned data shape: {X.shape}')
print(f'Target distribution: {np.bincount(y.astype(int))}')

# Scale features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# Train/test split (80/20)
X_train, X_test, y_train, y_test = train_test_split(X_scaled, y, test_size=0.2, random_state=42, stratify=y)

# Reshape for LSTM (samples, timesteps, features)
X_train = X_train.reshape((X_train.shape[0], 1, X_train.shape[1]))
X_test = X_test.reshape((X_test.shape[0], 1, X_test.shape[1]))

print(f'Training samples: {len(X_train)}')
print(f'Test samples: {len(X_test)}')

# Build LSTM model
model = Sequential([
    LSTM(64, return_sequences=True, input_shape=(1, X_train.shape[2])),
    Dropout(0.2),
    LSTM(32),
    Dropout(0.2),
    Dense(16, activation='relu'),
    Dense(1, activation='sigmoid')
])

model.compile(optimizer='adam', loss='binary_crossentropy', metrics=['accuracy', tf.keras.metrics.AUC(name='auc')])

# Train with early stopping
early_stop = tf.keras.callbacks.EarlyStopping(monitor='val_loss', patience=10, restore_best_weights=True)
reduce_lr = tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=5, min_lr=0.00001)

print('\nTraining LSTM model...')
history = model.fit(
    X_train, y_train,
    validation_data=(X_test, y_test),
    epochs=50,  # Reduced from 100 for speed
    batch_size=64,
    callbacks=[early_stop, reduce_lr],
    verbose=1
)

# Save model
model.save('models/lstm_predictor.h5')
joblib.dump(scaler, 'models/lstm_scaler.pkl')
print('✅ Model saved')

# Evaluate
loss, accuracy, auc = model.evaluate(X_test, y_test, verbose=0)
print(f'\n✅ LSTM Model Trained')
print(f'Test Accuracy: {accuracy:.4f}')
print(f'Test AUC: {auc:.4f}')

# Prediction test
sample_pred = model.predict(X_test[:5], verbose=0)
print(f'\nSample predictions: {sample_pred.flatten()}')
print(f'Actual targets: {y_test[:5]}')
