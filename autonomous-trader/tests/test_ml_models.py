"""
tests/test_ml_models.py
=======================
Tests for ML models (LSTM, XGBoost, Ensemble).
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

from ml.models.lstm_model import LSTMPredictor
from ml.models.xgboost_model import XGBoostPredictor
from ml.models.ensemble import EnsemblePredictor


@pytest.fixture
def sample_data():
    """Generate sample OHLCV data for testing."""
    dates = pd.date_range(end=datetime.now(), periods=500, freq='D')
    
    np.random.seed(42)
    base_price = 100
    returns = np.random.randn(500) * 0.02
    prices = base_price * (1 + returns).cumprod()
    
    df = pd.DataFrame({
        'Open': prices * (1 + np.random.randn(500) * 0.01),
        'High': prices * (1 + np.abs(np.random.randn(500)) * 0.02),
        'Low': prices * (1 - np.abs(np.random.randn(500)) * 0.02),
        'Close': prices,
        'Volume': np.random.randint(1000000, 10000000, 500),
    }, index=dates)
    
    return df


class TestLSTMModel:
    """Tests for LSTM model."""
    
    def test_model_initialization(self):
        """Test LSTM model can be initialized."""
        model = LSTMPredictor(symbol="TEST")
        assert model.symbol == "TEST"
        assert model.model is None  # Not built yet
    
    def test_model_training(self, sample_data):
        """Test LSTM model training."""
        model = LSTMPredictor(symbol="TEST")
        
        result = model.train(
            sample_data,
            validation_split=0.2,
            epochs=5,  # Small number for testing
            batch_size=32,
            verbose=0
        )
        
        assert result is not None
        assert result.epochs_trained > 0
        assert result.final_loss > 0
        assert result.val_loss > 0
        assert result.train_samples > 0
        assert result.val_samples > 0
    
    def test_model_prediction(self, sample_data):
        """Test LSTM model prediction."""
        model = LSTMPredictor(symbol="TEST")
        
        # Train first
        model.train(sample_data, epochs=5, verbose=0)
        
        # Predict
        prediction = model.predict(sample_data)
        
        assert prediction is not None
        assert 0 <= prediction.prob_up_1day <= 1
        assert 0 <= prediction.prob_up_3day <= 1
        assert 0 <= prediction.prob_up_7day <= 1
        assert 0 <= prediction.confidence <= 1
    
    def test_model_save_load(self, sample_data, tmp_path):
        """Test saving and loading LSTM model."""
        model = LSTMPredictor(symbol="TEST")
        
        # Train
        model.train(sample_data, epochs=5, verbose=0)
        
        # Save
        save_path = tmp_path / "lstm_test"
        model.save(save_path)
        
        # Load
        loaded_model = LSTMPredictor(symbol="TEST")
        loaded_model.load(save_path)
        
        # Should make same predictions
        pred1 = model.predict(sample_data)
        pred2 = loaded_model.predict(sample_data)
        
        np.testing.assert_almost_equal(pred1.prob_up_1day, pred2.prob_up_1day, decimal=3)


class TestXGBoostModel:
    """Tests for XGBoost model."""
    
    def test_model_initialization(self):
        """Test XGBoost model can be initialized."""
        model = XGBoostPredictor(symbol="TEST")
        assert model.symbol == "TEST"
        assert model.model is None
    
    def test_model_training(self, sample_data):
        """Test XGBoost model training."""
        model = XGBoostPredictor(symbol="TEST")
        
        result = model.train(sample_data, test_size=0.2)
        
        assert result is not None
        assert 0 <= result.train_accuracy <= 1
        assert 0 <= result.test_accuracy <= 1
        assert 0 <= result.train_auc <= 1
        assert 0 <= result.test_auc <= 1
        assert result.n_estimators_used > 0
        assert isinstance(result.feature_importance, dict)
    
    def test_model_prediction(self, sample_data):
        """Test XGBoost model prediction."""
        model = XGBoostPredictor(symbol="TEST")
        
        # Train first
        model.train(sample_data)
        
        # Predict
        prediction = model.predict(sample_data)
        
        assert prediction is not None
        assert 0 <= prediction.prob_up <= 1
        assert 0 <= prediction.confidence <= 1
    
    def test_feature_importance(self, sample_data):
        """Test feature importance extraction."""
        model = XGBoostPredictor(symbol="TEST")
        
        model.train(sample_data)
        
        importance = model.get_feature_importance(top_n=10)
        
        assert isinstance(importance, dict)
        assert len(importance) > 0
        assert len(importance) <= 10
    
    def test_model_save_load(self, sample_data, tmp_path):
        """Test saving and loading XGBoost model."""
        model = XGBoostPredictor(symbol="TEST")
        
        model.train(sample_data)
        
        # Save
        save_path = tmp_path / "xgb_test"
        model.save(save_path)
        
        # Load
        loaded_model = XGBoostPredictor(symbol="TEST")
        loaded_model.load(save_path)
        
        # Should make same predictions
        pred1 = model.predict(sample_data)
        pred2 = loaded_model.predict(sample_data)
        
        np.testing.assert_almost_equal(pred1.prob_up, pred2.prob_up, decimal=3)


class TestEnsembleModel:
    """Tests for Ensemble model."""
    
    def test_model_initialization(self):
        """Test Ensemble model can be initialized."""
        model = EnsemblePredictor(symbol="TEST")
        assert model.symbol == "TEST"
        assert model.lstm_model is not None
        assert model.xgboost_model is not None
    
    def test_model_training(self, sample_data):
        """Test Ensemble model training."""
        model = EnsemblePredictor(symbol="TEST")
        
        result = model.train(
            sample_data,
            lstm_epochs=5,
            lstm_verbose=0,
            xgb_verbose=False
        )
        
        assert result is not None
        assert "lstm" in result
        assert "xgboost" in result
    
    def test_model_prediction(self, sample_data):
        """Test Ensemble model prediction."""
        model = EnsemblePredictor(symbol="TEST")
        
        # Train first
        model.train(sample_data, lstm_epochs=5, lstm_verbose=0, xgb_verbose=False)
        
        # Predict
        prediction = model.predict(sample_data)
        
        assert prediction is not None
        assert 0 <= prediction.score <= 1
        assert prediction.decision in ["BUY", "SELL", "HOLD"]
        assert 0 <= prediction.confidence <= 1
        assert prediction.lstm_prediction is not None
        assert prediction.xgboost_prediction is not None
        assert 0 <= prediction.model_agreement <= 1
    
    def test_disagreement_detection(self, sample_data):
        """Test that model disagreement is detected."""
        model = EnsemblePredictor(symbol="TEST")
        
        model.train(sample_data, lstm_epochs=5, lstm_verbose=0, xgb_verbose=False)
        
        prediction = model.predict(sample_data)
        
        # If disagreement_flag is True, agreement should be low
        if prediction.disagreement_flag:
            assert prediction.model_agreement < 0.6
    
    def test_decision_thresholds(self, sample_data):
        """Test that decision thresholds work correctly."""
        model = EnsemblePredictor(symbol="TEST")
        
        model.train(sample_data, lstm_epochs=5, lstm_verbose=0, xgb_verbose=False)
        
        prediction = model.predict(sample_data)
        
        # Check decision matches score
        if prediction.score >= 0.65:
            assert prediction.decision == "BUY"
        elif prediction.score <= 0.35:
            assert prediction.decision == "SELL"
        else:
            assert prediction.decision == "HOLD"
    
    def test_model_save_load(self, sample_data, tmp_path):
        """Test saving and loading Ensemble model."""
        model = EnsemblePredictor(symbol="TEST")
        
        model.train(sample_data, lstm_epochs=5, lstm_verbose=0, xgb_verbose=False)
        
        # Save
        save_path = tmp_path / "ensemble_test"
        model.save(save_path)
        
        # Load
        loaded_model = EnsemblePredictor(symbol="TEST")
        loaded_model.load(save_path)
        
        # Should make same predictions
        pred1 = model.predict(sample_data)
        pred2 = loaded_model.predict(sample_data)
        
        np.testing.assert_almost_equal(pred1.score, pred2.score, decimal=3)
        assert pred1.decision == pred2.decision
