import pandas as pd
import numpy as np
from pathlib import Path
import xgboost as xgb
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, roc_auc_score, classification_report
import joblib

# Load all features
all_features = []
for file in Path('data/features').glob('*_features.csv'):
    df = pd.read_csv(file, index_col=0)
    all_features.append(df)

data = pd.concat(all_features, ignore_index=True)
print(f'Total samples: {len(data)}')

# Prepare data
feature_cols = [col for col in data.columns if col != 'target']
X = data[feature_cols].values
y = data['target'].values

# FIX: Handle inf values
X = np.where(np.isinf(X), np.nan, X)
X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

print(f'Cleaned data shape: {X.shape}')

# Train/test split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

# Train simple XGBoost (no grid search for speed)
print('Training XGBoost model...')
xgb_model = xgb.XGBClassifier(
    objective='binary:logistic',
    random_state=42,
    tree_method='hist',
    max_depth=5,
    learning_rate=0.1,
    n_estimators=100,
    subsample=0.8,
    colsample_bytree=0.8
)

xgb_model.fit(X_train, y_train, verbose=False)

# Evaluate
y_pred = xgb_model.predict(X_test)
y_pred_proba = xgb_model.predict_proba(X_test)[:, 1]

accuracy = accuracy_score(y_test, y_pred)
auc = roc_auc_score(y_test, y_pred_proba)

print(f'\n✅ XGBoost Model Trained')
print(f'Test Accuracy: {accuracy:.4f}')
print(f'Test AUC: {auc:.4f}')

# Save model
xgb_model.save_model('models/xgboost_predictor.json')
print('✅ Model saved')

# Sample predictions
print(f'\nSample predictions: {y_pred_proba[:5]}')
print(f'Actual targets: {y_test[:5]}')
