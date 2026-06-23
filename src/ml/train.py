""" src/ml/train.py — Train XGBoost/LightGBM/CatBoost on collected dataset. """

import pandas as pd
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.metrics import classification_report, accuracy_score
import xgboost as xgb
import lightgbm as lgb
import catboost as cb
from src.ml.dataset_storage import DatasetStorage


class MLTrainer:
    """Train ML models on the collected dataset."""

    def __init__(self, model_type: str = "xgboost"):
        self.model_type = model_type
        self.model = None
        self.feature_columns = None
        self.label_encoder = LabelEncoder()

    def prepare_data(self, df: pd.DataFrame) -> tuple:
        """Prepare features and labels for training."""
        # Exclude non-feature columns
        exclude = ['trade_id', 'candle_ts', 'entry_price', 'stop_loss',
                   'take_profit', 'exit_price', 'holding_candles',
                   'return_pct', 'pnl_r', 'triple_barrier', 'llm_decision']

        # Separate features and target
        X = df.drop(columns=exclude + ['triple_barrier'], errors='ignore')
        y = df['triple_barrier']

        # Encode categorical columns
        for col in X.select_dtypes(include=['object']).columns:
            X[col] = self.label_encoder.fit_transform(X[col].astype(str))

        self.feature_columns = X.columns.tolist()
        return X, y

    def train(self, df: pd.DataFrame, test_size: float = 0.2) -> dict:
        """Train the selected model and return metrics."""
        X, y = self.prepare_data(df)
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        if self.model_type == "xgboost":
            self.model = xgb.XGBClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                random_state=42
            )
        elif self.model_type == "lightgbm":
            self.model = lgb.LGBMClassifier(
                n_estimators=200,
                max_depth=6,
                learning_rate=0.05,
                random_state=42
            )
        elif self.model_type == "catboost":
            self.model = cb.CatBoostClassifier(
                iterations=200,
                depth=6,
                learning_rate=0.05,
                random_seed=42,
                verbose=False
            )
        else:
            raise ValueError(f"Unknown model type: {self.model_type}")

        self.model.fit(X_train, y_train)

        # Evaluate
        y_pred = self.model.predict(X_test)
        metrics = {
            'accuracy': accuracy_score(y_test, y_pred),
            'report': classification_report(y_test, y_pred, output_dict=True),
            'feature_importance': dict(zip(self.feature_columns,
                                           self.model.feature_importances_))
        }

        return metrics

    def predict(self, features: pd.DataFrame) -> np.ndarray:
        """Predict labels for new features."""
        if self.model is None:
            raise ValueError("Model not trained yet.")
        return self.model.predict(features)