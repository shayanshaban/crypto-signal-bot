import pandas as pd
import numpy as np
import config
from catboost import CatBoostClassifier
from collections import Counter
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    roc_auc_score,
)
DATASET_FILE = config.DATASET_DIR  + "/ml_dataset.csv"



def clean_dataset(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean trading dataset before ML training.

    - Remove duplicate samples
    - Sort chronologically
    - Fill categorical missing values
    - Add support/resistance existence flags
    - Keep MACD NaNs (CatBoost handles them natively)
    """

    df = df.copy()

    # Remove duplicate samples
    df = df.drop_duplicates(subset="sample_id")

    # Sort chronologically
    df = df.sort_values("candle_ts").reset_index(drop=True)

    # ---------- Categorical ----------
    df["engulfing"] = df["engulfing"].fillna("none")

    # ---------- Support ----------
    df["has_support"] = (
        df["distance_support"]
        .notna()
        .astype("int8")
    )

    df["distance_support"] = df["distance_support"].fillna(-1.0)

    # ---------- Resistance ----------
    df["has_resistance"] = (
        df["distance_resistance"]
        .notna()
        .astype("int8")
    )

    df["distance_resistance"] = df["distance_resistance"].fillna(-1.0)

    df["is_win"] = (df["result_r"] > 0).astype(int)

    # IMPORTANT:
    # Leave MACD NaNs unchanged.
    # CatBoost can handle missing numerical values natively.
    # They also indicate that MACD was unavailable for that setup
    # or during indicator warm-up.

    return df
def train():
    df = pd.read_csv(DATASET_FILE)

    df = clean_dataset(df)
    print(df["is_win"].value_counts())
    print(df["is_win"].value_counts(normalize=True))
    
    TARGET = "is_win"

    DROP_COLUMNS = [
        "sample_id",
        "candle_ts",
        TARGET,
        "result_r",
    ]

    X = df.drop(columns=DROP_COLUMNS)
    y = df[TARGET]
    CAT_FEATURES = [
        "symbol",
        "timeframe",
        "setup_type",
        "side",
        "market_structure",
        "candle_type",
        "engulfing",
        "last_3_candles",
    ]
    split = int(len(df) * 0.8)

    X_train = X.iloc[:split]
    X_test = X.iloc[split:]

    y_train = y.iloc[:split]
    y_test = y.iloc[split:]

    counter = Counter(y_train)
    model = CatBoostClassifier(
        iterations=3000,
        learning_rate=0.03,
        depth=8,

        loss_function="Logloss",
        eval_metric="AUC",

        random_seed=42,

        verbose=100,

        early_stopping_rounds=200,
        auto_class_weights="Balanced"
    )
    model.fit(
        X_train,
        y_train,

        cat_features=CAT_FEATURES,

        eval_set=(X_test, y_test),
    )
    # print(model.best_iteration_)
    # print(model.best_score_)
    # pred = model.predict(X_test)

    # print("MAE :", mean_absolute_error(y_test, pred))

    # print("RMSE:", np.sqrt(mean_squared_error(y_test, pred)))

    # print("R²  :", r2_score(y_test, pred))
   
    # print(df["result_r"].describe())

    # print(df["result_r"].value_counts().sort_index())

    # print(df["setup_type"].value_counts())

    # print(model.get_feature_importance())
    pred = model.predict(X_test)
    prob = model.predict_proba(X_test)[:, 1]

    print("Accuracy :", accuracy_score(y_test, pred))
    print("Precision:", precision_score(y_test, pred))
    print("Recall   :", recall_score(y_test, pred))
    print("F1 Score :", f1_score(y_test, pred))
    print("ROC AUC  :", roc_auc_score(y_test, prob))
    importance = model.get_feature_importance()

    for col, imp in sorted(zip(X.columns, importance), key=lambda x: x[1], reverse=True):
        print(f"{col:30} {imp:.2f}")
