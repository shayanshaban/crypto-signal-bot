import pandas as pd
import numpy as np
import config
from catboost import CatBoostClassifier
from pathlib import Path
from collections import Counter
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)

DATASET_FILE = config.DATASET_DIR + "/ml_dataset_v2.csv"


def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:

    df = df.copy()

    # Remove duplicates
    df = df.drop_duplicates(subset="sample_id")

    # Sort by time
    df = df.sort_values("candle_ts").reset_index(drop=True)

    # -------------------------
    # Target
    # -------------------------
    df["is_win"] = (df["result_r"] > 0).astype("int8")

    # -------------------------
    # Fill categorical NaNs
    # -------------------------
    categorical_fill = [
        "engulfing",
        "rsi_zone",
        "stoch_rsi_zone",
        "macd_position",
        "volume_signal",
        "bb_signal",
        "bb_squeeze",
        "market_structure",
        "candle_type",
        "last_3_candles",
        "session",
    ]

    for col in categorical_fill:
        if col in df.columns:
            df[col] = df[col].fillna("unknown")

    # -------------------------
    # Support / Resistance
    # -------------------------
    if "distance_to_support_pct" in df.columns:

        df["has_support"] = (
            df["distance_to_support_pct"]
            .notna()
            .astype("int8")
        )

        df["distance_to_support_pct"] = (
            df["distance_to_support_pct"]
            .fillna(-1.0)
        )

    if "distance_to_resistance_pct" in df.columns:

        df["has_resistance"] = (
            df["distance_to_resistance_pct"]
            .notna()
            .astype("int8")
        )

        df["distance_to_resistance_pct"] = (
            df["distance_to_resistance_pct"]
            .fillna(-1.0)
        )

    return df


def train():
    df = pd.read_csv(DATASET_FILE)
    df = df[df["side"].isin(["LONG", "SHORT"])].copy()
    df = clean_dataset(df)
    print(df["side"].value_counts())

    TARGET = "is_win"

    DROP_COLUMNS = [
        "sample_id",
        "status",
        "result_r",
        "candle_ts",
        "timestamp",
        "id",
        "candle_id",
        "macd_signal",
        "macd_histogram",
        TARGET,
    ]

    df["is_win"] = (df["result_r"] > 0).astype(int)

    X = df.drop(columns=DROP_COLUMNS)
    y = df[TARGET]

    CAT_FEATURES = [
        "symbol",
        "timeframe",
        "side",

        "market_structure",

        "rsi_zone",
        "stoch_rsi_zone",

        "volume_signal",

        "bb_signal",
        "bb_squeeze",

        "session",

        "candle_type",
        "engulfing",
        "last_3_candles",
        "macd_position"
    ]

    split = int(len(df) * 0.8)

    X_train = X.iloc[:split]
    X_test = X.iloc[split:]

    y_train = y.iloc[:split]
    y_test = y.iloc[split:]

    model = CatBoostClassifier(
        iterations=3000,
        learning_rate=0.01,
        depth=10,
        loss_function="Logloss",
        eval_metric="AUC",
        auto_class_weights="Balanced",
        early_stopping_rounds=200,
        random_seed=42,
        verbose=100,
        use_best_model=True,
    )

    model.fit(
        X_train,
        y_train,
        cat_features=CAT_FEATURES,
        eval_set=(X_test, y_test),
    )
    print(model.best_iteration_)
    print(model.best_score_)

    model_save_path = config.MODEL_SAVE_PATH + "/long_short_model.cbm"
    model_save_path = Path(model_save_path)
    model_save_path.parent.mkdir(parents=True, exist_ok=True)
    
    model.save_model(str(model_save_path))
    print(f"Model saved to: {str(model_save_path)}")
   

    pred = model.predict(X_test)
    prob = model.predict_proba(X_test)[:, 1]
    pred = (prob >= 0.33).astype(int)

    # for th in [0.3,0.35,0.4,0.45,0.5,0.6]:
    #     pred = (prob >= th).astype(int)

    #     print(th)
    #     print("Precision", precision_score(y_test,pred))
    #     print("Recall", recall_score(y_test,pred))
    #     print("F1", f1_score(y_test,pred))
    #     print()

    print("Accuracy :", accuracy_score(y_test, pred))
    print("Precision:", precision_score(y_test, pred))
    print("Recall   :", recall_score(y_test, pred))
    print("F1 Score :", f1_score(y_test, pred))
    print("ROC AUC  :", roc_auc_score(y_test, prob))
    prob = model.predict_proba(X_test)[:, 1]

    print(prob.min())
    print(prob.max())
    print(prob.mean())
    print("Predicted WIN:", pred.sum())
    print("Predicted LOSE:", len(pred) - pred.sum())
    importance = model.get_feature_importance()

    for col, imp in sorted(zip(X.columns, importance), key=lambda x: x[1], reverse=True):
        print(f"{col:30} {imp:.2f}")