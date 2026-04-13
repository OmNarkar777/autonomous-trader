import numpy as np
import pandas as pd
import tensorflow as tf
import xgboost as xgb
import joblib
from pathlib import Path

class RealMLPredictor:
    def __init__(self):
        try:
            self.lstm_model = tf.keras.models.load_model('models/lstm_predictor.h5')
            self.lstm_scaler = joblib.load('models/lstm_scaler.pkl')
            self.xgb_model = xgb.Booster()
            self.xgb_model.load_model('models/xgboost_predictor.json')
            self.models_loaded = True
            print('✅ Real ML models loaded')
        except Exception as e:
            print(f'⚠️ ML models not found, using fallback: {e}')
            self.models_loaded = False
    
    def predict(self, features_df):
        '''Predict using ensemble of LSTM + XGBoost'''
        if not self.models_loaded:
            return 0.5  # Neutral if models not trained yet
        
        try:
            # Prepare features
            X = features_df.values
            X_scaled = self.lstm_scaler.transform(X)
            X_lstm = X_scaled.reshape((1, 1, X_scaled.shape[1]))
            
            # LSTM prediction
            lstm_pred = self.lstm_model.predict(X_lstm, verbose=0)[0][0]
            
            # XGBoost prediction
            dmatrix = xgb.DMatrix(X)
            xgb_pred = self.xgb_model.predict(dmatrix)[0]
            
            # Ensemble (50/50 weight)
            ensemble_pred = (lstm_pred + xgb_pred) / 2
            
            return float(ensemble_pred)
        except Exception as e:
            print(f'Prediction error: {e}')
            return 0.5
