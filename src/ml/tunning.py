import pandas as pd
import numpy as np
import config
from catboost import CatBoostClassifier
from pathlib import Path
from collections import Counter
from src.ml.train import clean_dataset
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)

DATASET_FILE = config.DATASET_DIR + "/ml_dataset_v2.csv"

MODEL_PATH = Path(config.MODEL_SAVE_PATH) / "long_short_depth10_auc0.6014_1.06M.cbm"

def tune():
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

    split = int(len(df) * 0.8)

    X_train = X.iloc[:split]
    X_test = X.iloc[split:]

    y_train = y.iloc[:split]
    y_test = y.iloc[split:]

    result_r_test = df["result_r"].iloc[split:]

    # result_r_test = df["result_r"]

    # X_test = X
    # y_test = y

    model = CatBoostClassifier()

    model.load_model(MODEL_PATH)
    print(model.best_iteration_)
    print(model.best_score_)
  

    pred = model.predict(X_test)
    prob = model.predict_proba(X_test)[:, 1]
    pred = (prob >= 0.33).astype(int)

    print("ROC AUC  :", roc_auc_score(y_test, prob))
    ths = [
        # 0.3,
        # 0.35,
        # 0.4,
        # 0.45,
        # 0.46,
        # 0.47,
        # 0.48,
        # 0.49,
        # 0.5,
        # 0.51,
        # 0.52,
        # 0.53,
        # 0.54,
        # 0.55,
        0.56,
        # 0.57,
        # 0.58,
        # 0.59,
        # 0.6,
        # 0.65,
        # 0.7
        ]
    for th in ths:
        pred = (prob >= th).astype(int)
        selected_r = result_r_test[pred == 1]
        print(th)
        print("Accuracy :", accuracy_score(y_test, pred))
        print("Precision:", precision_score(y_test, pred))
        print("Recall   :", recall_score(y_test, pred))
        print("F1 Score :", f1_score(y_test, pred))

        print("Predicted WIN:", pred.sum())
        print("Predicted LOSE:", len(pred) - pred.sum())

        print("Avg R   :", selected_r.mean())
        print("Total R :", selected_r.sum())
        print("Median R:", selected_r.median())
        print("Profit Factor:", selected_r[selected_r > 0].sum() / abs(selected_r[selected_r < 0].sum()))
        print()

    
    
    

    print("Min  : ",prob.min())
    print("Max  : ",prob.max())
    print("Mean : ",prob.mean())
    
    importance = model.get_feature_importance()

    for col, imp in sorted(zip(X.columns, importance), key=lambda x: x[1], reverse=True):
        print(f"{col:30} {imp:.2f}")